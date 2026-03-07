import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, CheckConstraint, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nova_manager.core.models import Base
from nova_manager.core.security import SDKAuthContext
from nova_manager.database.async_session import get_async_db
from nova_manager.components.auth.dependencies import require_sdk_app_context
from nova_manager.api.users.router import router as users_router

TEST_ORG_ID = str(uuid.uuid4())
TEST_APP_ID = str(uuid.uuid4())


@pytest.fixture(scope="session")
def _patch_for_sqlite():
    """Patch metadata for SQLite compatibility:
    - Remove func.json('{}') server_defaults (SQLite doesn't have json())
    - Remove CHECK constraints with subqueries (SQLite prohibits them)
    """
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSON) and col.server_default is not None:
                col.server_default = None

        # Remove CHECK constraints with subqueries
        table.constraints = {
            c for c in table.constraints
            if not (
                isinstance(c, CheckConstraint)
                and c.sqltext is not None
                and "SELECT" in str(c.sqltext).upper()
            )
        }


@pytest_asyncio.fixture
async def async_engine(_patch_for_sqlite):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # Enable FK support for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def async_db_session(async_engine):
    session_factory = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_client(async_db_session):
    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1/users")

    async def _override_db():
        yield async_db_session

    def _override_auth():
        return SDKAuthContext(organisation_id=TEST_ORG_ID, app_id=TEST_APP_ID)

    app.dependency_overrides[get_async_db] = _override_db
    app.dependency_overrides[require_sdk_app_context] = _override_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_queue():
    with patch("nova_manager.api.users.router.QueueController") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance
