# Nova Manager API Requests

## Context

Overwatch is the internal super-admin dashboard for the platform. It needs to integrate with Nova Manager for two purposes:

1. **Management API** — Overwatch admins manage feature flags, experiences, personalisations, and segments through overwatch's UI. Overwatch calls Nova's management endpoints server-to-server.
2. **Runtime SDK** — Gamin (the game/tournament backend) evaluates feature flags and tracks user events at runtime via Nova's SDK endpoints. This is a separate integration owned by the gamin team.

This document covers what overwatch needs from Nova to wire both integrations in. Request/response schemas are taken from the Nova codebase (`nova-manager`). Where we're unsure of the right endpoint, we describe what we need and ask for guidance.

---

## 1. Service Account for Overwatch

Nova's management endpoints use JWT Bearer tokens (HS256, 15m access / 30d refresh), validated via `require_app_context`. There is no management API key mechanism — and we don't need one.

**What overwatch needs:**

- A **service account** — a Nova user + organisation + app that overwatch can log into. Overwatch calls `POST /api/v1/auth/login` with the service account's email/password, gets JWT access + refresh tokens, and refreshes via `POST /api/v1/auth/refresh` as needed.
- This works with Nova's existing auth system. No Nova code changes required — just account creation.

**What overwatch will do with it:**

- Overwatch's `NovaClient` will authenticate with `POST /api/v1/auth/login`, cache the JWT, and auto-refresh before expiry.
- All management API calls (section 2) will use `Authorization: Bearer {jwt_access_token}`.
- Overwatch handles its own RBAC internally — Nova does not need to enforce role-level permissions. If the JWT is valid, trust the request.

**Additionally, overwatch needs an SDK API key** (`nova_sk_...`) for the same org+app. The `sync-nova-objects` endpoint (section 2.2) uses SDK key auth, not JWT. So overwatch needs both:
1. Service account credentials (email + password) → for JWT-authenticated management endpoints
2. SDK API key (`nova_sk_...`) → for sync-nova-objects

---

## 2. Endpoints Overwatch Needs (Management API)

All requests include `Authorization: Bearer {jwt_access_token}` unless noted otherwise.

### Endpoint summary

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | GET | `/api/v1/feature-flags/` | JWT | List all feature flags |
| 2 | GET | `/api/v1/feature-flags/{flag_pid}/` | JWT | Get feature flag detail |
| 3 | GET | `/api/v1/feature-flags/available/` | JWT | List flags not assigned to any experience |
| 4 | POST | `/api/v1/feature-flags/sync-nova-objects/` | **SDK key** | Create/update flags + experiences from code |
| 5 | GET | `/api/v1/experiences/` | JWT | List all experiences |
| 6 | GET | `/api/v1/experiences/{experience_pid}/` | JWT | Get experience detail |
| 7 | GET | `/api/v1/experiences/{experience_pid}/features/` | JWT | List features linked to an experience |
| 8 | GET | `/api/v1/personalisations/` | JWT | List all personalisations |
| 9 | GET | `/api/v1/personalisations/{pid}/` | JWT | Get personalisation detail |
| 10 | GET | `/api/v1/personalisations/personalised-experiences/{experience_id}/` | JWT | List personalisations for an experience |
| 11 | POST | `/api/v1/personalisations/create-personalisation/` | JWT | Create personalisation |
| 12 | PATCH | `/api/v1/personalisations/{pid}/` | JWT | Update personalisation |
| 13 | PATCH | `/api/v1/personalisations/{pid}/disable/` | JWT | Disable personalisation |
| 14 | PATCH | `/api/v1/personalisations/{pid}/enable/` | JWT | Enable personalisation |
| 15 | GET | `/api/v1/segments/` | JWT | List all segments |
| 16 | GET | `/api/v1/segments/{segment_pid}/` | JWT | Get segment detail (includes linked personalisations) |
| 17 | POST | `/api/v1/segments/` | JWT | Create segment |
| 18 | PUT | `/api/v1/segments/{segment_pid}/` | JWT | Update segment |

### Endpoint details

#### 2.1 Feature Flags

**`GET /api/v1/feature-flags/`** — List all feature flags

