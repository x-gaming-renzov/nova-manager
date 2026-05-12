# Nova Manager API — Response to Overwatch Requests

## Summary

Every endpoint requested in `nova-requests.md` already exists in Nova Manager. No code changes are needed. This document confirms each endpoint, answers all open questions, and notes one minor limitation around pagination.

---

## 1. Service Account — Operational Task Only

No code changes required. This is an account provisioning task:

1. Create a Nova user (email + password) for Overwatch
2. Create an organisation and app for Overwatch's context
3. Generate an SDK API key (`nova_sk_...`) for the same org+app
4. Share credentials + SDK key with the Overwatch team

Overwatch's `NovaClient` will authenticate via `POST /api/v1/auth/login`, cache the JWT, and auto-refresh via `POST /api/v1/auth/refresh`. Both endpoints exist in `nova_manager/api/auth/router.py`.

**Token expiry:** The `TokenResponse` returns `expires_in` in seconds (derived from `ACCESS_TOKEN_EXPIRE_MINUTES * 60`). Overwatch should refresh before this window closes.

---

## 2. Management Endpoints — All 18 Present

Every management endpoint Overwatch requested is implemented and operational.

| # | Method | Path | Status | Router File |
|---|--------|------|--------|-------------|
| 1 | GET | `/api/v1/feature-flags/` | PRESENT | `api/feature_flags/router.py` |
| 2 | GET | `/api/v1/feature-flags/{flag_pid}/` | PRESENT | `api/feature_flags/router.py` |
| 3 | GET | `/api/v1/feature-flags/available/` | PRESENT | `api/feature_flags/router.py` |
| 4 | POST | `/api/v1/feature-flags/sync-nova-objects/` | PRESENT | `api/feature_flags/router.py` |
| 5 | GET | `/api/v1/experiences/` | PRESENT | `api/experiences/router.py` |
| 6 | GET | `/api/v1/experiences/{experience_pid}/` | PRESENT | `api/experiences/router.py` |
| 7 | GET | `/api/v1/experiences/{experience_pid}/features/` | PRESENT | `api/experiences/router.py` |
| 8 | GET | `/api/v1/personalisations/` | PRESENT | `api/personalisations/router.py` |
| 9 | GET | `/api/v1/personalisations/{pid}/` | PRESENT | `api/personalisations/router.py` |
| 10 | GET | `/api/v1/personalisations/personalised-experiences/{experience_id}/` | PRESENT | `api/personalisations/router.py` |
| 11 | POST | `/api/v1/personalisations/create-personalisation/` | PRESENT | `api/personalisations/router.py` |
| 12 | PATCH | `/api/v1/personalisations/{pid}/` | PRESENT | `api/personalisations/router.py` |
| 13 | PATCH | `/api/v1/personalisations/{pid}/disable/` | PRESENT | `api/personalisations/router.py` |
| 14 | PATCH | `/api/v1/personalisations/{pid}/enable/` | PRESENT | `api/personalisations/router.py` |
| 15 | GET | `/api/v1/segments/` | PRESENT | `api/segments/router.py` |
| 16 | GET | `/api/v1/segments/{segment_pid}/` | PRESENT | `api/segments/router.py` |
| 17 | POST | `/api/v1/segments/` | PRESENT | `api/segments/router.py` |
| 18 | PUT | `/api/v1/segments/{segment_pid}/` | PRESENT | `api/segments/router.py` |

### Schema notes

