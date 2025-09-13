from datetime import datetime, timezone
import json
from typing import TypedDict
from uuid import UUID
import uuid
from sqlalchemy.orm.attributes import flag_modified

from nova_manager.database.session import db_session
from nova_manager.core.log import logger
from nova_manager.service.bigquery import BigQueryService

from nova_manager.components.metrics.artefacts import EventsArtefacts
from nova_manager.components.metrics.crud import EventsSchemaCRUD, UserProfileKeysCRUD
from nova_manager.components.user_experience.models import UserExperience
from nova_manager.components.metrics.models import EventsSchema
from nova_manager.components.users.models import Users
from nova_manager.core.config import GCP_PROJECT_ID


class TrackEvent(TypedDict):
    event_name: str
    event_data: dict | None = None
    timestamp: datetime | None = None


class EventsController(EventsArtefacts):
    def create_dataset(self):
        dataset_id = f"{GCP_PROJECT_ID}.{self.dataset_name}"
        BigQueryService().create_dataset_if_not_exists(dataset_id)

    def create_raw_events_table(self):
        raw_events_table_name = f"{GCP_PROJECT_ID}.{self._raw_events_table_name()}"

        try:
            BigQueryService().create_table_if_not_exists(
                raw_events_table_name,
                schema=[
                    {"name": "event_id", "type": "STRING"},
                    {"name": "user_id", "type": "STRING"},
                    {"name": "client_ts", "type": "TIMESTAMP"},
                    {"name": "server_ts", "type": "TIMESTAMP"},
                    {"name": "event_name", "type": "STRING"},
                    {"name": "event_data", "type": "STRING"},
                ],
                partition_field="client_ts",
                clustering_fields=["event_name", "user_id"],
            )
        except Exception as e:
            logger.error(f"Failed to create raw events table: {str(e)}")
            raise e

        return raw_events_table_name

    def create_event_table(self, event_name: str):
        event_table_name = f"{GCP_PROJECT_ID}.{self._event_table_name(event_name)}"

        # Create event table if not exists
        event_table_schema = [
            {"name": "event_id", "type": "STRING"},
            {"name": "user_id", "type": "STRING"},
            {"name": "event_name", "type": "STRING"},
            {"name": "client_ts", "type": "TIMESTAMP"},
            {"name": "server_ts", "type": "TIMESTAMP"},
        ]

        BigQueryService().create_table_if_not_exists(
            event_table_name,
            event_table_schema,
            partition_field="client_ts",
            clustering_fields=["event_name", "user_id"],
        )

        return event_table_name

    def create_event_props_table(self, event_name: str):
        event_props_table_name = (
            f"{GCP_PROJECT_ID}.{self._event_props_table_name(event_name)}"
        )

        # Create event props table if not exists
        event_props_table_schema = [
            {"name": "event_id", "type": "STRING"},
            {"name": "user_id", "type": "STRING"},
            {"name": "event_name", "type": "STRING"},
            {"name": "key", "type": "STRING"},
            {"name": "value", "type": "STRING"},
            {"name": "client_ts", "type": "TIMESTAMP"},
            {"name": "server_ts", "type": "TIMESTAMP"},
        ]

        BigQueryService().create_table_if_not_exists(
            event_props_table_name,
            event_props_table_schema,
            partition_field="client_ts",
            clustering_fields=["event_name", "user_id"],
        )

        return event_props_table_name

    def create_user_profile_table(self):
        user_profile_table_name = (
            f"{GCP_PROJECT_ID}.{self._user_profile_props_table_name()}"
        )

        logger.info(f"Creating user profile table: {user_profile_table_name}")

        user_profile_table_schema = [
            {"name": "user_id", "type": "STRING"},
            {"name": "key", "type": "STRING"},
            {"name": "value", "type": "STRING"},
            {"name": "server_ts", "type": "TIMESTAMP"},
        ]

        try:
            BigQueryService().create_table_if_not_exists(
                user_profile_table_name,
                user_profile_table_schema,
                partition_field="server_ts",
                clustering_fields=["user_id", "key"],
            )
            logger.info(
                f"User profile table created/confirmed: {user_profile_table_name}"
            )
        except Exception as e:
            logger.error(f"Failed to create user profile table: {str(e)}")
            raise e

        return user_profile_table_name

    def create_user_experience_table(self):
        user_experience_table_name = (
            f"{GCP_PROJECT_ID}.{self._user_experience_table_name()}"
        )

        try:
            BigQueryService().create_table_if_not_exists(
                user_experience_table_name,
                schema=[
                    {"name": "user_id", "type": "STRING"},
                    {"name": "experience_id", "type": "STRING"},
                    {"name": "personalisation_id", "type": "STRING"},
                    {"name": "personalisation_name", "type": "STRING"},
                    {"name": "experience_variant_id", "type": "STRING"},
                    {"name": "features", "type": "STRING"},
                    {"name": "evaluation_reason", "type": "STRING"},
                    {"name": "assigned_at", "type": "TIMESTAMP"},
                ],
                partition_field="assigned_at",
                clustering_fields=["user_id", "experience_id", "personalisation_id"],
            )
        except Exception as e:
            logger.error(f"Failed to create user experience table: {str(e)}")
            raise e

        return user_experience_table_name

    def push_to_bigquery(
        self,
        raw_events_rows: list[dict],
        event_table_rows: dict,
        event_props_table_rows: dict,
    ):
        try:
            raw_events_table_name = self._raw_events_table_name()
            errors = BigQueryService().insert_rows(
                raw_events_table_name, raw_events_rows
            )

            if errors:
                raise Exception(str(errors))

            for event_name, row in event_table_rows.items():
                event_table_name = self._event_table_name(event_name)

                errors = BigQueryService().insert_rows(event_table_name, [row])
                if errors:
                    raise Exception(str(errors))

            for event_name, rows in event_props_table_rows.items():
                event_props_table_name = self._event_props_table_name(event_name)

                errors = BigQueryService().insert_rows(event_props_table_name, rows)
                if errors:
                    raise Exception(str(errors))

        except Exception as e:
            logger.error(f"BigQuery insertion failed: {str(e)}")
            raise e

    def track_events(self, user_id: UUID, events: list[TrackEvent]):
        logger.info(
            f"EventsController.track_events: user_id={user_id}, org={self.organisation_id}, app={self.app_id}, events={events}"
        )
        time_now = datetime.now(timezone.utc)

        raw_events_rows = []
        event_table_rows = {}
        event_props_table_rows = {}

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
                logger.info(f"Creating BigQuery tables for new event: {event_name}")
                self.create_event_table(event_name)
                self.create_event_props_table(event_name)
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
                    "client_ts": timestamp.isoformat(),
                    "server_ts": time_now.isoformat(),
                    "event_name": event_name,
                    "event_data": json.dumps(event_data),
                }
            )

            event_table_rows[event_name] = {
                "event_id": event_id,
                "user_id": str(user_id),
                "event_name": event_name,
                "client_ts": timestamp.isoformat(),
                "server_ts": time_now.isoformat(),
            }

            event_props_table_rows[event_name] = []

            for key in event_data:
                if key not in event_properties:
                    event_properties[key] = {"type": type(event_data[key]).__name__}

                event_props_table_rows[event_name].append(
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

        self.push_to_bigquery(raw_events_rows, event_table_rows, event_props_table_rows)

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
        user_id: UUID,
        event_name: str,
        event_data: dict | None = None,
        timestamp: datetime | None = None,
    ):
        if not timestamp:
            timestamp = datetime.now()

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

    def track_user_experience(self, user_experience: UserExperience):
        # TODO: Remove creation of table here
        user_experience_table_name = self.create_user_experience_table()

        user_experience_row = {
            "user_id": str(user_experience.user_id),
            "experience_id": str(user_experience.experience_id),
            "personalisation_id": str(user_experience.personalisation_id),
            "personalisation_name": user_experience.personalisation_name,
            "experience_variant_id": str(user_experience.experience_variant_id),
            "features": json.dumps(user_experience.features),
            "evaluation_reason": user_experience.evaluation_reason,
            "assigned_at": user_experience.assigned_at.isoformat(),
        }

        BigQueryService().insert_rows(user_experience_table_name, [user_experience_row])

    def track_user_profile(self, user_id: UUID, old_profile: dict, user_profile: dict):
        # TODO: Remove creation of table here
        user_profile_table_name = self.create_user_profile_table()

        changed_profile = {
            key: value
            for key, value in user_profile.items()
            if key not in old_profile or old_profile[key] != value
        }

        # Create user profile key entries for new keys
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

            # Track user profile data to BigQuery
            user_profile_rows = [
                {
                    "user_id": str(user_id),
                    "key": key,
                    "value": str(changed_profile[key]),  # Convert all values to strings
                    "server_ts": datetime.now(timezone.utc).isoformat(),
                }
                for key in changed_profile
            ]

            BigQueryService().insert_rows(user_profile_table_name, user_profile_rows)
