### Events API (/api/v1/metrics)

Event tracking endpoints.

#### POST /api/v1/metrics/track-event/

Track an event for a user.

Request

```json
{
	"user_id": "<uuid>",
	"organisation_id": "org-123",
	"app_id": "app-123",
	"timestamp": "2024-01-01T12:00:00Z",
	"event_name": "purchase",
	"event_data": { "amount": 19.99, "currency": "USD" }
}
```

Response

```json
{ "success": true }
```

Notes

- Events are queued asynchronously and processed server-side.
- See Metrics for event schema discovery and metric computations.
- When `timestamp` is omitted, the server assigns the current time in **UTC**. All server-generated timestamps are UTC — ensure downstream queries and dashboards account for this.
