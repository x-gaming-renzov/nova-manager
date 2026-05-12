from abc import ABC, abstractmethod


class AnalyticsService(ABC):
    """Abstract interface for analytics backends (ClickHouse, ADX, etc.)."""

    @abstractmethod
    def insert_rows(self, table_name: str, rows: list[dict]):
        """Insert rows into a table."""
        ...

    @abstractmethod
    def run_query(self, query: str) -> list[dict]:
        """Execute a query and return results as list[dict]."""
        ...

    @abstractmethod
    def execute(self, statement: str):
        """Execute a DDL or management command."""
        ...
