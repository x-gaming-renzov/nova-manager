import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from nova_manager.components.users.crud_async import UsersAsyncCRUD
from nova_manager.components.users.models import Users
from nova_manager.components.user_experience.models import UserExperience
from nova_manager.components.experiences.models import Experiences
from nova_manager.components.metrics.events_controller import EventsController

from tests.conftest import TEST_ORG_ID, TEST_APP_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_user(db, user_id, profile=None):
    crud = UsersAsyncCRUD(db)
    return await crud.create_user(
        user_id=user_id,
        organisation_id=TEST_ORG_ID,
        app_id=TEST_APP_ID,
        user_profile=profile or {},
    )


async def _create_experience(db):
    """Create an Experiences row so FK constraints are satisfied."""
    exp = Experiences(
        name=f"exp-{uuid.uuid4().hex[:8]}",
        description="test",
        status="active",
        organisation_id=TEST_ORG_ID,
        app_id=TEST_APP_ID,
    )
    db.add(exp)
    await db.commit()
    await db.refresh(exp)
    return exp


async def _create_experience_row(db, user_pid, experience_id=None):
    """Insert a UserExperience row directly."""
    if experience_id is None:
        exp = await _create_experience(db)
        experience_id = exp.pid

    ue = UserExperience(
        user_id=user_pid,
        experience_id=experience_id,
        personalisation_id=None,
        personalisation_name="test",
        experience_variant_id=None,
        features={},
        assigned_at=datetime.now(timezone.utc),
        evaluation_reason="test",
        organisation_id=TEST_ORG_ID,
        app_id=TEST_APP_ID,
    )
    db.add(ue)
    await db.commit()
    await db.refresh(ue)
    return ue


# ===========================================================================
# A. Endpoint Code Paths
# ===========================================================================

@pytest.mark.asyncio
class TestEndpointCodePaths:

    async def test_identify_same_id_returns_400(self, test_client, mock_queue):
        resp = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "same", "identified_id": "same"},
        )
        assert resp.status_code == 400

    async def test_identify_anon_exists_identified_exists(
        self, test_client, async_db_session, mock_queue
    ):
        anon = await _create_user(async_db_session, "anon-1", {"a": 1})
        identified = await _create_user(async_db_session, "id-1", {"b": 2})

        resp = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-1", "identified_id": "id-1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] is True
        assert body["nova_user_id"] == str(identified.pid)

        # Anon should be deleted
        crud = UsersAsyncCRUD(async_db_session)
        assert await crud.get_by_user_id("anon-1", TEST_ORG_ID, TEST_APP_ID) is None
        # Identified should still exist
        assert await crud.get_by_user_id("id-1", TEST_ORG_ID, TEST_APP_ID) is not None

    async def test_identify_anon_exists_identified_not_exists(
        self, test_client, async_db_session, mock_queue
    ):
        await _create_user(async_db_session, "anon-2", {"x": 10})

        resp = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-2", "identified_id": "id-2"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] is True

        crud = UsersAsyncCRUD(async_db_session)
        assert await crud.get_by_user_id("anon-2", TEST_ORG_ID, TEST_APP_ID) is None
        id_user = await crud.get_by_user_id("id-2", TEST_ORG_ID, TEST_APP_ID)
        assert id_user is not None

    async def test_identify_anon_not_in_pg_identified_exists(
        self, test_client, async_db_session, mock_queue
    ):
        identified = await _create_user(async_db_session, "id-3")

        resp = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "ghost-anon", "identified_id": "id-3"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] is False
        assert body["nova_user_id"] == str(identified.pid)

    async def test_identify_anon_not_in_pg_identified_not_exists(
        self, test_client, async_db_session, mock_queue
    ):
        resp = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "ghost-anon-2", "identified_id": "id-4"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["merged"] is False

        crud = UsersAsyncCRUD(async_db_session)
        assert await crud.get_by_user_id("id-4", TEST_ORG_ID, TEST_APP_ID) is not None

    async def test_identify_response_shape(self, test_client, async_db_session, mock_queue):
        resp = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-shape", "identified_id": "id-shape"},
        )
        body = resp.json()
        assert "nova_user_id" in body
        assert "merged" in body
        # nova_user_id should be a valid UUID
        uuid.UUID(body["nova_user_id"])
        assert isinstance(body["merged"], bool)


