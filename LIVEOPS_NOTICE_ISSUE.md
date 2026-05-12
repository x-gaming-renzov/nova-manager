# LiveOps + CMS — Bug Report

## Summary

Three bugs identified across the Nova integration layer (Overwatch backend). One is blocking notice delivery in production (P0). The other two are silent bugs that currently mask themselves behind Nova's tiebreak logic and will cause unpredictable behaviour as usage grows (P1).

| # | Issue | Affects | Priority |
|---|---|---|---|
| 1 | Notice payload rule gate | Notices only | P0 — production block |
| 2 | Ghost variants on CMS deploys | CMS | P1 — silent bug |
| 3 | Ghost notices on multi-publish | LiveOps Notices | P1 — silent bug |

All three live in **Overwatch backend**. No frontend or Nova changes required.

---

## Issue 1 (P0) — Notices Not Showing in App

### What is happening
Admin publishes a notice, it reaches Nova, but it never renders in the mobile app for any user. App logs show every `tournament_notice_*` experience returns `no_experience_assignment_error`.

### Root cause
**File:** `overwatch/api/admin/liveops/notices.py`, lines 181–186

Overwatch hardcodes a targeting rule when creating a notice's personalisation in Nova:

```python
"rule_config": {
    "conditions": [
        {"field": "is_participant", "operator": "equals", "value": True}
    ],
    "operator": "AND",
}
```

This tells Nova to only assign the notice to users who send `is_participant: true` in their evaluation payload. The mobile app does not send this flag consistently — the Nova SDK's startup batch call does not forward per-call payloads — so the rule never matches and Nova returns an empty assignment.

### Proof (direct Nova API test)

With payload:
```bash
curl -X POST https://api.nova.xgaming.club/api/v1/user-experience/get-experience/ \
  -H "Authorization: Bearer <NOVA_API_KEY>" \
  -d '{"user_id":"...","experience_name":"tournament_notice_...","payload":{"is_participant":true}}'
# -> evaluation_reason: "personalisation_reassignment", full notice content returned
```

Without payload:
```bash
# Same call, no payload field
# -> evaluation_reason: "no_experience_assignment_error", empty content
```

The difference is solely the payload gate. Nova and the notice data itself are correct.

### Fix
**Where:** `overwatch/api/admin/liveops/notices.py`, lines 181–186
**What:** Set `rule_config.conditions` to an empty array.

```python
"rule_config": {
    "conditions": [],
    "operator": "AND",
},
```

### Why backend (not frontend)
- CMS already uses empty `rule_config.conditions` and works. Matching its pattern is the lowest-risk fix.
- The mobile app already filters notices by tournament — `useNotice.ts` only requests experiences for the user's live tournaments. Server-side `is_participant` adds no real access control.
- Admin UI exposes no targeting controls, so the rule is dead code no one can configure.
- Client-side payload is not trustable as an authorization gate (any client can send `true`). Fixing this on the frontend is effort without security benefit.

---

## Issue 2 (P1) — CMS: Ghost Variants on Multiple Deploys

### What is happening
Every time a variant is deployed on the same CMS experience, Overwatch creates a **new** Nova personalisation. Old personalisations are never auto-disabled or deleted. All share the same hardcoded `priority: 1`. Nova returns exactly one personalisation per experience per user — the tiebreak winner — and silently drops the rest.

### Root cause
**File:** `overwatch/api/admin/cms/deployments.py`

- Line 83: `"priority": 1` is hardcoded on every deploy
- Lines 248–292: `set_variant()` handler creates a new personalisation; no existing-deployment check, no auto-disable

### Impact
- Team deploys v1 → it becomes active.
- Team deploys v2 → both v1 and v2 are live on Nova; Nova picks one by its internal tiebreak (likely creation order or pid).
- Team thinks v2 is live; in reality some or all users may still be served v1.
- Admin UI lists both as "active" — no indication of which one users actually see.

### Fix (pick one)
**Option A (recommended):** On new deploy, automatically disable previous active personalisations for the same experience before creating the new one.
**Option B:** Use incrementing priority — newest deploy gets highest priority so Nova always picks it.

---

## Issue 3 (P1) — LiveOps Notices: Ghost Notices on Multi-Publish

### What is happening
Same underlying problem as Issue 2, but for notices. Each tournament maps to a single Nova experience (`tournament_notice_<tournamentPid>`). When admin publishes multiple notices for the same tournament, each becomes a separate personalisation on that one experience, all at priority 1.

### Root cause
**File:** `overwatch/api/admin/liveops/notices.py`

- Line 180: `"priority": 1` hardcoded on every publish
- Lines 71–72: Experience name is keyed by tournament, not by notice — so multiple notices collide on one experience

### Impact
- Admin dashboard shows "Notices (2)" — team expects both visible.
- App receives only one notice per tournament from Nova.
- Other notices are permanently invisible to users, even though admin sees them as active.
- Multi-tournament example: user registered in 2 tournaments with 2 notices each (4 total) → user sees 2, not 4.

### Fix (pick one — team decision needed)
**Option A:** Change architecture so each notice is its own experience: `tournament_notice_<tournamentPid>_<noticePid>`. App's `useNotice.ts` would need updating to load all notice experiences for a tournament.
**Option B:** On new publish, auto-disable previous active notices for the same tournament — enforce a "one active notice per tournament" model and update the admin UI accordingly.
**Option C:** Store all notices as an array inside a single variant's config — one personalisation, many notice objects.

---

## Working Correctly (not bugs)

- Nova SaaS — evaluates rules and returns assignments correctly.
- Overwatch HTTP endpoints — POST/PUT return 200 with accurate state.
- Admin UI — publish/disable/enable flows are wired correctly.
- Mobile app `useNotice.ts` — loads correct experience names per user's live tournaments.
- Mobile app `NoticeCarousel` — renders one notice per tournament as the current architecture allows.

---

## Action Items

1. **P0 — Issue 1:** Remove the `is_participant` condition in `overwatch/api/admin/liveops/notices.py:181–186`. Deploy. Verify with the curl above (no payload) that notices return real assignments.
2. **P1 — Issue 2:** Decide between auto-disable-previous vs. incrementing-priority for CMS deploys, then patch `overwatch/api/admin/cms/deployments.py`.
3. **P1 — Issue 3:** Team decision on multi-notice model (separate experiences / one active / array config). Depending on choice, update `overwatch/api/admin/liveops/notices.py` and possibly `src/hooks/useNotice.ts` on the mobile app.
