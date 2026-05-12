# Nova Manager — Personalisation Priority Is Silently Ignored on Create

## TL;DR

`POST /api/v1/personalisations/create-personalisation/` ignores the `priority` field sent by the client and always assigns `max_priority_in_experience + 1`. Combined with the `priority DESC + first-match-wins` evaluator, this means **the most recently created personalisation always shadows older ones on the same experience** whenever its rule matches — regardless of what priority the client tried to set.

This breaks any use case where an integration wants to express "this narrow-rule personalisation must beat an existing broad-rule one on the same experience."

---

## Reproducer (real use case hitting us)

We have two consumers writing personalisations into Nova:

1. **LiveOps notices** — create a personalisation on experience `tournament_notice_{tournament_pid}`:
   - `rule_config.conditions: [{field: "is_participant", operator: "equals", value: true}]`
   - `rollout_percentage: 100`
   - Client sends `priority: 1` intending "high priority / must win."

2. **CMS deployments** — create a personalisation on the same experience (via a separate admin flow):
   - `rule_config`: empty conditions (matches everyone)
   - `rollout_percentage: 100`
   - Client sends `priority: 1` as well.

### Observed behaviour

| Step | Result |
|---|---|
| Publish LiveOps notice only | Participants see the notice on mobile. ✅ |
| Publish CMS deployment only | CMS content renders on mobile. ✅ |
| Publish notice, **then** publish CMS deployment | Participants **stop seeing the notice**. No error. ❌ |

### Why it happens (from Nova's own code)

**1. `priority` from the client is discarded.**
`nova_manager/api/personalisations/router.py` — create endpoint:

```python
max_priority_personalisation = (
    personalisations_crud.get_experience_max_priority_personalisation(
        experience_id=experience_id
    )
)
if max_priority_personalisation:
    next_priority = max_priority_personalisation.priority + 1
else:
    next_priority = 1

personalisation = personalisations_crud.create_personalisation(
    experience_id=experience_id,
    ...
    priority=next_priority,     # <-- client's priority is never read
    rule_config=personalisation_data.rule_config,
    rollout_percentage=personalisation_data.rollout_percentage,
)
```

Result: notice gets `priority=1`, CMS (second write) gets `priority=2`. The client has no way to override this.

**2. Evaluation is priority-DESC, first-match-wins.**
`nova_manager/components/experiences/models.py`:

```python
personalisations: Mapped[list[Personalisations]] = relationship(
    ...
    order_by="Personalisations.priority.desc()",
    ...
)
```

`nova_manager/flows/get_user_experience_variant_flow_async.py`:

```python
for personalisation in personalisations:
    if not personalisation.is_active: continue
    if not evaluate_target_percentage(...): continue
    if personalisation.segment_rules and not any_segment_matches(...): continue
    if not evaluate_rule(rule_config, evaluation_context): continue
    # pick variant
    break   # <-- first match wins
```

**3. End-to-end:** participant user → Nova iterates `priority DESC` → CMS (p=2) evaluated first → empty rule matches everyone → `break` → notice (p=1) is never reached.

The notice row is still `is_active=True` in the DB. It is simply unreachable.

---

## Why this is a Nova-side bug and not just a consumer problem

- The `priority` field is in the public request schema, so clients reasonably expect it to do something.
- There is no validation error, no 400 response, no warning log — the field is silently dropped.
- This makes it **impossible** for any integration to express ordering intent, even when they fully understand Nova's evaluation semantics. The only way to "win" right now is to always be the last writer, which is not a stable property.
- `sync_nova_objects` and `create_personalisation` are otherwise non-destructive (good), so Nova's data model is fine — only the `priority` handling is broken.

---

## Requested fix

Option A (preferred) — **honor client-supplied `priority`** in `nova_manager/api/personalisations/router.py`:

```python
if personalisation_data.priority is not None:
    next_priority = personalisation_data.priority
else:
    next_priority = (
        max_priority_personalisation.priority + 1
        if max_priority_personalisation
        else 1
    )
```

This should be paired with either:
- dropping the `UniqueConstraint(experience_id, priority)` on `Personalisations`, OR
- returning a clear 409/400 if a client tries to claim an already-used priority on that experience.

Option B — **reject the field** if Nova does not want to support client-controlled priority: remove `priority` from the request schema, so clients fail loudly instead of silently being overridden. Less useful, but at least not misleading.

Option C — **document the current behaviour prominently** (newest-wins, client priority ignored) and add an explicit `evaluation_order` or `is_override` flag so integrations can express "this one must evaluate first."

---

## Files referenced (branch `chore/cleanup-experiences-script`)

- `nova_manager/api/personalisations/router.py` — create endpoint, priority override logic
- `nova_manager/api/personalisations/request_response.py` — request schema with `priority`
- `nova_manager/components/personalisations/crud.py` — DB insert, additive only
- `nova_manager/components/personalisations/models.py` — `UniqueConstraint(experience_id, priority)`
- `nova_manager/components/experiences/models.py` — `order_by="Personalisations.priority.desc()"`
- `nova_manager/flows/get_user_experience_variant_flow_async.py` — evaluator loop with `break`

---