# Agent Handoff Document

**Date:** 2026-04-28  
**Last agent action:** Merged PR #11 (cherry-pick-main-fixes → staging)

---

## What is Nova Manager?

A FastAPI backend for managing feature flags, personalisations, and A/B experiments. Users are assigned experience variants based on personalisation rules (targeting conditions, rollout percentages, segments). Analytics events are tracked in ClickHouse, with Postgres as the primary relational store.

Key flows:
- **Personalisation evaluation:** `nova_manager/flows/get_user_experience_variant_flow_async.py` — iterates personalisations in priority DESC order, first-match-wins with `break`
- **Rule evaluation:** `nova_manager/components/rule_evaluator/controller.py` — evaluates targeting conditions against user payload/profile
- **Analytics:** `nova_manager/components/metrics/` — event tracking + query building for ClickHouse

---

## What Was Just Merged (PR #11)

Cherry-picked 6 commits (3 PRs) from `main` into `staging`. Six bug fixes:

### 1. Rule evaluator None crash (P0)
- **File:** `nova_manager/components/rule_evaluator/controller.py:227-244`
- **Was:** `None > 18` raised TypeError; `str(None).startswith("No")` returned True
- **Fix:** All comparison/string operators guard with `actual_value is not None`, return False for missing fields
- **Tests:** `tests/test_bug_fixes.py::TestRuleEvaluatorNoneHandling` (14 tests)

### 2. Assignment cache logic inverted (P0)
- **File:** `nova_manager/flows/get_user_experience_variant_flow_async.py:153-155`
- **Was:** `assigned_at < last_updated_at and not reassign` — only cached when stale+no-reassign, meaning fresh cache entries were always re-evaluated. Used `continue` which let post-loop code overwrite cached result.
- **Fix:** `assigned_at >= last_updated_at or not reassign` with `break` — caches when fresh OR reassign disabled
- **Tests:** `tests/test_bug_fixes.py::TestAssignmentCacheLogic` (6 tests)

### 3. Timezone mismatch
- **File:** `nova_manager/components/metrics/events_controller.py:240`
- **Was:** `datetime.now()` (naive) vs `track_events()` using `datetime.now(timezone.utc)`
- **Fix:** Both now use `datetime.now(timezone.utc)`
- **Tests:** `tests/test_bug_fixes.py::TestTrackEventTimezone`

### 4. Debug print leaking invite tokens
- **File:** `nova_manager/api/auth/request_response.py`
- **Was:** `print(f"Company: {info}, Invite token: {info.data.get('invite_token')}")`
- **Fix:** Removed
- **Tests:** `tests/test_bug_fixes.py::TestNoDebugPrint`

### 5. Client-supplied priority ignored
- **File:** `nova_manager/api/personalisations/router.py:182-212`
- **Was:** Always auto-incremented priority (max+1), ignoring `personalisation_data.priority`
- **Fix:** Honors client priority when provided, falls back to auto-increment. Catches `IntegrityError` for duplicate priority.
- **Tests:** `tests/test_bug_replication.py::TestPriorityShadowing_ClientPriorityIgnored`

### 6. Retention query ClickHouse incompatibility
- **File:** `nova_manager/components/metrics/query_builder.py:355-367`
- **Was:** Non-equi conditions (`>`, `<`) in `LEFT JOIN ON` — ClickHouse v24.8 rejects with `INVALID_JOIN_ON_EXPRESSION`. Also used `IS NOT NULL` (broken on non-Nullable columns), `SAFE_DIVIDE`, `TIMESTAMP_ADD` (BigQuery-only).
- **Fix:** Moved time-window filtering into `IF()` aggregation, equi-join only, ClickHouse-compatible division/interval arithmetic
- **Confirmed live:** Old query crashes on ClickHouse v24.8, fixed query returns correct results
- **Tests:** `tests/test_retention_query.py` (14 tests)

---

## Known Unfixed Bug: Ghost Variants / Evaluation Order Shadowing

**Full investigation:** `GHOST_VARIANTS_INVESTIGATION.md`  
**Replication tests:** `tests/test_bug_replication.py::TestIssues2And3_EvaluationOrderShadowing` (all pass, proving the bug exists)  
**Related issues:** `LIVEOPS_NOTICE_ISSUE.md` (Issues 2 & 3), `NOVA_ISSUE_PRIORITY_SHADOWING.md`

### The problem

When multiple personalisations exist on the same experience, only the newest is ever evaluated. Older ones are "ghosts" — active in DB but unreachable.

### Why it happens

Three design choices conflict:
1. Personalisations load in **priority DESC** order (`models.py:58`)
2. New personalisations get **auto-incremented priority** (always highest)
3. Evaluation is **first-match-wins** with `break` (`flow_async.py:294`)

Newest → highest priority → evaluates first → if it matches (e.g. empty conditions), older ones never reached.

### What PR #11 helped with

The priority fix (#5 above) lets callers supply explicit priority, so they can control evaluation order. But the fundamental first-match-wins model is unchanged.

### What needs to happen next

1. **Reproduce against a running instance** — the unit-level replication tests exist, but need to confirm via the API with real DB state
2. **Decide on fix approach** — see `GHOST_VARIANTS_INVESTIGATION.md` for four options (flip to ASC, most-specific-wins, separate concerns, multi-match)
3. **Fix and verify** — update `test_bug_replication.py` tests to assert correct behavior once fixed

### Key files for the ghost variants fix

| What | File | Line |
|------|------|------|
| Priority DESC ordering | `nova_manager/components/experiences/models.py` | 58 |
| Auto-increment priority | `nova_manager/api/personalisations/router.py` | 184-194 |
| First-match-wins loop | `nova_manager/flows/get_user_experience_variant_flow_async.py` | 142-294 |
| Single-winner schema | `nova_manager/components/user_experience/schemas.py` | `UserExperienceAssignment` |
| Priority unique constraint | `nova_manager/components/personalisations/models.py` | 55-59 |

---

## Infrastructure

- **Postgres:** Primary relational DB (models use SQLAlchemy + Alembic migrations)
- **ClickHouse v24.8:** Analytics event storage + queries (`docker-compose.yml`)
- **Redis + RQ:** Background job queue
- **Python 3.13**, FastAPI, venv at `.venv/`
- **Tests:** `pytest` via `.venv/bin/python -m pytest`

## Branches

- `main` — has all fixes
- `staging` — now up to date with main's fixes (PR #11 merged)
- `cherry-pick-main-fixes` — the PR branch, can be deleted