- **What overwatch does with this:** Displays a read-only list of all feature flags in the dashboard so admins can see what's configured and click through for detail.
- Params: `active_only` (bool, optional), `skip` (int, default 0), `limit` (int, default 100)
- Response: list of `FeatureFlagListItem`:
  ```json
  {
    "pid": "uuid",
    "name": "tournament_banner",
    "description": "Banner config for tournaments",
    "type": "feature_flag",
    "is_active": true,
    "keys_config": {
      "banner_url": {"type": "string", "description": "URL of the banner image", "default": ""},
      "tournament_pid": {"type": "string", "description": "Tournament identifier", "default": ""}
    },
    "default_variant": {"banner_url": "", "tournament_pid": ""},
    "experiences": [{"experience_id": "uuid"}]
  }
  ```
- `keys_config` defines the feature's configurable keys — each key has a `type`, `description`, and `default` value
- `default_variant` is derived from `keys_config` defaults

**`GET /api/v1/feature-flags/{flag_pid}/`** — Get feature flag detail

- **What overwatch does with this:** Shows full flag configuration when an admin clicks on a flag in the list.
- Params: `flag_pid` (path)
- Response: `FeatureFlagDetailedResponse` — same fields as list item, but `experiences` includes full experience detail (not just IDs)

**`GET /api/v1/feature-flags/available/`** — List flags not assigned to any experience

- **What overwatch does with this:** Shows orphaned or newly synced flags that haven't been linked to an experience yet, so admins can spot them on the dashboard.
- Params: same as list endpoint (`active_only`, `skip`, `limit`)
- Response: same shape as `GET /api/v1/feature-flags/` — list of `FeatureFlagListItem`

#### 2.2 Sync Nova Objects

**`POST /api/v1/feature-flags/sync-nova-objects/`** — Create/update feature flags and experiences from a declarative JSON payload

- **Auth: SDK API key** (`Authorization: Bearer nova_sk_...`), not JWT. This endpoint uses `require_sdk_app_context`.
- **What overwatch does with this:** When an admin creates a tournament banner, overwatch builds a sync payload that declares the feature flag (with `banner_url` + `tournament_pid` keys) and an experience linking it. This is the primary way overwatch creates flags — it doesn't call a "create flag" endpoint directly.
- Request body (`NovaObjectSyncRequest`):
  ```json
  {
    "objects": {
      "tournament_banner_parkour_open": {
        "type": "feature_flag",
        "keys": {
          "banner_url": {
            "type": "string",
            "description": "Azure CDN URL for the banner image",
            "default": ""
          },
          "tournament_pid": {
            "type": "string",
            "description": "Gamin tournament identifier",
            "default": ""
          }
        }
      }
    },
    "experiences": {
      "tournament_banner_parkour_open_experience": {
        "description": "Banner targeting for Parkour Open tournament",
        "objects": {
          "tournament_banner_parkour_open": true
        }
      }
    }
  }
  ```
- `objects` declares feature flags: each key is the flag name, value has `type` and `keys` (the configurable properties)
- `experiences` declares experiences: each key is the experience name, `objects` maps flag names to `true` to link them
- Response (`NovaObjectSyncResponse`):
  ```json
  {
    "success": true,
    "objects_processed": 1,
    "objects_created": 1,
    "objects_updated": 0,
    "objects_skipped": 0,
    "experiences_processed": 1,
    "experiences_created": 1,
    "experiences_updated": 0,
    "experiences_skipped": 0,
    "experience_features_created": 1,
    "dashboard_url": null,
    "message": "Sync completed successfully",
    "details": [
      {"type": "object", "name": "tournament_banner_parkour_open", "action": "created"},
      {"type": "experience", "name": "tournament_banner_parkour_open_experience", "action": "created"}
    ]
  }
  ```
- Idempotent: re-syncing the same payload updates existing objects rather than creating duplicates

#### 2.3 Experiences

**`GET /api/v1/experiences/`** — List all experiences

- **What overwatch does with this:** Displays experiences in the dashboard. Admins need to see which experiences exist before creating personalisations that target them.
- Params: `status` (optional), `search` (optional), `order_by` (default `created_at`), `order_direction` (default `desc`), `skip`, `limit`
- Response: list of `ExperienceListResponse`:
  ```json
  {
    "pid": "uuid",
    "name": "tournament_banner_parkour_open_experience",
    "description": "Banner targeting for Parkour Open tournament",
    "status": "active",
    "variants": [{"pid": "uuid"}],
    "features": [{"pid": "uuid"}]
  }
  ```

**`GET /api/v1/experiences/{experience_pid}/`** — Get experience detail

