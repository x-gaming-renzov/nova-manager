from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data.client_request_properties import ClientRequestProperties
from azure.kusto.ingest import QueuedIngestClient, IngestionProperties
from azure.kusto.ingest.ingestion_properties import DataFormat

import io
import json
from datetime import timedelta

from nova_manager.core.config import ADX_CLUSTER_URI, ADX_DATABASE, ADX_INGEST_MODE
from nova_manager.core.log import logger
from nova_manager.service.analytics_service import AnalyticsService

# Cap how long Nova will wait for ADX to respond. Without this, the Kusto
# SDK can block indefinitely on a half-closed socket and starve FastAPI's
# threadpool, taking the whole API down.
_KUSTO_QUERY_TIMEOUT = timedelta(seconds=30)
_KUSTO_MGMT_TIMEOUT = timedelta(minutes=1)  # mgmt commands (table create, .ingest inline) can be slower


def _query_props() -> ClientRequestProperties:
    props = ClientRequestProperties()
    props.set_option(ClientRequestProperties.request_timeout_option_name, _KUSTO_QUERY_TIMEOUT)
    return props


def _mgmt_props() -> ClientRequestProperties:
    props = ClientRequestProperties()
    props.set_option(ClientRequestProperties.request_timeout_option_name, _KUSTO_MGMT_TIMEOUT)
    return props


class ADXService(AnalyticsService):
    def __init__(self, database: str | None = None):
        self._query_client = None
        self._ingest_client = None
        self._database = database or ADX_DATABASE

    @property
    def query_client(self) -> KustoClient:
        if self._query_client is None:
            credential = DefaultAzureCredential()
            kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
                ADX_CLUSTER_URI, credential
            )
            self._query_client = KustoClient(kcsb)
        return self._query_client

    @property
    def ingest_client(self) -> QueuedIngestClient:
        if self._ingest_client is None:
            credential = DefaultAzureCredential()
            kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
                f"{ADX_CLUSTER_URI.rstrip('/')}", credential
            )
            self._ingest_client = QueuedIngestClient(kcsb)
        return self._ingest_client

    def insert_rows(self, table_name: str, rows: list[dict]):
        if not rows:
            return []

        if ADX_INGEST_MODE == "inline":
            self._insert_rows_inline(table_name, rows)
            return []

        try:
            json_lines = "\n".join(json.dumps(row) for row in rows)
            stream = io.StringIO(json_lines)

            ingestion_props = IngestionProperties(
                database=self._database,
                table=table_name,
                data_format=DataFormat.MULTIJSON,
            )

            self.ingest_client.ingest_from_stream(stream, ingestion_properties=ingestion_props)
        except Exception as e:
            logger.error(f"ADX ingestion failed for {table_name}: {e}")
            raise

        return []

    def _insert_rows_inline(self, table_name: str, rows: list[dict]):
        # Synchronous mgmt-plane ingest: rows are queryable as soon as this returns.
        # Intended for tests (set ADX_INGEST_MODE=inline). Subject to a per-command
        # payload cap; callers in tests stay well under it.
        json_lines = "\n".join(json.dumps(row) for row in rows)
        command = (
            f".ingest inline into table {table_name} "
            f"with (format='multijson') <|\n{json_lines}"
        )
        try:
            self.query_client.execute_mgmt(self._database, command, _mgmt_props())
        except Exception as e:
            logger.error(f"ADX inline ingestion failed for {table_name}: {e}")
            raise

    def run_query(self, query: str) -> list[dict]:
        try:
            result = self.query_client.execute_query(self._database, query, _query_props())

            if not result.primary_results or not result.primary_results[0]:
                return []

            primary = result.primary_results[0]
            columns = [c.column_name for c in primary.columns]

            return [
                {col: row[col] for col in columns}
                for row in primary
            ]
        except Exception as e:
            logger.error(f"ADX query failed: {e}")
            raise

    def execute(self, statement: str):
        try:
            self.query_client.execute_mgmt(self._database, statement, _mgmt_props())
        except Exception as e:
            logger.error(f"ADX management command failed: {e}")
            raise
