import os
import threading

import clickhouse_connect
from clickhouse_connect.driver import Client

from nova_manager.core.config import (
    CLICKHOUSE_HOST,
    CLICKHOUSE_PORT,
    CLICKHOUSE_USER,
    CLICKHOUSE_PASSWORD,
)
from nova_manager.core.log import logger


def _get_client() -> Client:
    """Return a ClickHouse client. Uses connection pooling from clickhouse-connect."""
    return clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
    )


_local = threading.local()

# Each insert used to DESCRIBE its table first; schemas only change on deploy.
_column_types: dict[tuple[str, tuple[str, ...]], list] = {}

# Workers insert a handful of rows per job, and every insert became a part to merge.
# The server buffers them into larger parts; waiting keeps a failed insert raising here.
ASYNC_INSERT_SETTINGS = {"async_insert": 1, "wait_for_async_insert": 1}


def _shared_client() -> Client:
    """One client per thread, rebuilt after a fork.

    A client holds a session, which refuses concurrent queries, so API threads can't share
    one; a forked child must not reuse the parent's sockets.
    """
    if getattr(_local, "pid", None) != os.getpid():
        _local.client = _get_client()
        _local.pid = os.getpid()
    return _local.client


class ClickHouseService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = _shared_client()
        return self._client

    def insert_rows(self, table_name: str, rows: list[dict]):
        """Insert rows into a ClickHouse table.

        table_name: 'database.table' format (e.g., 'org_X_app_Y.raw_events')
        rows: list of dicts with column names as keys
        """
        if not rows:
            return []

        columns = list(rows[0].keys())
        data = [[row[col] for col in columns] for row in rows]
        types_key = (table_name, tuple(columns))

        try:
            if types_key not in _column_types:
                context = self.client.create_insert_context(table=table_name, column_names=columns)
                _column_types[types_key] = context.column_types
            self.client.insert(
                table=table_name,
                data=data,
                column_names=columns,
                column_types=_column_types[types_key],
                settings=ASYNC_INSERT_SETTINGS,
            )
        except Exception as e:
            # A changed schema shows up as a failed insert; look the types up again next time.
            _column_types.pop(types_key, None)
            logger.error(f"ClickHouse insert failed for {table_name}: {str(e)}")
            raise e

        return []  # Empty list = success (matches BigQuery interface)

    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        """Execute a query and return results as list[dict].

        parameters: values for server-side placeholders written as {name:Type} in the query.
        """
        try:
            result = self.client.query(query, parameters=parameters)

            if not result.result_rows:
                return []

            column_names = result.column_names
            return [
                dict(zip(column_names, row)) for row in result.result_rows
            ]
        except Exception as e:
            logger.error(f"ClickHouse query failed: {str(e)}")
            raise e

    def execute(self, statement: str):
        """Execute a DDL or non-query statement (CREATE TABLE, CREATE DATABASE, etc.)."""
        self.client.command(statement)

    def create_database_if_not_exists(self, database_name: str):
        """Create a ClickHouse database (replaces BigQuery dataset)."""
        try:
            self.execute(f"CREATE DATABASE IF NOT EXISTS `{database_name}`")
            logger.info(f"Database ensured: {database_name}")
        except Exception as e:
            logger.error(f"Error creating database {database_name}: {str(e)}")
            raise e

    def create_table_if_not_exists(self, create_table_sql: str):
        """Execute a CREATE TABLE IF NOT EXISTS statement.

        Takes the full DDL SQL string because ClickHouse table creation
        includes ENGINE, PARTITION BY, ORDER BY which don't fit a simple
        schema-dict interface.
        """
        try:
            self.execute(create_table_sql)
        except Exception as e:
            logger.error(f"Error creating table: {str(e)}")
            raise e
