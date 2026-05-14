from datetime import datetime, timezone
import json
from typing import TypedDict
import uuid
from sqlalchemy.orm.attributes import flag_modified

from nova_manager.database.session import db_session
from nova_manager.core.log import logger
from nova_manager.service.clickhouse_service import ClickHouseService
from nova_manager.service.analytics_factory import get_analytics_service

from nova_manager.components.metrics.artefacts import EventsArtefacts
from nova_manager.components.metrics.crud import EventsSchemaCRUD, UserProfileKeysCRUD
from nova_manager.components.user_experience.models import UserExperience
from nova_manager.components.metrics.models import EventsSchema
from nova_manager.components.users.models import Users


class TrackEvent(TypedDict):
    event_name: str
    event_data: dict | None = None
    timestamp: datetime | None = None


class EventsController(EventsArtefacts):
    def __init__(self, organisation_id: str, app_id: str, analytics_backend: str = "clickhouse"):
        super().__init__(organisation_id, app_id)
        self.analytics_backend = analytics_backend

    def _get_service(self):
        """Return the analytics service for the configured backend.
        For ADX, targets the per-org/app database."""
        if self.analytics_backend == "adx":
            from nova_manager.service.adx_service import ADXService
            return ADXService(database=self.database_name)
        return get_analytics_service(self.analytics_backend)

    def _adx_table_name(self, ch_table: str) -> str:
        """Extract plain table name from ClickHouse's db.table format for KQL."""
        return ch_table.split(".")[-1] if "." in ch_table else ch_table

    def create_database(self):
        if self.analytics_backend == "adx":
            import subprocess
            from nova_manager.core.config import ADX_CLUSTER_URI
            # Use ARM API (az kusto database create) — Kusto control plane
            # doesn't grant us .create database, but ARM does.
            result = subprocess.run(
                [
                    "az", "kusto", "database", "create",
                    "--cluster-name", ADX_CLUSTER_URI.split("//")[1].split(".")[0],
                    "--resource-group", "KR-ESports-RG-Dev",
                    "--database-name", self.database_name,
                    "--read-write-database",
                    "soft-delete-period=P365D",
                    "hot-cache-period=P31D",
                    "location=Central India",
                ],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                # Database may already exist — that's fine
                if "already exists" in result.stderr.lower() or "conflict" in result.stderr.lower():
                    logger.info(f"ADX database already exists: {self.database_name}")
                else:
                    logger.error(f"ADX database creation failed: {result.stderr}")
                    raise RuntimeError(f"Failed to create ADX database: {result.stderr}")
            else:
                logger.info(f"ADX database created: {self.database_name}")
            return
        ClickHouseService().create_database_if_not_exists(self.database_name)

    def create_raw_events_table(self):
        if self.analytics_backend == "adx":
            tbl = self._adx_table_name(self._raw_events_table_name())
            self._get_service().execute(
                f".create-merge table {tbl} "
                f"(event_id: string, user_id: string, event_name: string, "
                f"event_data: dynamic, client_ts: datetime, server_ts: datetime)"
            )
            return tbl
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._raw_events_table_name()} (
            event_id String,
            user_id String,
            event_name String,
            event_data String,
            client_ts DateTime64(3),
            server_ts DateTime64(3)
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(client_ts)
        ORDER BY (event_name, user_id, client_ts)
        """
        ClickHouseService().create_table_if_not_exists(ddl)
        return self._raw_events_table_name()

    def create_event_props_table(self):
        if self.analytics_backend == "adx":
            tbl = self._adx_table_name(self._event_props_table_name())
            self._get_service().execute(
                f".create-merge table {tbl} "
                f"(event_id: string, user_id: string, event_name: string, "
                f"key: string, value: string, client_ts: datetime, server_ts: datetime)"
            )
            return tbl
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._event_props_table_name()} (
            event_id String,
            user_id String,
            event_name String,
            key String,
            value String,
            client_ts DateTime64(3),
            server_ts DateTime64(3)
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(client_ts)
        ORDER BY (event_name, user_id, key, client_ts)
        """
        ClickHouseService().create_table_if_not_exists(ddl)
        return self._event_props_table_name()

    def create_user_profile_table(self):
        if self.analytics_backend == "adx":
            tbl = self._adx_table_name(self._user_profile_props_table_name())
            self._get_service().execute(
                f".create-merge table {tbl} "
                f"(user_id: string, key: string, value: string, server_ts: datetime)"
            )
            return tbl
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._user_profile_props_table_name()} (
            user_id String,
            key String,
            value String,
            server_ts DateTime64(3)
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(server_ts)
        ORDER BY (user_id, key, server_ts)
        """
        try:
            ClickHouseService().create_table_if_not_exists(ddl)
            logger.info(
                f"User profile table created/confirmed: {self._user_profile_props_table_name()}"
            )
        except Exception as e:
            logger.error(f"Failed to create user profile table: {str(e)}")
            raise e

        return self._user_profile_props_table_name()

    def create_user_experience_table(self):
        if self.analytics_backend == "adx":
            tbl = self._adx_table_name(self._user_experience_table_name())
            self._get_service().execute(
                f".create-merge table {tbl} "
                f"(user_id: string, experience_id: string, personalisation_id: string, "
                f"personalisation_name: string, experience_variant_id: string, "
                f"features: dynamic, evaluation_reason: string, assigned_at: datetime)"
            )
            return tbl
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._user_experience_table_name()} (
            user_id String,
            experience_id String,
            personalisation_id String,
            personalisation_name String,
            experience_variant_id String,
            features String,
            evaluation_reason String,
            assigned_at DateTime64(3)
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(assigned_at)
        ORDER BY (user_id, experience_id, assigned_at)
        """
        try:
            ClickHouseService().create_table_if_not_exists(ddl)
        except Exception as e:
            logger.error(f"Failed to create user experience table: {str(e)}")
            raise e

        return self._user_experience_table_name()

    def push_to_analytics(
        self,
        raw_events_rows: list[dict],
        event_props_rows: list[dict],
    ):
        try:
            svc = self._get_service()
            is_adx = self.analytics_backend == "adx"

            if raw_events_rows:
                table = self._adx_table_name(self._raw_events_table_name()) if is_adx else self._raw_events_table_name()
                svc.insert_rows(table, raw_events_rows)

            if event_props_rows:
                table = self._adx_table_name(self._event_props_table_name()) if is_adx else self._event_props_table_name()
                svc.insert_rows(table, event_props_rows)

        except Exception as e:
            logger.error(f"Analytics insertion failed: {str(e)}")
            raise e

    # Keep old name as alias for backwards compatibility with queued jobs
    def push_to_clickhouse(self, raw_events_rows: list[dict], event_props_rows: list[dict]):
        return self.push_to_analytics(raw_events_rows, event_props_rows)

    def track_events(self, user_id: str, events: list[TrackEvent]):
        logger.info(
            f"EventsController.track_events: user_id={user_id}, org={self.organisation_id}, app={self.app_id}, events={events}"
        )
        time_now = datetime.now(timezone.utc)

        raw_events_rows = []
        all_event_props_rows = []

        unique_event_names = list(set([event["event_name"] for event in events]))

        events_schema_objs_map = {}
        events_schema_map = {}
        with db_session() as db:
            events_schema = EventsSchemaCRUD(db).get_events_schema(
                unique_event_names, self.organisation_id, self.app_id
            )

            events_schema_map = {
                schema.event_name: schema.event_schema for schema in events_schema
            }
            events_schema_objs_map = {
                schema.event_name: schema for schema in events_schema
            }

        new_events: list[str] = []
        existing_events: list[str] = []

        for event_name in unique_event_names:
            if event_name not in events_schema_map:
                # With unified tables, no per-event table creation needed
                events_schema_map[event_name] = {}
                new_events.append(event_name)
            else:
                existing_events.append(event_name)

        for event in events:
            event_id = str(uuid.uuid4())
            event_name = event["event_name"]
            event_data = event.get("event_data") or {}
            timestamp = event.get("timestamp") or time_now

            event_schema = events_schema_map[event_name] or {}

            if "properties" not in event_schema:
                event_schema["properties"] = {}

            event_properties = event_schema["properties"] or {}

            raw_events_rows.append(
                {
                    "event_id": event_id,
                    "user_id": str(user_id),
                    "event_name": event_name,
                    "event_data": json.dumps(event_data),
                    "client_ts": timestamp.isoformat(),
                    "server_ts": time_now.isoformat(),
                }
            )

            for key in event_data:
                if key not in event_properties:
                    event_properties[key] = {"type": type(event_data[key]).__name__}

                all_event_props_rows.append(
                    {
                        "event_id": event_id,
                        "user_id": str(user_id),
                        "event_name": event_name,
                        "key": key,
                        "value": str(event_data[key]),
                        "client_ts": timestamp.isoformat(),
                        "server_ts": time_now.isoformat(),
                    }
                )

            event_schema["properties"].update(event_properties)
            events_schema_map[event_name] = event_schema

        self.push_to_clickhouse(raw_events_rows, all_event_props_rows)

        # Update event schemas in PostgreSQL (unchanged)
        with db_session() as db:
            crud = EventsSchemaCRUD(db)

            to_insert = []
            to_update = []

            for event_name in new_events:
                event_schema = events_schema_map[event_name]
                new_schema = EventsSchema(
                    event_name=event_name,
                    organisation_id=self.organisation_id,
                    app_id=self.app_id,
                    event_schema=event_schema,
                )
                to_insert.append(new_schema)

            for event_name in existing_events:
                existing_event_schema_obj = events_schema_objs_map[event_name]
                existing_event_schema_obj.event_schema = events_schema_map[event_name]

                flag_modified(existing_event_schema_obj, "event_schema")
                to_update.append(existing_event_schema_obj)

            crud.bulk_create(to_insert)
            crud.bulk_update(to_update)

    def track_event(
        self,
        user_id: str,
        event_name: str,
        event_data: dict | None = None,
        timestamp: datetime | None = None,
    ):
        if not timestamp:
            timestamp = datetime.now(timezone.utc)

        if not event_data:
            event_data = {}

        return self.track_events(
            user_id,
            [
                {
                    "event_name": event_name,
                    "event_data": event_data,
                    "timestamp": timestamp,
                }
            ],
        )

    def track_user_experience(self, user_experience: UserExperience, external_user_id: str | None = None):
        ch_user_id = external_user_id if external_user_id else str(user_experience.user_id)
        user_experience_row = {
            "user_id": ch_user_id,
            "experience_id": str(user_experience.experience_id),
            "personalisation_id": str(user_experience.personalisation_id) if user_experience.personalisation_id else "",
            "personalisation_name": user_experience.personalisation_name or "default",
            "experience_variant_id": str(user_experience.experience_variant_id) if user_experience.experience_variant_id else "",
            "features": json.dumps(user_experience.features),
            "evaluation_reason": user_experience.evaluation_reason or "",
            "assigned_at": user_experience.assigned_at.isoformat() if user_experience.assigned_at else datetime.now(timezone.utc).isoformat(),
        }

        is_adx = self.analytics_backend == "adx"
        table = self._adx_table_name(self._user_experience_table_name()) if is_adx else self._user_experience_table_name()
        self._get_service().insert_rows(table, [user_experience_row])

    def track_user_profile(self, user_id: str, old_profile: dict, user_profile: dict):
        changed_profile = {
            key: value
            for key, value in user_profile.items()
            if key not in old_profile or old_profile[key] != value
        }

        # Create user profile key entries for new keys in PostgreSQL
        if changed_profile:
            try:
                with db_session() as db:
                    user_profile_keys_crud = UserProfileKeysCRUD(db)

                    user_profile_keys_crud.create_user_profile_keys_if_not_exists(
                        user_profile_data=changed_profile,
                        organisation_id=self.organisation_id,
                        app_id=self.app_id,
                    )

            except Exception as e:
                logger.error(f"Failed to create user profile keys: {e}")

            # Track user profile data to ClickHouse
            user_profile_rows = [
                {
                    "user_id": str(user_id),
                    "key": key,
                    "value": str(changed_profile[key]),
                    "server_ts": datetime.now(timezone.utc).isoformat(),
                }
                for key in changed_profile
            ]

            is_adx = self.analytics_backend == "adx"
            table = self._adx_table_name(self._user_profile_props_table_name()) if is_adx else self._user_profile_props_table_name()
            self._get_service().insert_rows(table, user_profile_rows)

    def create_business_metrics_table(self):
        if self.analytics_backend == "adx":
            tbl = self._adx_table_name(self._business_metrics_table_name())
            try:
                self._get_service().execute(
                    f".create-merge table {tbl} "
                    f"(metric_name: string, dimension: string, value: real, "
                    f"currency: string, scenario_id: string, period_start: datetime, "
                    f"created_at: datetime)"
                )
                logger.info(f"Business metrics table created/confirmed (ADX): {tbl}")
            except Exception as e:
                logger.error(f"Failed to create business metrics table (ADX): {str(e)}")
                raise e
            return tbl
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {self._business_metrics_table_name()} (
            metric_name String,
            dimension String,
            value Float64,
            currency String DEFAULT '',
            scenario_id String DEFAULT 'actuals',
            period_start DateTime64(3),
            created_at DateTime64(3)
        ) ENGINE = ReplacingMergeTree(created_at)
        PARTITION BY toYYYYMM(period_start)
        ORDER BY (metric_name, dimension, period_start, scenario_id)
        """
        try:
            ClickHouseService().create_table_if_not_exists(ddl)
            logger.info(
                f"Business metrics table created/confirmed: {self._business_metrics_table_name()}"
            )
        except Exception as e:
            logger.error(f"Failed to create business metrics table: {str(e)}")
            raise e
        return self._business_metrics_table_name()

    def ingest_business_metrics(self, rows: list[dict], scenario_id: str = "actuals"):
        time_now = datetime.now(timezone.utc)
        ch_rows = []
        for i, row in enumerate(rows):
            try:
                value = float(row["value"])
                if not __import__("math").isfinite(value):
                    raise ValueError(f"value must be finite, got {value}")
                ch_rows.append(
                    {
                        "metric_name": row["metric_name"],
                        "dimension": row.get("dimension", ""),
                        "value": value,
                        "currency": row.get("currency", ""),
                        "scenario_id": row.get("scenario_id", scenario_id),
                        "period_start": row["period_start"],
                        "created_at": time_now.isoformat(),
                    }
                )
            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"Invalid business metric row {i}: {e}")
                raise ValueError(f"Invalid row at index {i}: {e}") from e

        try:
            is_adx = self.analytics_backend == "adx"
            table = self._adx_table_name(self._business_metrics_table_name()) if is_adx else self._business_metrics_table_name()
            self._get_service().insert_rows(table, ch_rows)
        except Exception as e:
            logger.error(f"Analytics insertion failed for business metrics: {e}")
            raise

    @staticmethod
    def _escape_ch_string(value: str) -> str:
        """Escape a value for safe embedding in a ClickHouse string literal."""
        return str(value).replace("\\", "\\\\").replace("'", "\\'")

    def reconcile_user(self, anonymous_id: str, identified_id: str):
        """Re-key anon rows → identified user across all analytics tables."""
        if self.analytics_backend == "adx":
            return self._reconcile_user_adx(anonymous_id, identified_id)
        return self._reconcile_user_clickhouse(anonymous_id, identified_id)

    # Keep old name as alias for backwards compatibility with queued jobs
    def reconcile_user_in_clickhouse(self, anonymous_id: str, identified_id: str):
        return self.reconcile_user(anonymous_id, identified_id)

    def _reconcile_user_clickhouse(self, anonymous_id: str, identified_id: str):
        """Re-key anon rows → identified user in ClickHouse.

        user_id is part of the ORDER BY key in MergeTree tables, so it
        cannot be updated in-place.  Instead we INSERT … SELECT with the
        new user_id and then DELETE the old rows.
        """
        safe_anon = self._escape_ch_string(anonymous_id)
        safe_identified = self._escape_ch_string(identified_id)

        ch = ClickHouseService()
        tables = [
            self._raw_events_table_name(),
            self._event_props_table_name(),
            self._user_profile_props_table_name(),
            self._user_experience_table_name(),
        ]
        completed_tables = []
        for table in tables:
            try:
                insert_stmt = (
                    f"INSERT INTO {table} "
                    f"SELECT * REPLACE('{safe_identified}' AS user_id) "
                    f"FROM {table} WHERE user_id = '{safe_anon}'"
                )
                ch.execute(insert_stmt)

                delete_stmt = (
                    f"ALTER TABLE {table} DELETE "
                    f"WHERE user_id = '{safe_anon}'"
                )
                ch.execute(delete_stmt)
                completed_tables.append(table)
            except Exception as e:
                logger.error(
                    f"reconcile_user_in_clickhouse failed for {table} "
                    f"(completed {len(completed_tables)}/{len(tables)} tables, "
                    f"anon={anonymous_id}, identified={identified_id}): {e}"
                )
                raise

    def _reconcile_user_adx(self, anonymous_id: str, identified_id: str):
        """Re-key anon rows → identified user in ADX.

        ADX does not support in-place updates. We use .delete to soft-delete
        old rows and ingest new rows with the updated user_id.
        """
        safe_anon = self._escape_kql_string(anonymous_id)
        safe_identified = self._escape_kql_string(identified_id)

        svc = self._get_service()
        tables = [
            self._raw_events_table_name(),
            self._event_props_table_name(),
            self._user_profile_props_table_name(),
            self._user_experience_table_name(),
        ]
        completed_tables = []
        for table in tables:
            try:
                # 1. Query existing rows for the anonymous user
                query = f"{table} | where user_id == '{safe_anon}'"
                rows = svc.run_query(query)

                if rows:
                    # 2. Re-insert with identified user_id
                    for row in rows:
                        row["user_id"] = identified_id
                    svc.insert_rows(table, rows)

                    # 3. Soft-delete the old rows
                    svc.execute(
                        f".delete table {table} records <| "
                        f"{table} | where user_id == '{safe_anon}'"
                    )
                completed_tables.append(table)
            except Exception as e:
                logger.error(
                    f"reconcile_user_adx failed for {table} "
                    f"(completed {len(completed_tables)}/{len(tables)} tables, "
                    f"anon={anonymous_id}, identified={identified_id}): {e}"
                )
                raise

    @staticmethod
    def _escape_kql_string(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace("'", "\\'")