- **What overwatch does with this:** Shows the full experience with its linked features and variants when an admin clicks through.
- Params: `experience_pid` (path)
- Response (`ExperienceDetailedResponse`):
  ```json
  {
    "pid": "uuid",
    "name": "tournament_banner_parkour_open_experience",
    "description": "Banner targeting for Parkour Open tournament",
    "status": "active",
    "features": [
      {
        "pid": "uuid",
        "feature_flag": {
          "pid": "uuid",
          "name": "tournament_banner_parkour_open",
          "type": "feature_flag",
          "is_active": true
        }
      }
    ],
    "variants": [
      {
        "pid": "uuid",
        "name": "Default",
        "description": "Default variant",
        "is_default": true,
        "last_updated_at": "2026-03-12T10:30:00Z",
        "feature_variants": [
          {
            "pid": "uuid",
            "experience_feature_id": "uuid",
            "name": "Default Config",
            "config": {"banner_url": "", "tournament_pid": ""}
          }
        ]
      }
    ]
  }
  ```

**`GET /api/v1/experiences/{experience_pid}/features/`** — List features linked to an experience

- **What overwatch does with this:** When building the personalisation create form, overwatch needs the list of features (with their `experience_feature_id`s) linked to the selected experience. Each feature variant in a personalisation references an `experience_feature_id`, so this endpoint populates the form dropdown.
- Params: `experience_pid` (path)
- Response: list of `ExperienceFeatureResponse`:
  ```json
  [
    {
      "pid": "uuid",
      "feature_flag": {
        "pid": "uuid",
        "name": "tournament_banner_parkour_open",
        "type": "feature_flag",
        "is_active": true
      }
    }
  ]
  ```
- The `pid` in each item **is the `experience_feature_id`** to use in `feature_variants` when creating personalisations

#### 2.4 Personalisations

**`GET /api/v1/personalisations/`** — List all personalisations

- **What overwatch does with this:** Lists all personalisations so admins can manage targeting rules, priorities, and rollout percentages.
- Params: `search` (optional), `order_by`, `order_direction`, `skip`, `limit`
- Response: list of `PersonalisationListResponse`:
  ```json
  {
    "pid": "uuid",
    "name": "Parkour Open Banner — US Players",
    "description": "Show Parkour Open banner to US-based players",
    "experience_id": "uuid",
    "is_active": true,
    "experience": {"pid": "uuid", "name": "...", "description": "..."}
  }
  ```

**`GET /api/v1/personalisations/{pid}/`** — Get personalisation detail

- **What overwatch does with this:** Shows full personalisation config when an admin clicks through — including rule config, variants, metrics, and segment rules.
- Params: `pid` (path)
- Response (`PersonalisationDetailedResponse`):
  ```json
  {
    "pid": "uuid",
    "name": "Parkour Open Banner — US Players",
    "description": "Show Parkour Open banner to US-based players",
    "experience_id": "uuid",
    "priority": 1,
    "rollout_percentage": 100,
    "rule_config": {
      "conditions": [
        {"field": "country", "operator": "equals", "value": "US"}
      ],
      "operator": "AND"
    },
    "is_active": true,
    "experience_variants": [
      {
        "pid": "uuid",
        "target_percentage": 100,
        "experience_variant": {
          "pid": "uuid",
          "name": "Banner Active",
          "description": "Show the tournament banner",
          "is_default": true,
          "last_updated_at": "2026-03-12T10:30:00Z",
          "feature_variants": [
            {
              "pid": "uuid",
              "experience_feature_id": "uuid",
              "name": "Banner Config",
              "config": {
                "banner_url": "https://storage.blob.core.windows.net/cms-media/uuid/parkour-open.png",
                "tournament_pid": "tournament-uuid"
              }
            }
          ]
        }
      }
    ],
    "metrics": [],
    "segment_rules": []
  }
  ```

**`GET /api/v1/personalisations/personalised-experiences/{experience_id}/`** — List personalisations for an experience

- **What overwatch does with this:** When viewing an experience detail page, shows all personalisations targeting that experience so admins can see the full targeting setup at a glance.
- Params: `experience_id` (path)
- Response: list of `PersonalisationDetailedResponse` (same shape as single detail above)

**`POST /api/v1/personalisations/create-personalisation/`** — Create personalisation

