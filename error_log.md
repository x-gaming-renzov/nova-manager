# Error Log

**Date:** 2026-04-23
**Status:** `500 Internal Server Error`

---

## Error Response

```json
{
    "detail": "Nova API error: {'error_code': 'UNKNOWN_ERROR', 'message': 'Unknown error', 'error': 'Received ClickHouse exception, code: 403, server response: Code: 403. DB::Exception: JOIN LEFT JOIN ... ON (r.user_id = i.user_id) AND (r.ret_ts > i.first_ts) AND (r.ret_ts < (i.first_ts + toIntervalDay(30))) join expression contains column from left and right table, you may try experimental support of this feature by SET allow_experimental_join_condition = 1. (INVALID_JOIN_ON_EXPRESSION) (version 24.8.14.39 (official build))'}"
}
```

---

## cURL

```bash
curl -X POST \
  'https://kr-es-api-dev-ewg0bbb8b4dqagdx.a03.azurefd.net/api/v1/overwatch/admin/cms/deployments/metrics/compute' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <YOUR_TOKEN>' \
  -d '{
    "type": "retention",
    "config": {
        "time_range": {
            "start": "2026-03-18 12:17:18",
            "end": "2026-04-17 12:17:18"
        },
        "granularity": "daily",
        "group_by": [],
        "filters": {},
        "initial_event": {
            "event_name": "auth.login_success",
            "distinct": false
        },
        "return_event": {
            "event_name": "role.switched",
            "distinct": false
        },
        "retention_window": "30d"
    }
}'
```

> Replace `<YOUR_TOKEN>` with a valid Bearer token.
