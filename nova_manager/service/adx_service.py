from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.ingest import QueuedIngestClient, IngestionProperties
from azure.kusto.ingest.ingestion_properties import DataFormat

import io
import json

from nova_manager.core.config import ADX_CLUSTER_URI, ADX_DATABASE
from nova_manager.core.log import logger
from nova_manager.service.analytics_service import AnalyticsService


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

        try:
            # Convert rows to newline-delimited JSON for ingestion
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

    def run_query(self, query: str) -> list[dict]:
        try:
            result = self.query_client.execute_query(self._database, query)

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
            self.query_client.execute_mgmt(self._database, statement)
        except Exception as e:
            logger.error(f"ADX management command failed: {e}")
            raise
