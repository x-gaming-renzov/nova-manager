# 003: Event Batching (SDK + Backend)

## Problem

The SDK fired one HTTP request per `trackEvent` call. In apps with frequent events (button taps, screen views, scroll tracking), this creates excessive network traffic, drains battery on mobile, and puts unnecessary load on the backend.

## Solution

### Backend: New `POST /api/v1/metrics/track-events/` endpoint

Accepts an array of events in a single request. Each event includes `event_name`, `event_data`, and `timestamp`. The endpoint enqueues one background job that writes all events to ClickHouse via the existing `EventsController.track_events()` method.

**Request body:**

```json
{
  "user_id": "ext-user-123",
  "events": [
    {
      "event_name": "button_click",
      "event_data": { "button_id": "cta-main" },
      "timestamp": "2025-06-15T10:30:00Z"
    },
    {
      "event_name": "page_view",
      "event_data": { "page": "/home" },
      "timestamp": "2025-06-15T10:30:01Z"
    }
  ]
}
```

**Response:** `{ "success": true, "count": 2 }`

Authentication: SDK API key (`Authorization: Bearer nova_sk_...`), same as other SDK endpoints.

### SDK: Client-side event batching

Events are queued in memory and flushed to the backend in batches. Three flush triggers:

1. **Max size** (default: 10) — flushes immediately when the queue reaches this count
2. **Interval** (default: 5000ms) — periodic flush on a timer
3. **Unmount** — flushes remaining events when the provider unmounts (app background / navigation away)

On flush failure, events are pushed back to the front of the queue for retry on the next flush cycle.

**Configuration:**

```tsx
<NovaProvider config={{
  apiKey: "nova_sk_...",
  apiEndpoint: "https://api.example.com",
  eventBatch: {
    maxSize: 20,         // flush at 20 events (default: 10)
    flushInterval: 3000, // flush every 3s (default: 5000)
  },
  registry: { ... },
}}>
```

**Manual flush:**

```tsx
const { flushEvents } = useNova();

// Force-flush before navigation or logout
await flushEvents();
```

## Files Changed

### Backend (`nova-manager`)

| File | Change |
|------|--------|
| `api/metrics/request_response.py` | Added `TrackEventItem` and `TrackEventsRequest` models |
| `api/metrics/router.py` | Added `POST /track-events/` endpoint, imported new models |

### SDK (`nova-react-sdk`)

| File | Change |
|------|--------|
| `src/context/NovaContext.tsx` | Added `NovaEventBatchConfig` interface, `eventBatch` config option, queue/flush logic with `useRef`+`useEffect`, `flushEvents` method on context |
| `src/index.ts` | Exported `NovaEventBatchConfig` type |

## Notes

- The old single-event endpoint `POST /track-event/` still works. The SDK no longer calls it directly, but it remains available for other integrations.
- `trackEvent()` is now synchronous (returns `void`, not `Promise<void>`). It pushes to the local queue instantly.
- Timestamps are captured client-side at the moment `trackEvent` is called, not when the batch is flushed. This preserves accurate event timing.
- The batch endpoint uses the same SDK API key auth (`require_sdk_app_context`) as all other SDK endpoints.
