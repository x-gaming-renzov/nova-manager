### Personalisation API (/api/v1/personalisations)

Create and list personalisations attached to experiences, with target percentages and metrics.

Common requirements:

- Bearer token and app context.

#### POST /api/v1/personalisations/create-personalisation/

Create a new personalisation for an experience.

Request

```json
{
	"name": "Promo 10%",
	"description": "Offer 10% discount",
	"experience_id": "<uuid>",
	"priority": 1,
	"rule_config": {
		"conditions": [{ "field": "country", "operator": "==", "value": "US" }],
		"operator": "AND"
	},
	"rollout_percentage": 100,
	"selected_metrics": ["<metric-uuid>"],
	"experience_variants": [
		{
			"target_percentage": 100,
			"experience_variant": {
				"name": "Variant A",
				"description": "Primary",
				"is_default": false,
				"feature_variants": [
					{
						"experience_feature_id": "<uuid>",
						"name": "Blue Button",
						"config": { "color": "#00F" }
					}
				]
			}
		}
	]
}
```

Response

```json
{ "pid": "<uuid>", "name": "Promo 10%", "description": "Offer 10% discount", "experience_id": "<uuid>", "priority": 1, "rollout_percentage": 100, "rule_config": { ... }, "experience_variants": [ { "target_percentage": 100, "experience_variant": { "name": "Variant A", "description": "Primary", "is_default": false } } ], "metrics": [ { "metric": { "pid": "<uuid>", "name": "WAU", "type": "count", "config": {} } } ] }
```

Notes

- Exactly one default variant allowed across variants; percentages must sum to 100.
- Experience, metrics must belong to the same organisation/app as the token.
- `priority` is optional. When provided, the personalisation is created with that exact priority. When omitted (`null`), priority is auto-assigned as `max_existing_priority + 1`.
- Returns **409 Conflict** if the supplied `priority` already exists for the same experience. Callers should handle this status code.
- Priority determines evaluation order: personalisations are evaluated in descending priority (highest first), and evaluation is first-match-wins. Choose priorities carefully to avoid unintentional shadowing.

#### GET /api/v1/personalisations/

List personalisations (search, pagination, ordering supported).

Query params

- search: string (optional)
- order_by: created_at | name | status (default created_at)
- order_direction: asc | desc (default desc)
- skip: int (default 0)
- limit: int (default 100)

Response: array of items with `experience` embedded.

#### GET /api/v1/personalisations/personalised-experiences/{experience_id}/

List personalisations associated with an experience.

Response: array of detailed personalisations for the experience.