# ===========================================================================
# B. Profile Merge Tests
# ===========================================================================

@pytest.mark.asyncio
class TestProfileMerge:

    async def test_profile_merge_precedence(self, test_client, async_db_session, mock_queue):
        await _create_user(async_db_session, "anon-pm1", {"a": 1, "b": 2})
        await _create_user(async_db_session, "id-pm1", {"b": 3, "c": 4})

        await test_client.post(
            "/api/v1/users/identify/",
            json={
                "anonymous_id": "anon-pm1",
                "identified_id": "id-pm1",
                "user_profile": {"c": 5, "d": 6},
            },
        )

        crud = UsersAsyncCRUD(async_db_session)
        user = await crud.get_by_user_id("id-pm1", TEST_ORG_ID, TEST_APP_ID)
        assert user.user_profile == {"a": 1, "b": 3, "c": 5, "d": 6}

    async def test_profile_merge_anon_only(self, test_client, async_db_session, mock_queue):
        await _create_user(async_db_session, "anon-pm2", {"a": 1})

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-pm2", "identified_id": "id-pm2"},
        )

        crud = UsersAsyncCRUD(async_db_session)
        user = await crud.get_by_user_id("id-pm2", TEST_ORG_ID, TEST_APP_ID)
        assert user.user_profile == {"a": 1}

    async def test_profile_merge_request_overrides_all(
        self, test_client, async_db_session, mock_queue
    ):
        await _create_user(async_db_session, "anon-pm3", {"x": 1})
        await _create_user(async_db_session, "id-pm3", {"x": 2})

        await test_client.post(
            "/api/v1/users/identify/",
            json={
                "anonymous_id": "anon-pm3",
                "identified_id": "id-pm3",
                "user_profile": {"x": 3},
            },
        )

        crud = UsersAsyncCRUD(async_db_session)
        user = await crud.get_by_user_id("id-pm3", TEST_ORG_ID, TEST_APP_ID)
        assert user.user_profile == {"x": 3}

    async def test_profile_merge_empty_profiles(
        self, test_client, async_db_session, mock_queue
    ):
        await _create_user(async_db_session, "anon-pm4", {})
        await _create_user(async_db_session, "id-pm4", {})

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-pm4", "identified_id": "id-pm4"},
        )

        crud = UsersAsyncCRUD(async_db_session)
        user = await crud.get_by_user_id("id-pm4", TEST_ORG_ID, TEST_APP_ID)
        assert user.user_profile == {}

    async def test_profile_merge_no_request_profile(
        self, test_client, async_db_session, mock_queue
    ):
        await _create_user(async_db_session, "anon-pm5", {"a": 1})
        await _create_user(async_db_session, "id-pm5", {"b": 2})

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-pm5", "identified_id": "id-pm5"},
        )

        crud = UsersAsyncCRUD(async_db_session)
        user = await crud.get_by_user_id("id-pm5", TEST_ORG_ID, TEST_APP_ID)
        assert user.user_profile == {"a": 1, "b": 2}


# ===========================================================================
# C. Experience Reassignment Tests
# ===========================================================================