- **What overwatch does with this:** When an admin sets up targeting for a tournament banner (e.g. "show this banner to players in the US"), overwatch creates a personalisation that links a segment rule to an experience with specific variant config.
- Request body (`PersonalisationCreate`):
  ```json
  {
    "name": "Parkour Open Banner — US Players",
    "description": "Show Parkour Open banner to US-based players",
    "experience_id": "uuid-of-experience",
    "priority": 1,
    "rule_config": {
      "conditions": [
        {
          "field": "country",
          "operator": "equals",
          "value": "US"
        }
      ],
      "operator": "AND"
    },
    "rollout_percentage": 100,
    "selected_metrics": [],
    "experience_variants": [
      {
        "experience_variant": {
          "name": "Banner Active",
          "description": "Show the tournament banner",
          "is_default": true,
          "feature_variants": [
            {
              "experience_feature_id": "uuid-of-experience-feature",
              "name": "Banner Config",
              "config": {
                "banner_url": "https://storage.blob.core.windows.net/cms-media/uuid/parkour-open.png",
                "tournament_pid": "tournament-uuid"
              }
            }
          ]
        },
        "target_percentage": 100
      }
    ],
    "segments": null
  }
  ```
- **Key fields:**
  - `experience_id` — which experience this personalisation targets
  - `priority` — evaluation order (lower = evaluated first, first match wins). Optional — Nova assigns one if omitted.
  - `rule_config` — targeting conditions (see section 5 for rule syntax)
  - `rollout_percentage` — what percentage of matching users see this (0-100)
  - `experience_variants` — the variant configs to serve when this personalisation matches. Each variant has `feature_variants` that set the actual key values (e.g. `banner_url`, `tournament_pid`). `target_percentage` across variants must sum to 100.
  - `segments` — optional list of `{segment_id, rule_config}`. Can be `null` if using inline `rule_config` instead.
  - `selected_metrics` — metric UUIDs to track for this personalisation
- Response: `PersonalisationDetailedResponse` with `pid`, `is_active: true`

**`PATCH /api/v1/personalisations/{pid}/`** — Update personalisation

- **What overwatch does with this:** Admins update targeting rules, rollout percentage, or variant config.
- Params: `pid` (path)
- Request body (`PersonalisationUpdate`) — partial update, any subset of:
  ```json
  {
    "name": "Updated Name",
    "description": "Updated description",
    "rule_config": { "conditions": [...], "operator": "AND" },
    "rollout_percentage": 50,
    "selected_metrics": [],
    "experience_variants": [...],
    "segments": [...],
    "reassign": false
  }
  ```
- `reassign` (bool, default false) — when `true`, re-evaluates all existing user assignments against the new rules. Use when changing targeting conditions.
- Response: `PersonalisationDetailedResponse`

**`PATCH /api/v1/personalisations/{pid}/disable/`** — Disable personalisation

- **What overwatch does with this:** Admins can turn off a personalisation without deleting it (e.g. pause a banner campaign).
- Params: `pid` (path)
- Request body: none
- Response: `PersonalisationDetailedResponse` with `"is_active": false`

**`PATCH /api/v1/personalisations/{pid}/enable/`** — Enable personalisation

- **What overwatch does with this:** Re-enable a previously disabled personalisation.
- Params: `pid` (path)
- Request body: none
- Response: `PersonalisationDetailedResponse` with `"is_active": true`

#### 2.5 Segments

**`GET /api/v1/segments/`** — List all segments

- **What overwatch does with this:** Displays available segments so admins can reuse them when creating personalisations, rather than writing inline rules every time.
- Params: `search` (optional), `skip`, `limit`
- Response: list of `SegmentListResponse`:
  ```json
  {
    "pid": "uuid",
    "name": "New Players (Last 7 Days)",
    "description": "Players who created their account within the last 7 days",
    "rule_config": {
      "conditions": [
        {"field": "days_since_signup", "operator": "less_than", "value": 7}
      ],
      "operator": "AND"
    }
  }
  ```

**`GET /api/v1/segments/{segment_pid}/`** — Get segment detail

- **What overwatch does with this:** Shows full segment config including which personalisations reference this segment — so admins know the blast radius before editing.
- Params: `segment_pid` (path)
- Response (`SegmentDetailedResponse`):
  ```json
  {
    "pid": "uuid",
    "name": "New Players (Last 7 Days)",
    "description": "Players who created their account within the last 7 days",
    "rule_config": {
      "conditions": [
        {"field": "days_since_signup", "operator": "less_than", "value": 7}
      ],
      "operator": "AND"
    },
    "personalisations": [
      {"pid": "uuid", "name": "Parkour Open Banner — New Players"}
    ]
  }
  ```

