### Metrics API (/api/v1/metrics)

Manage metrics definitions and compute results.

Common requirements:

- Bearer token and app context for all except `track-event` which is public in this API (but should include org/app IDs in body).

#### POST /api/v1/metrics/compute/

Compute a metric ad-hoc.

Request

```json
{
	"type": "count",
	"config": {
		"event": "purchase",
		"time_range": { "start": "2024-01-01", "end": "2024-01-31" }
	}
}
```

Response

```json
[{ "date": "2024-01-01", "value": 10 }]
```

#### GET /api/v1/metrics/events-schema/

List known event schemas.

Query params

- search: string (optional)

Response

```json
[
	{
		"pid": "<uuid>",
		"event_name": "purchase",
		"event_schema": { "amount": "number" }
	}
]
```

#### GET /api/v1/metrics/user-profile-keys/

List known user profile keys.

Query params

- search: string (optional)

Response

```json
[
	{
		"pid": "<uuid>",
		"key": "ltv",
		"type": "number",
		"description": "Lifetime value"
	}
]
```

#### POST /api/v1/metrics/

Create a metric definition.

Request

```json
{
	"name": "Weekly Active Users",
	"description": "WAU",
	"type": "count",
	"config": { "event": "login" }
}
```

Response

```json
{
	"pid": "<uuid>",
	"name": "Weekly Active Users",
	"description": "WAU",
	"type": "count",
	"config": { "event": "login" }
}
```

#### GET /api/v1/metrics/

List metrics.

Response: array of metric objects.

#### GET /api/v1/metrics/{metric_id}/

Get a metric by id.

Response: metric object.

#### PUT /api/v1/metrics/{metric_id}/

Update a metric.

Request

```json
{
	"name": "WAU",
	"description": "Weekly AU",
	"type": "count",
	"config": { "event": "login" }
}
```

Response: updated metric object.

### Retention metrics

Retention queries use ClickHouse-compatible SQL. The retention calculation:
- Uses `INTERVAL` arithmetic (e.g., `i.first_ts + INTERVAL 30 DAY`) for time-window filtering
- Applies time-window conditions inside `IF()` aggregation expressions rather than in JOIN clauses (required for ClickHouse v24.8+ compatibility)
- Guards against divide-by-zero with `IF(count = 0, 0, retained / total)` instead of `SAFE_DIVIDE`

**Note:** Retention values reflect users who performed the return event within the retention window. Users with no qualifying return event are correctly counted as not retained.