@pytest.mark.asyncio
class TestExperienceReassignment:

    async def test_reassign_anon_experiences_to_identified(
        self, test_client, async_db_session, mock_queue
    ):
        anon = await _create_user(async_db_session, "anon-exp1")
        identified = await _create_user(async_db_session, "id-exp1")

        for _ in range(3):
            await _create_experience_row(async_db_session, anon.pid)

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-exp1", "identified_id": "id-exp1"},
        )

        result = await async_db_session.execute(
            select(UserExperience).where(UserExperience.user_id == identified.pid)
        )
        assert len(result.scalars().all()) == 3

    async def test_reassign_both_have_experiences(
        self, test_client, async_db_session, mock_queue
    ):
        anon = await _create_user(async_db_session, "anon-exp2")
        identified = await _create_user(async_db_session, "id-exp2")

        for _ in range(2):
            await _create_experience_row(async_db_session, anon.pid)
        await _create_experience_row(async_db_session, identified.pid)

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-exp2", "identified_id": "id-exp2"},
        )

        result = await async_db_session.execute(
            select(UserExperience).where(UserExperience.user_id == identified.pid)
        )
        assert len(result.scalars().all()) == 3

    async def test_reassign_overlapping_experiences(
        self, test_client, async_db_session, mock_queue
    ):
        anon = await _create_user(async_db_session, "anon-exp3")
        identified = await _create_user(async_db_session, "id-exp3")

        shared_exp = await _create_experience(async_db_session)
        await _create_experience_row(async_db_session, anon.pid, experience_id=shared_exp.pid)
        await _create_experience_row(async_db_session, identified.pid, experience_id=shared_exp.pid)

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-exp3", "identified_id": "id-exp3"},
        )

        result = await async_db_session.execute(
            select(UserExperience).where(UserExperience.user_id == identified.pid)
        )
        assert len(result.scalars().all()) == 2

    async def test_reassign_no_experiences(
        self, test_client, async_db_session, mock_queue
    ):
        await _create_user(async_db_session, "anon-exp4")
        identified = await _create_user(async_db_session, "id-exp4")

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-exp4", "identified_id": "id-exp4"},
        )

        result = await async_db_session.execute(
            select(UserExperience).where(UserExperience.user_id == identified.pid)
        )
        assert len(result.scalars().all()) == 0

    async def test_cascade_delete_does_not_remove_reassigned_rows(
        self, test_client, async_db_session, mock_queue
    ):
        anon = await _create_user(async_db_session, "anon-exp5")
        identified = await _create_user(async_db_session, "id-exp5")

        for _ in range(2):
            await _create_experience_row(async_db_session, anon.pid)

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-exp5", "identified_id": "id-exp5"},
        )

        # Anon is gone
        crud = UsersAsyncCRUD(async_db_session)
        assert await crud.get_by_user_id("anon-exp5", TEST_ORG_ID, TEST_APP_ID) is None

        # Rows still exist under identified
        result = await async_db_session.execute(
            select(UserExperience).where(UserExperience.user_id == identified.pid)
        )
        assert len(result.scalars().all()) == 2


# ===========================================================================
# D. ClickHouse Job Enqueueing Tests
# ===========================================================================

@pytest.mark.asyncio
class TestClickHouseJobEnqueue:

    async def test_clickhouse_reconcile_job_enqueued(
        self, test_client, async_db_session, mock_queue
    ):
        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-ch1", "identified_id": "id-ch1"},
        )

        calls = mock_queue.add_task.call_args_list
        reconcile_calls = [
            c for c in calls
            if len(c.args) >= 1 and hasattr(c.args[0], "__name__")
            and c.args[0].__name__ == "reconcile_user_in_clickhouse"
        ]
        assert len(reconcile_calls) >= 1
        call = reconcile_calls[0]
        assert call.args[1] == "anon-ch1"
        assert call.args[2] == "id-ch1"

    async def test_clickhouse_profile_sync_enqueued(
        self, test_client, async_db_session, mock_queue
    ):
        await _create_user(async_db_session, "anon-ch2", {"key": "val"})

        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-ch2", "identified_id": "id-ch2"},
        )

        calls = mock_queue.add_task.call_args_list
        profile_calls = [
            c for c in calls
            if len(c.args) >= 1 and hasattr(c.args[0], "__name__")
            and c.args[0].__name__ == "track_user_profile"
        ]
        assert len(profile_calls) >= 1

    async def test_clickhouse_jobs_enqueued_even_without_pg_anon(
        self, test_client, async_db_session, mock_queue
    ):
        await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "no-pg-anon", "identified_id": "id-ch3"},
        )

        calls = mock_queue.add_task.call_args_list
        reconcile_calls = [
            c for c in calls
            if len(c.args) >= 1 and hasattr(c.args[0], "__name__")
            and c.args[0].__name__ == "reconcile_user_in_clickhouse"
        ]
        assert len(reconcile_calls) >= 1


# ===========================================================================
# E. Repeat / Multi-Session Identify Tests
# ===========================================================================

