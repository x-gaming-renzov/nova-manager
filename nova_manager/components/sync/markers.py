from nova_manager.components.sync.tables import SYNC_TABLES
from nova_manager.core.log import logger
from nova_manager.service.clickhouse_service import ClickHouseService

# ClickHouse fills these on every insert, so each row carries its true write time and a unique
# id. MATERIALIZED keeps them out of SELECT *, so the copies made by an identity merge
# (INSERT ... SELECT * REPLACE) get fresh values rather than inheriting the old ones.
_MARKER_COLUMNS = {
    "_written_at": "DateTime64(6) MATERIALIZED now64(6)",
    "_row_id": "UUID MATERIALIZED generateUUIDv4()",
}
_MARKER_INDEX_NAME = "idx_written_at"
_MARKER_INDEX = f"{_MARKER_INDEX_NAME} _written_at TYPE minmax GRANULARITY 1"

# Appended to the column list of every analytics CREATE TABLE.
SYNC_MARKER_DDL = ",\n            ".join(
    [f"{name} {definition}" for name, definition in _MARKER_COLUMNS.items()]
    + [f"INDEX {_MARKER_INDEX}"]
)


def _parts_missing(ch: ClickHouseService, database_name: str, table: str, column: str) -> bool:
    counts = ch.run_query(
        """
        SELECT
            (SELECT count() FROM system.parts
              WHERE database = {database:String} AND table = {table:String} AND active) AS parts,
            (SELECT uniqExact(name) FROM system.parts_columns
              WHERE database = {database:String} AND table = {table:String} AND active
                AND column = {column:String}) AS parts_with_markers
        """,
        {"database": database_name, "table": table, "column": column},
    )[0]
    return counts["parts_with_markers"] < counts["parts"]


def ensure_sync_markers(database_name: str) -> None:
    """Add the marker columns to tables created before they existed. Safe to run repeatedly."""
    ch = ClickHouseService()
    existing = {
        row["name"]
        for row in ch.run_query(
            "SELECT name FROM system.tables WHERE database = {database:String}",
            {"database": database_name},
        )
    }
    for table in SYNC_TABLES:
        if table not in existing:
            continue
        full_name = f"{database_name}.{table}"
        add_columns = ", ".join(
            f"ADD COLUMN IF NOT EXISTS {name} {definition}"
            for name, definition in _MARKER_COLUMNS.items()
        )
        ch.execute(f"ALTER TABLE {full_name} {add_columns}")
        ch.execute(f"ALTER TABLE {full_name} ADD INDEX IF NOT EXISTS {_MARKER_INDEX}")
        filled = False
        for column in _MARKER_COLUMNS:
            # Rows written before the column existed get a new value on every read until the
            # value is stored, so wait for the mutation: the export is not safe before it ends.
            if _parts_missing(ch, database_name, table, column):
                logger.info(f"Storing {column} for existing rows of {full_name}")
                ch.execute(
                    f"ALTER TABLE {full_name} MATERIALIZE COLUMN {column} SETTINGS mutations_sync = 2"
                )
                filled = True
        if filled:
            # ADD INDEX only covers parts written afterwards.
            ch.execute(
                f"ALTER TABLE {full_name} MATERIALIZE INDEX {_MARKER_INDEX_NAME} SETTINGS mutations_sync = 2"
            )
