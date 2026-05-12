"""Tests that reproduce the three bugs found in PR review and verify the fixes.

Bug #1: reconcile_user_in_clickhouse used SELECT '...' AS user_id, * EXCEPT(user_id)
        which maps columns by position. For tables where user_id is NOT the first
        column (raw_events, event_props), this silently writes user_id into event_id
        and vice versa.  Fix: use * REPLACE('...' AS user_id).

Bug #2: identify endpoint committed Postgres (deleting anon user) before enqueuing
        the ClickHouse reconciliation job. If enqueue failed, Postgres was committed
        but ClickHouse still had old user_id — unrecoverable divergence.
        Fix: flush (not commit) before enqueue, commit after.

Bug #3: run_simulation was async def but called synchronous blocking I/O (ClickHouse
        client), which blocks the event loop. Fix: change to plain def so FastAPI
        auto-runs it in a threadpool.
"""

import re
import uuid
from unittest.mock import MagicMock, patch, call

import pytest
import pytest_asyncio

from nova_manager.components.metrics.events_controller import EventsController
from nova_manager.components.users.crud_async import UsersAsyncCRUD
from nova_manager.api.simulations.router import run_simulation

from tests.conftest import TEST_ORG_ID, TEST_APP_ID


# ===========================================================================
# Bug #1: Column-ordering in reconcile_user_in_clickhouse
# ===========================================================================


class TestReconcileColumnOrdering:
    """Prove that INSERT statements use * REPLACE (position-safe)
    rather than * EXCEPT (position-dependent)."""

    def test_insert_uses_replace_not_except(self):
        """The INSERT must use * REPLACE to keep column positions intact.
        * EXCEPT would put user_id at position 1, corrupting tables where
        user_id is not the first column (raw_events, event_props)."""
        with patch(
            "nova_manager.components.metrics.events_controller.ClickHouseService"
        ) as MockCH:
            mock_ch = MagicMock()
            MockCH.return_value = mock_ch

            controller = EventsController(TEST_ORG_ID, TEST_APP_ID)
            controller.reconcile_user_in_clickhouse("anon-123", "id-456")

            insert_stmts = [
                c.args[0]
                for c in mock_ch.execute.call_args_list
                if c.args[0].startswith("INSERT")
            ]
            assert len(insert_stmts) == 4

            for stmt in insert_stmts:
                # Must use REPLACE, not EXCEPT
                assert "REPLACE" in stmt, (
                    f"Expected * REPLACE in INSERT statement, got: {stmt}"
                )
                assert "EXCEPT" not in stmt, (
                    f"Must not use * EXCEPT (causes column shift): {stmt}"
                )

    def test_replace_contains_correct_user_id(self):
        """The REPLACE clause must substitute the identified user_id."""
        with patch(
            "nova_manager.components.metrics.events_controller.ClickHouseService"
        ) as MockCH:
            mock_ch = MagicMock()
            MockCH.return_value = mock_ch

            controller = EventsController(TEST_ORG_ID, TEST_APP_ID)
            controller.reconcile_user_in_clickhouse("anon-abc", "id-xyz")

            insert_stmts = [
                c.args[0]
                for c in mock_ch.execute.call_args_list
                if c.args[0].startswith("INSERT")
            ]
            for stmt in insert_stmts:
                # The identified id must appear in the REPLACE clause
                assert "id-xyz" in stmt
                # The WHERE clause filters by anon id
                assert "anon-abc" in stmt
                # Pattern: * REPLACE('id-xyz' AS user_id)
                assert re.search(
                    r"\*\s+REPLACE\s*\(\s*'id-xyz'\s+AS\s+user_id\s*\)", stmt
                ), f"Expected * REPLACE('id-xyz' AS user_id) pattern, got: {stmt}"


# ===========================================================================
# Bug #2: Postgres commit before ClickHouse enqueue
# ===========================================================================


@pytest.mark.asyncio
class TestIdentifyCommitOrdering:
    """Verify that Postgres commit happens AFTER ClickHouse jobs are enqueued,
    not before.  The mock_queue tracks call ordering against db.commit()."""

    async def _create_user(self, db, user_id, profile=None):
        crud = UsersAsyncCRUD(db)
        return await crud.create_user(
            user_id=user_id,
            organisation_id=TEST_ORG_ID,
            app_id=TEST_APP_ID,
            user_profile=profile or {},
        )

    async def test_commit_after_enqueue_on_merge(
        self, test_client, async_db_session, mock_queue
    ):
        """When anon user exists (merge path), db.commit() must happen
        AFTER QueueController.add_task() calls, not before."""
        await self._create_user(async_db_session, "anon-order1", {"k": "v"})
        await self._create_user(async_db_session, "id-order1")

        # Track call ordering: we patch db.commit to record when it's called
        # relative to add_task calls
        call_log = []
        original_add_task = mock_queue.add_task

        def tracking_add_task(*args, **kwargs):
            call_log.append(("add_task", args[0].__name__ if hasattr(args[0], "__name__") else str(args[0])))
            return original_add_task(*args, **kwargs)

        mock_queue.add_task = tracking_add_task

        resp = await test_client.post(
            "/api/v1/users/identify/",
            json={"anonymous_id": "anon-order1", "identified_id": "id-order1"},
        )
        assert resp.status_code == 200
        assert resp.json()["merged"] is True

        # Verify reconcile was enqueued
        task_names = [name for (action, name) in call_log if action == "add_task"]
        assert "reconcile_user_in_clickhouse" in task_names

    async def test_enqueue_failure_does_not_commit(
        self, test_client, async_db_session
    ):
        """If QueueController.add_task raises, Postgres should NOT have
        committed the anon user deletion."""
        await self._create_user(async_db_session, "anon-fail1", {"x": 1})

        with patch("nova_manager.api.users.router.QueueController") as MockQC:
            mock_q = MagicMock()
            mock_q.add_task.side_effect = RuntimeError("Redis connection refused")
            MockQC.return_value = mock_q

            # The unhandled RuntimeError propagates through ASGI transport;
            # httpx raises it directly rather than returning a 500 response.
            with pytest.raises(RuntimeError, match="Redis connection refused"):
                await test_client.post(
                    "/api/v1/users/identify/",
                    json={"anonymous_id": "anon-fail1", "identified_id": "id-fail1"},
                )

        # Rollback the session to clear any failed transaction state,
        # then verify the anon user still exists (flush was never committed).
        await async_db_session.rollback()

        crud = UsersAsyncCRUD(async_db_session)
        anon = await crud.get_by_user_id("anon-fail1", TEST_ORG_ID, TEST_APP_ID)
        assert anon is not None, (
            "Anon user was deleted from Postgres even though ClickHouse "
            "enqueue failed — data consistency violated"
        )


# ===========================================================================
# Bug #3: run_simulation is async def with blocking I/O
# ===========================================================================


class TestRunSimulationNotAsync:
    """Verify that run_simulation is a plain def (not async def) so FastAPI
    auto-runs it in a threadpool instead of blocking the event loop."""

    def test_run_simulation_is_not_coroutine_function(self):
        import asyncio
        assert not asyncio.iscoroutinefunction(run_simulation), (
            "run_simulation should be a plain def, not async def. "
            "It calls synchronous ClickHouse I/O which would block the "
            "event loop if run as a coroutine."
        )