**`POST /api/v1/segments/`** — Create segment

- **What overwatch does with this:** Admins create reusable targeting segments (e.g. "US Players", "New Players Last 7 Days") that can be attached to multiple personalisations.
- Request body (`SegmentCreate`):
  ```json
  {
    "name": "New Players (Last 7 Days)",
    "description": "Players who created their account within the last 7 days",
    "rule_config": {
      "conditions": [
        {
          "field": "days_since_signup",
          "operator": "less_than",
          "value": 7
        }
      ],
      "operator": "AND"
    }
  }
  ```
- Validation: `name` 1-100 chars, `description` max 500 chars
- Response: `SegmentResponse` with `pid`

**`PUT /api/v1/segments/{segment_pid}/`** — Update segment

- **What overwatch does with this:** Admins edit a segment's rules (e.g. change the window from 7 to 14 days).
- Params: `segment_pid` (path)
- Request body (`SegmentUpdate`) — despite being PUT, all fields are optional (partial update):
  ```json
  {
    "name": "New Players (Last 14 Days)",
    "description": "Extended window to 14 days",
    "rule_config": {
      "conditions": [
        {
          "field": "days_since_signup",
          "operator": "less_than",
          "value": 14
        }
      ],
      "operator": "AND"
    }
  }
  ```
- Response: `SegmentResponse` with updated fields

---

## 3. What We Also Need (Guidance Requested)

### 3.1 User profile attribute names

**What we're building:** The rule builder UI needs a dropdown of available user profile fields (e.g. `country`, `platform`, `days_since_signup`) so admins can build segment/personalisation rules without guessing field names.

**What we need returned:** List of known user profile attribute keys, their types, and descriptions.

**What we found in the codebase:** A `UserProfileKeyResponse` schema exists in the metrics module (`pid`, `key`, `type`, `description`). Which endpoint returns this list? Is it something like `GET /api/v1/metrics/user-profile-keys/`?

---

## 4. Gamin SDK Integration (Runtime Endpoints)

Gamin (the game/tournament backend) integrates with Nova at runtime using the SDK key (`nova_sk_...`). This is a separate integration from overwatch's management API usage.

**Auth:** `Authorization: Bearer nova_sk_...` — SDK API key, validated via HMAC signature (stateless, zero DB lookups).

**Endpoints gamin will call:**

| # | Method | Path | Purpose |
|---|--------|------|---------|
| 1 | POST | `/api/v1/users/create-user/` | Register a user context in Nova when a player signs up |
| 2 | POST | `/api/v1/users/update-user-profile/` | Update user attributes for segment targeting |
| 3 | POST | `/api/v1/users/identify/` | Merge anonymous user into identified user |
| 4 | POST | `/api/v1/user-experience/get-experience/` | Evaluate a single experience for a user |
| 5 | POST | `/api/v1/user-experience/get-experiences/` | Evaluate specific experiences for a user (filtered by name) |
| 6 | POST | `/api/v1/user-experience/get-all-experiences/` | Evaluate all experiences for a user |
| 7 | POST | `/api/v1/metrics/track-events/` | Track user events for analytics (batch) |

### SDK endpoint schemas

**`POST /api/v1/users/create-user/`**
```json
// Request (UserCreate)
{"user_id": "player-123", "user_profile": {"country": "US", "platform": "ios"}}
// Response (UserResponse)
{"nova_user_id": "uuid"}
```

**`POST /api/v1/users/update-user-profile/`**
```json
// Request (UpdateUserProfile)
{"user_id": "player-123", "user_profile": {"country": "US", "level": 42}}
// Response (UserResponse)
{"nova_user_id": "uuid"}
```

**`POST /api/v1/users/identify/`**
```json
// Request (IdentifyUserRequest)
{"anonymous_id": "anon-abc", "identified_id": "player-123", "user_profile": {"country": "US"}}
// Response (IdentifyUserResponse)
{"nova_user_id": "uuid", "merged": true}
```
Merges an anonymous user's profile and experience assignments into the identified user. Call this when a player logs in after playing anonymously.