@pytest.mark.asyncio
class TestRepeatIdentify:

    async def test_identify_multiple_anons_to_same_user(
        self, test_client, async_db_session, mock_queue
    ):
        await _create_user(async_db_session, "anon-r1", {"a": 1})
        await _create_user(async_db_session, "anon-r2", {"b": 2})

        resp1 = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-r1", "identified_id": "id-r1"},
        )
        assert resp1.status_code == 200
        assert resp1.json()["merged"] is True

        resp2 = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-r2", "identified_id": "id-r1"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["merged"] is True

        crud = UsersAsyncCRUD(async_db_session)
        user = await crud.get_by_user_id("id-r1", TEST_ORG_ID, TEST_APP_ID)
        # Both anon profiles merged in
        assert user.user_profile.get("a") == 1
        assert user.user_profile.get("b") == 2

    async def test_identify_idempotent_after_anon_deleted(
        self, test_client, async_db_session, mock_queue
    ):
        await _create_user(async_db_session, "anon-idem", {"z": 9})

        resp1 = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-idem", "identified_id": "id-idem"},
        )
        assert resp1.json()["merged"] is True

        mock_queue.add_task.reset_mock()

        resp2 = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-idem", "identified_id": "id-idem"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["merged"] is False

        # CH reconcile still enqueued
        reconcile_calls = [
            c for c in mock_queue.add_task.call_args_list
            if len(c.args) >= 1 and hasattr(c.args[0], "__name__")
            and c.args[0].__name__ == "reconcile_user_in_clickhouse"
        ]
        assert len(reconcile_calls) >= 1


# ===========================================================================
# F. CRUD Unit Tests
# ===========================================================================

@pytest.mark.asyncio
class TestCRUDMethods:

    async def test_crud_reassign_user_experiences_returns_count(
        self, async_db_session
    ):
        anon = await _create_user(async_db_session, "anon-crud1")
        target = await _create_user(async_db_session, "id-crud1")

        for _ in range(3):
            await _create_experience_row(async_db_session, anon.pid)

        crud = UsersAsyncCRUD(async_db_session)
        count = await crud.reassign_user_experiences(anon.pid, target.pid)
        assert count == 3

    async def test_crud_reassign_zero_rows(self, async_db_session):
        anon = await _create_user(async_db_session, "anon-crud2")
        target = await _create_user(async_db_session, "id-crud2")

        crud = UsersAsyncCRUD(async_db_session)
        count = await crud.reassign_user_experiences(anon.pid, target.pid)
        assert count == 0

    async def test_crud_delete_user(self, async_db_session):
        user = await _create_user(async_db_session, "del-user")
        crud = UsersAsyncCRUD(async_db_session)

        await crud.delete_user(user)
        await async_db_session.commit()

        assert await crud.get_by_user_id("del-user", TEST_ORG_ID, TEST_APP_ID) is None

    async def test_crud_merge_user_profiles(self, async_db_session):
        target = await _create_user(async_db_session, "merge-target", {"b": 2})
        crud = UsersAsyncCRUD(async_db_session)

        await crud.merge_user_profiles(target, {"a": 1}, {"c": 3})
        await async_db_session.commit()
        await async_db_session.refresh(target)

        assert target.user_profile == {"a": 1, "b": 2, "c": 3}


# ===========================================================================
# G. EventsController Unit Test
# ===========================================================================

@pytest.mark.asyncio
class TestEventsControllerReconcile:

    async def test_reconcile_user_in_clickhouse_calls_execute(self):
        with patch(
            "nova_manager.components.metrics.events_controller.ClickHouseService"
        ) as MockCH:
            mock_ch = MagicMock()
            MockCH.return_value = mock_ch

            controller = EventsController(TEST_ORG_ID, TEST_APP_ID)
            controller.reconcile_user_in_clickhouse("anon-xyz", "id-xyz")

            # 4 tables × 2 calls each (INSERT … SELECT + ALTER TABLE DELETE)
            assert mock_ch.execute.call_count == 8

            calls = [c.args[0] for c in mock_ch.execute.call_args_list]
            insert_calls = [c for c in calls if c.startswith("INSERT")]
            delete_calls = [c for c in calls if c.startswith("ALTER TABLE")]
            assert len(insert_calls) == 4
            assert len(delete_calls) == 4
            for stmt in insert_calls:
                assert "anon-xyz" in stmt
                assert "id-xyz" in stmt
            for stmt in delete_calls:
                assert "anon-xyz" in stmt