- **Sync nova objects (#4):** Uses SDK key auth (`require_sdk_app_context`), not JWT. This is correct as documented in the request. Overwatch needs both JWT credentials and an SDK key.
- **Personalisation priority:** The `priority` field in `PersonalisationCreate` is optional. If omitted, Nova auto-assigns the next priority value. Lower number = evaluated first.
- **Segment update (#18):** Despite being `PUT`, all fields in `SegmentUpdate` are optional — it behaves as a partial update.
- **Disable personalisation (#13):** This also removes existing user assignments, not just sets `is_active: false`. Overwatch should note this in their admin UI.

---

## 3. SDK Endpoints — All 7 Present

All runtime SDK endpoints requested for the Gamin integration exist. SDK key auth (`require_sdk_app_context`) is confirmed for all of them.

| # | Method | Path | Status | Router File |
|---|--------|------|--------|-------------|
| 1 | POST | `/api/v1/users/create-user/` | PRESENT | `api/users/router.py` |
| 2 | POST | `/api/v1/users/update-user-profile/` | PRESENT | `api/users/router.py` |
| 3 | POST | `/api/v1/users/identify/` | PRESENT | `api/users/router.py` |
| 4 | POST | `/api/v1/user-experience/get-experience/` | PRESENT | `api/user_experience/router.py` |
| 5 | POST | `/api/v1/user-experience/get-experiences/` | PRESENT | `api/user_experience/router.py` |
| 6 | POST | `/api/v1/user-experience/get-all-experiences/` | PRESENT | `api/user_experience/router.py` |
| 7 | POST | `/api/v1/metrics/track-events/` | PRESENT | `api/metrics/router.py` |

### Additional SDK endpoint

- `POST /api/v1/metrics/track-event/` (single event variant) is also present, as noted in the request document.

### SDK auth confirmation

All 7 endpoints use `require_sdk_app_context`, which validates the `nova_sk_...` key via HMAC signature (stateless, no DB lookup). The SDK key Gamin receives will work for all listed endpoints without any configuration changes.

### Identify endpoint notes

The `/identify/` endpoint performs a full anonymous-to-identified user merge:
- Merges user profiles (identified user's profile takes precedence)
- Reassigns experience assignments from anonymous to identified user
- Deletes the anonymous user record from Postgres
- Enqueues a background ClickHouse reconciliation job (`ALTER TABLE ... UPDATE`) to update `user_id` across all event tables

Returns `400` if `anonymous_id == identified_id`.

---

## 4. Open Questions — Answered

### Q1: Service account setup

> Can you create a service account for overwatch and share the credentials + SDK key?

Yes. This is a pure operational task — no code changes. We will:
1. Create a user account for Overwatch
2. Set up the org + app
3. Generate the SDK key
4. Share credentials securely with the Overwatch team

### Q2: Sync behavior — do personalisations/segments take effect immediately?

> After overwatch calls sync-nova-objects, do personalisations/segments created via management API automatically take effect at runtime?

**Yes, immediately.** There is no publish step or sync delay. When Overwatch creates a personalisation or segment via the management API, the next runtime evaluation (`get-experience`, `get-experiences`, `get-all-experiences`) will pick it up. The evaluation code reads directly from the database — there is no cache layer or eventual consistency gap for management writes.

The typical Overwatch flow is:
1. `POST /sync-nova-objects/` — creates feature flags + experiences
2. `POST /create-personalisation/` — creates targeting rules with variants
3. Done — Gamin's next `get-experience` call for any affected user will evaluate against the new personalisation

### Q3: Pagination — max limit and total count

> Is there a max limit value? Do responses include a total count for pagination UIs?

**Max limit:** `1000`. All list endpoints enforce `ge=1, le=1000` on the `limit` parameter. Default is `100`.

**Total count:** List endpoints return bare `List[...]` responses — there is **no `total` count** field in the response. This means Overwatch cannot display "Page 1 of N" style pagination.

**Workaround:** Use offset-based "load more" pagination. If `len(results) == limit`, there are likely more results — fetch the next page with `skip += limit`. If `len(results) < limit`, you've reached the end.

This is a known limitation. If Overwatch needs a total count for their admin UI, we can add a count query to list endpoints — but it's not blocking for the initial integration.

### Q4: User profile keys endpoint

> Which endpoint path returns the list of user profile attribute keys?

**`GET /api/v1/metrics/user-profile-keys/`**

Located in `nova_manager/api/metrics/router.py`. Accepts an optional `search` query parameter for filtering.

Returns `List[UserProfileKeyResponse]`:
```json
[
  {
    "pid": "uuid",
    "key": "country",
    "type": "string",
    "description": "User's country code"
  }
]
```

Overwatch can call this endpoint to populate the rule builder dropdown with available profile attribute names, types, and descriptions. The `search` parameter supports filtering by key name.

---

## 5. Auth Endpoints — Present

| Method | Path | Status | Purpose |
|--------|------|--------|---------|
| POST | `/api/v1/auth/login` | PRESENT | Get JWT access + refresh tokens |
| POST | `/api/v1/auth/refresh` | PRESENT | Refresh expired access token |
| GET | `/api/v1/auth/me` | PRESENT | Get current authenticated user info |
| GET | `/api/v1/auth/sdk-credentials` | PRESENT | Get SDK API key for current app |

**Note:** `/auth/sdk-credentials` could be useful for Overwatch to programmatically retrieve the SDK key after login, rather than having it pre-configured.

---

## 6. What's Not Needed

Based on the request document, **no new endpoints, schemas, or auth mechanisms need to be built**. The entire integration can proceed with the existing API surface.

The only action item is the operational task of creating the service account (Q1).