**`POST /api/v1/user-experience/get-experience/`**
```json
// Request (GetExperienceRequest)
{"user_id": "player-123", "experience_name": "tournament_banner_experience", "payload": {"tournament_status": "live"}}
// Response (UserExperienceAssignment)
{
  "experience_id": "uuid",
  "personalisation_id": "uuid",
  "personalisation_name": "Parkour Open Banner — US Players",
  "experience_variant_id": "uuid",
  "features": {
    "tournament_banner_parkour_open": {
      "feature_id": "uuid",
      "feature_name": "tournament_banner_parkour_open",
      "variant_id": "uuid",
      "variant_name": "Banner Active",
      "config": {
        "banner_url": "https://storage.blob.core.windows.net/cms-media/uuid/parkour-open.png",
        "tournament_pid": "tournament-uuid"
      }
    }
  },
  "evaluation_reason": "personalisation_match",
  "assigned_at": "2026-03-12T10:30:00Z"
}
```

**`POST /api/v1/user-experience/get-experiences/`**
```json
// Request (GetExperiencesRequest)
{"user_id": "player-123", "payload": {"tournament_status": "live"}, "experience_names": ["tournament_banner_experience"]}
// Response — dict keyed by experience name, each value is a UserExperienceAssignment (same shape as above)
```
- Pass a list of `experience_names` to evaluate specific experiences.

**`POST /api/v1/user-experience/get-all-experiences/`**
```json
// Request (GetExperiencesRequest)
{"user_id": "player-123", "payload": {"tournament_status": "live"}}
// Response — dict keyed by experience name, each value is a UserExperienceAssignment
```
- Convenience endpoint — evaluates all experiences for the user.

**`POST /api/v1/metrics/track-events/`**
```json
// Request (TrackEventsRequest)
{
  "user_id": "player-123",
  "events": [
    {"event_name": "banner_clicked", "event_data": {"tournament_pid": "uuid"}, "timestamp": "2026-03-12T10:30:00Z"}
  ]
}
// Response
{"success": true, "count": 1}
```
There is also a single-event variant: `POST /api/v1/metrics/track-event/` with a flat request body (`user_id`, `event_name`, `event_data`, `timestamp`).

**Notes:**
- These endpoints are gamin's responsibility to integrate, not overwatch's. Listed here for completeness so the Nova team has the full picture.
- Gamin needs confirmation that the SDK key auth works for all seven endpoints above.

---

## 5. Evaluation Model (How It Works)

This section documents how Nova evaluates experiences at runtime, based on studying the evaluation code in `nova_manager/components/rule_evaluator/controller.py`. Included here so both teams (gamin + overwatch) understand the mechanics.

### Rule config syntax

All rules (segment rules, personalisation rules) use the same `rule_config` format:

```json
{
  "conditions": [
    {"field": "country", "operator": "equals", "value": "US"},
    {"field": "level", "operator": "greater_than", "value": 10}
  ],
  "operator": "AND"
}
```

- `operator` at the top level: `"AND"` (all conditions must match) or `"OR"` (any condition matches)
- Each condition: `field` (attribute name), `operator` (comparison), `value` (target)

### Supported operators

| Operator | Description | Example |
|----------|-------------|---------|
| `equals` | Exact match | `{"field": "country", "operator": "equals", "value": "US"}` |
| `not_equals` | Not equal | `{"field": "status", "operator": "not_equals", "value": "banned"}` |
| `greater_than` | Numeric > | `{"field": "level", "operator": "greater_than", "value": 10}` |
| `less_than` | Numeric < | `{"field": "days_since_signup", "operator": "less_than", "value": 7}` |
| `greater_than_or_equal` | Numeric >= | `{"field": "age", "operator": "greater_than_or_equal", "value": 18}` |
| `less_than_or_equal` | Numeric <= | `{"field": "retries", "operator": "less_than_or_equal", "value": 3}` |
| `in` | Value in list | `{"field": "country", "operator": "in", "value": ["US", "CA", "UK"]}` |
| `not_in` | Value not in list | `{"field": "tier", "operator": "not_in", "value": ["banned", "suspended"]}` |
| `contains` | String contains | `{"field": "email", "operator": "contains", "value": "@company.com"}` |
| `starts_with` | String prefix | `{"field": "username", "operator": "starts_with", "value": "test_"}` |
| `ends_with` | String suffix | `{"field": "email", "operator": "ends_with", "value": ".edu"}` |

### Payload vs user_profile

When gamin calls `get-experience` or `get-experiences`, it can send two types of context:

