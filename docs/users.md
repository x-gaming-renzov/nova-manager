### Users API (/api/v1/users)

Manage Nova user records synchronized with your external user IDs. All endpoints require SDK API-key authentication — `organisation_id` and `app_id` are inferred from the API key.

#### POST /api/v1/users/create-user/

Create user if not exists, otherwise updates profile.

Request

```json
{
	"user_id": "external-user-123",
	"user_profile": { "country": "US", "ltv": 1200 }
}
```

Response

```json
{ "nova_user_id": "<uuid>" }
```

#### POST /api/v1/users/update-user-profile/

Update a user profile (or create if not exists).

Request

```json
{
	"user_id": "external-user-123",
	"user_profile": { "country": "US", "ltv": 1300 }
}
```

Response: same as create-user.

---

#### POST /api/v1/users/identify/

Reconcile an anonymous user into an identified user. Use this when a user transitions from anonymous to identified (e.g. after login or signup).

When to use:

- A visitor browses your app before signing up. They are tracked under an anonymous ID (e.g. a device fingerprint or session token). Once they log in or register, call this endpoint to merge their anonymous history into their real account.
- Supports multiple anonymous sessions being merged into the same identified user over time (e.g. user visits on different devices before logging in on each).
- Safe to call even if the anonymous user has no records in Postgres — ClickHouse event data will still be reconciled.

What it does:

1. Creates the identified user if it doesn't already exist.
2. If the anonymous user exists in Postgres:
   - Merges user profiles with precedence: anonymous profile < identified profile < request `user_profile`.
   - Reassigns all experience assignments from the anonymous user to the identified user.
   - Deletes the anonymous user record.
3. Enqueues a background job to update `user_id` across all ClickHouse event tables (regardless of whether the anonymous user existed in Postgres).
4. If a merge happened, enqueues a profile sync to ClickHouse.

Request

```json
{
	"anonymous_id": "anon_abc123",
	"identified_id": "user_42",
	"user_profile": { "preferred_language": "en" }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `anonymous_id` | string | yes | External ID of the anonymous user to reconcile from. |
| `identified_id` | string | yes | External ID of the identified user to reconcile to. Created if it doesn't exist. |
| `user_profile` | object \| null | no | Optional profile to merge on top. Has the highest precedence in the merge. |

Response (merged)

```json
{
	"nova_user_id": "<uuid>",
	"merged": true
}
```

Response (anonymous user not found in Postgres)

```json
{
	"nova_user_id": "<uuid>",
	"merged": false
}
```

| Field | Type | Description |
|---|---|---|
| `nova_user_id` | uuid | Internal UUID of the identified user (the surviving record). |
| `merged` | boolean | `true` if an anonymous user was found and merged. `false` if only ClickHouse reconciliation was enqueued. |

Errors

| Status | Condition |
|---|---|
| 400 | `anonymous_id` and `identified_id` are the same value. |

Notes

- Profile merge is a shallow dict merge: `{**anon_profile, **identified_profile, **request_profile}`. Keys in higher-precedence profiles overwrite lower ones.
- Experience reassignment is a bulk UPDATE — all `UserExperience` rows pointing to the anonymous user's internal ID are re-pointed to the identified user.
- The ClickHouse reconciliation runs asynchronously via a background queue. It updates `user_id` in four tables: `raw_events`, `event_props`, `user_profile_props`, and `user_experience`.
- Calling identify a second time with the same pair (after the anonymous user was already merged) returns `merged: false` — the operation is idempotent.
