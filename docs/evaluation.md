### Evaluation API (/api/v1/user-experience)

Runtime endpoints to evaluate and return experience assignments for users.

Common requirements:

- All endpoints require SDK API-key authentication. The `organisation_id` and `app_id` are inferred from the API key — do not include them in the request body.
- The user must exist; otherwise 404 is returned by the flow.

#### POST /api/v1/user-experience/get-experience/

Get assignment for a single experience.

Request

```json
{
	"user_id": "external-user-123",
	"experience_name": "Homepage",
	"payload": { "country": "US", "ltv": 1200 }
}
```

Response

```json
{
	"experience_id": "<uuid>",
	"personalisation_id": "<uuid>|null",
	"personalisation_name": "Promo 10%|null",
	"experience_variant_id": "<uuid>|null",
	"features": {
		"Button": {
			"feature_id": "<uuid>",
			"feature_name": "Button",
			"variant_id": "<uuid>|null",
			"variant_name": "Blue Button|default",
			"config": { "color": "#00F" }
		}
	},
	"evaluation_reason": "personalisation_match",
	"assigned_at": "2025-01-15T10:30:00Z|null"
}
```

#### POST /api/v1/user-experience/get-experiences/

Get assignments for multiple named experiences.

Request

```json
{
	"user_id": "external-user-123",
	"payload": { "country": "US" },
	"experience_names": ["Homepage", "Checkout"]
}
```

Response

```json
{
  "Homepage": { "experience_id": "<uuid>", "features": { ... }, "evaluation_reason": "personalisation_match" },
  "Checkout": { "experience_id": "<uuid>", "features": { ... }, "evaluation_reason": "default_experience" }
}
```

#### POST /api/v1/user-experience/get-all-experiences/

Get assignments for all active features/objects across experiences for a user.

Request: same as get-experiences without `experience_names`.

Response: map keyed by experience name.

Notes

- If the user doesn’t exist, a 404 is returned. Create or update the user first via Users API.

---

### Payload in Personalisation Rules

The `payload` field in evaluation requests (`get-experience`, `get-experiences`, `get-all-experiences`) allows you to pass runtime context that the evaluation flow uses when checking personalisation rules and segment rules.

When to use:

- When you need to target users based on data that isn’t stored in their profile — e.g. the current page, cart value, device type, or any request-time context.
- The payload is used in two places during evaluation: segment rules (gating) and personalisation rules (targeting). See below for details.

#### Evaluation sequence

Each personalisation attached to an experience is checked in priority order. For each one the engine runs:

1. **Active check** — skip if the personalisation is disabled.
2. **Rollout percentage** — probabilistic gate based on user ID.
3. **Segment rules** — if the personalisation has segment rules, they are evaluated against the **raw `payload` only** (user profile is not included). At least one segment rule must match (`any` logic). If none match, the personalisation is skipped.
4. **Personalisation rules** — evaluated against a **merged context** of `{**payload, **user_profile}`. All conditions must match (`all` logic).
5. **Variant selection** — pick the experience variant by target percentage.

The first personalisation that passes all checks wins.

#### Merge precedence (personalisation rules)

The merged evaluation context is built as `{**payload, **user_profile}` — the stored **user profile wins** over payload for overlapping keys. Payload supplies supplementary runtime context; the profile remains authoritative.

#### Segment rules vs personalisation rules

- **Segment rules** act as a population-level gate. They see only the raw `payload`, so they are ideal for filtering on transient request-time context (page, device, session attributes).
- **Personalisation rules** see the full merged context (payload + profile), so they can reference both stored user attributes and runtime data.

Example: a personalisation rule targeting users with `cart_value > 100` can be evaluated by passing the current cart value in the payload:

```json
{
	"user_id": "external-user-123",
	"experience_name": "Checkout",
	"payload": { "cart_value": 150, "device": "mobile" }
}
```

If the user’s stored profile also contains `"device": "desktop"`, the personalisation rule evaluation context will use `"desktop"` (profile wins). Segment rules, however, would see `"mobile"` since they only receive the raw payload.

#### `reassign` flag on personalisations

By default, once a user is assigned to a personalisation, the assignment is cached and reused on subsequent evaluations (even if the payload changes). To support transient/runtime context like cart value, set `reassign=True` on the personalisation. This forces re-evaluation on every request, so the latest payload is always considered.

#### `evaluation_reason` values

The response includes an `evaluation_reason` field indicating why the assignment was made:

| Value | Meaning |
|---|---|
| `personalisation_match` | A personalisation rule matched (first evaluation). |
| `personalisation_reassignment` | Re-evaluated because the personalisation has `reassign=True` and the user already had a prior assignment. |
| `default_experience` | No personalisations are configured for this experience; default features returned. |
| `no_personalisation_match_error` | Personalisations exist but none matched the user’s context. Default features returned. |
| `no_experience_assignment_error` | Fallback when no assignment could be made (should not happen in normal operation). |
| `assigned_from_cache: <reason>` | Returned a cached assignment. The suffix shows the original reason. |

#### `assigned_at` field

The response includes `assigned_at` (ISO 8601 timestamp or `null`). It is populated when the assignment is returned from cache, indicating when the cached assignment was originally created.