- **`user_profile`** (via `create-user` / `update-user-profile`) — persistent, stored in Nova's DB. Attributes like `country`, `platform`, `level`.
- **`payload`** (via `get-experience` request body) — transient, per-request. Attributes like `tournament_status`, `current_page`.

**Merge precedence:** When evaluating rules, Nova merges `{**payload, **user_profile}` — **user_profile values win** on key conflicts. The payload is never written to the DB.

### Evaluation flow

1. For each experience, Nova checks personalisations in **priority order** (lower number = first)
2. For each personalisation:
   - Skip if `is_active` is false
   - Evaluate `rule_config` against merged context (`{**payload, **user_profile}`)
   - Check rollout percentage — deterministic SHA256 hash of `user_id:context_id` mapped to `[0.0, 1.0)`, compared against `target_percentage / 100.0`. No randomness — same user always gets the same bucket.
   - Check segment membership if segments are attached
   - If match → select variant by target percentage, return features
3. If no personalisation matches → return default experience (default variant from `keys_config` defaults)

### Evaluation reasons

The `evaluation_reason` field in responses tells you why a particular variant was returned:
- `personalisation_match` — a personalisation's rules matched
- `default_experience` — no personalisations exist or none matched
- `assigned_from_cache: <reason>` — returned cached assignment
- `personalisation_reassignment` — re-evaluated due to `reassign=true`

---

## 6. Error Responses

Nova error responses follow this format:

```json
{
  "detail": {
    "error_code": "ERROR_CODE_NAME",
    "message": "Human-readable description of what went wrong"
  }
}
```

Overwatch maps these to admin-friendly error messages in its UI.

**HTTP status codes:** 400 (bad request), 401 (unauthorized / JWT expired), 403 (forbidden), 404 (not found), 422 (validation error), 429 (rate limit), 500 (internal error).

**Validation errors** (422) include additional detail:
```json
{
  "detail": {
    "error_code": "REQUEST_VALIDATION_ERROR",
    "message": "Request validation error",
    "errors": "[field-level validation details]"
  }
}
```

**Known error codes:** `BAD_REQUEST`, `PERMISSION_DENIED`, `METHOD_NOT_ALLOWED`, `TIMEOUT`, `VALIDATION_ERROR`, `REQUEST_VALIDATION_ERROR`, `INTERNAL_SERVER_ERROR`, `EXTERNAL_API_ERROR`, `API_REQUEST_EXCEPTION`, `RATE_LIMIT_EXCEEDED`, `UNKNOWN_ERROR`.

---

## 7. Timeline and Priority

### Priority 1 — Service Account + SDK Key (blocker)

The service account (section 1) is the single blocker. This is trivial — just create a Nova user/org/app for overwatch and share the credentials + SDK key. No Nova code changes needed.

**What we need from Nova:**
1. Create a service account (email + password) for overwatch
2. Provide the SDK API key (`nova_sk_...`) for the same org+app
3. Share both with the overwatch team for environment config

### Priority 2 — Management Endpoints (section 2)

Once overwatch has credentials, we will integrate endpoints in this order:
1. Feature flags (read-only — `GET` list, detail, and available)
2. Sync nova objects (`POST` — for creating tournament banner flags)
3. Experiences (read-only — `GET` list, detail, and features)
4. Segments (full CRUD — `GET` list/detail, `POST`, `PUT`)
5. Personalisations (full CRUD — `GET` list/detail/by-experience, `POST`, `PATCH`, enable/disable)

### Priority 3 — User Profile Keys (section 3)

We need confirmation on which endpoint returns user profile attribute names for the rule builder UI dropdown. Not a blocker — we can hardcode known attributes initially and switch to the endpoint later.

### Priority 4 — Gamin SDK Endpoints (section 4)

Owned by the gamin team. They will integrate independently once they have a working SDK key. No overwatch work required — just confirmation from Nova that SDK key auth works for all listed endpoints.

---

## Open Questions

1. **Service account setup** — Can you create a service account for overwatch and share the credentials + SDK key?
2. **Sync behavior** — After overwatch calls sync-nova-objects, do personalisations/segments created via management API automatically take effect at runtime? Or is there an additional step needed?
3. **Pagination** — List endpoints support `skip` + `limit`. Is there a max `limit` value? Do responses include a `total` count for pagination UIs?
4. **User profile keys endpoint** — We found a `UserProfileKeyResponse` schema in the metrics module. Which endpoint path returns this list?
