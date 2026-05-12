# Ghost Variants / Evaluation Order Shadowing — Bug Investigation

**Status:** Reproduced at unit level, not yet fixed  
**Severity:** High — active personalisations become unreachable to users  
**Related:** LIVEOPS_NOTICE_ISSUE.md (Issues 2 & 3), NOVA_ISSUE_PRIORITY_SHADOWING.md

## The Bug

When multiple personalisations exist on the same experience, only the newest one is ever evaluated. Older personalisations become "ghosts" — active in the DB, visible in admin, but invisible to users.

## Root Cause — Three Design Choices That Conflict

### 1. Personalisations load in priority DESC order

```python
# nova_manager/components/experiences/models.py:58
order_by="Personalisations.priority.desc()"
```

Highest priority number evaluates first.

### 2. New personalisations get auto-incremented priority

```python
# nova_manager/api/personalisations/router.py:184-194
# When no client priority provided:
next_priority = max_priority_personalisation.priority + 1
```

So newest = highest priority = evaluates first.

### 3. Evaluation is first-match-wins with `break`

```python
# nova_manager/flows/get_user_experience_variant_flow_async.py:142-294
for personalisation in personalisations:  # already DESC sorted
    # ... rule checks ...
    if not self.rule_evaluator.evaluate_rule(rule_config, evaluation_context):
        continue
    # MATCH — build assignment and:
    break  # line 294 — stop evaluating, first match wins
```

Combined: newest personalisation that matches always wins. Older ones are never reached.

## Reproduction Scenario

```
Timeline:
  T1: Create Personalisation A (auto-priority=1)
      rule: {conditions: [{field: "is_participant", operator: "equals", value: true}]}
      
  T2: Create Personalisation B (auto-priority=2)
      rule: {conditions: []}  ← empty = matches everyone

Evaluation order (DESC): [B(p=2), A(p=1)]
  1. B evaluated first — empty conditions → TRUE → break
  2. A is never reached → GHOST
```

This is confirmed by the passing tests in `tests/test_bug_replication.py`:
- `TestIssues2And3_EvaluationOrderShadowing::test_broad_rule_at_higher_priority_shadows_narrow_rule`
- `TestIssues2And3_EvaluationOrderShadowing::test_even_participant_user_gets_cms_not_notice`
- `TestIssues2And3_EvaluationOrderShadowing::test_multiple_notices_same_tournament_only_one_survives`

## Real-World Impact

### Issue 2 (CMS ghost variants)
CMS deployments create personalisations with empty conditions (match everyone). If a CMS deployment is created after a targeted personalisation on the same experience, the CMS deployment shadows it.

### Issue 3 (Ghost notices)
Multiple notices published for the same tournament each become a personalisation on `tournament_notice_<pid>`. Each gets auto-incrementing priority. Only the last-published notice is reachable — earlier ones are ghosts.

## What PR #11 Fixed (Partial)

PR #11 fixed the **priority input** side: clients can now supply their own priority value instead of always getting auto-increment. This lets callers control evaluation order. But the fundamental evaluation model (first-match-wins on DESC-sorted list) is unchanged.

## What Still Needs Fixing

The core question: **what should happen when multiple personalisations match?**

Options to evaluate:

1. **Flip to ASC** — lowest priority evaluates first. Combined with auto-increment, newest would be evaluated *last* (fallback). This reverses who shadows whom but doesn't eliminate shadowing.

2. **Most-specific-match-wins** — score personalisations by rule specificity (number of conditions, narrowness). More complex to implement but semantically correct.

3. **Separate concerns** — notices and CMS deployments shouldn't be personalisations on the same experience if they need independent evaluation. This is an architecture question.

4. **Allow multi-match** — return all matching personalisations, not just first. Breaking API change (`UserExperienceAssignment` is single-winner today).

## Key Code Locations

| What | File | Line |
|------|------|------|
| Priority DESC ordering | `nova_manager/components/experiences/models.py` | 58 |
| Auto-increment priority | `nova_manager/api/personalisations/router.py` | 184-194 |
| First-match-wins loop | `nova_manager/flows/get_user_experience_variant_flow_async.py` | 142-294 |
| `break` on match | `nova_manager/flows/get_user_experience_variant_flow_async.py` | 294 |
| Single-winner schema | `nova_manager/components/user_experience/schemas.py` | `UserExperienceAssignment` |
| Priority unique constraint | `nova_manager/components/personalisations/models.py` | 55-59 |
| Bug replication tests | `tests/test_bug_replication.py` | `TestIssues2And3_EvaluationOrderShadowing` |

## Reproduction Tests Already Exist

All in `tests/test_bug_replication.py` — these tests PASS (proving the bug exists). When the bug is fixed, they should be updated to assert the correct behavior.
