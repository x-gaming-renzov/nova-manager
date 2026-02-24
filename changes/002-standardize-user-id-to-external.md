# 002: Standardize user_id to External String

## Problem

The SDK and backend had an inconsistent `user_id` contract:

- **User endpoints** (`create-user`, `update-user-profile`) accepted the external `user_id` (string)
- **Experience endpoints** (`get-experience`, `get-experiences`, `get-all-experiences`) expected `user_id` as internal nova UUID and looked up via `users.pid`
- The **SDK** stored the internal `novaUserId` from the `create-user` response and sent it for all subsequent calls
- **ClickHouse** analytics stored nova UUIDs instead of the developer's external user_id

This forced SDK consumers to manage an internal ID they shouldn't need, and broke analytics consistency.

## Decision

All SDK-facing endpoints now accept the **external user_id** (string). The backend translates to internal UUID server-side. ClickHouse stores external user_id.

## Changes

### Backend (nova-manager)

| File | Change |
|------|--------|
| `api/user_experience/request_response.py` | `GetExperienceRequest.user_id` and `GetExperiencesRequest.user_id`: `UUID` -> `str` |
| `flows/get_user_experience_variant_flow_async.py` | Param types `UUID` -> `str`; lookup via `get_by_user_id()` instead of `get_by_pid()`; passes `external_user_id` to CRUD for ClickHouse |
| `api/users/router.py` | `track_user_profile` queue task now receives external `user_id` instead of `nova_user_id` |
| `components/metrics/events_controller.py` | Type hints `UUID` -> `str` for `track_event`, `track_events`, `track_user_profile`; `track_user_experience` accepts `external_user_id` param for ClickHouse |
| `components/user_experience/crud_async.py` | `bulk_create_user_experience_personalisations` accepts + passes `external_user_id` to ClickHouse tracking |
| `components/user_experience/event_listeners.py` | Removed `after_insert` listener (was duplicating ClickHouse writes already done in `crud_async.py`) |
| `main.py` | Removed import of now-empty event_listeners |

### SDK (nova-react-sdk)

| File | Change |
|------|--------|
| `src/context/NovaContext.tsx` | `NovaConfig`: removed `organisationId`/`appId`, added `apiKey`; `NovaUser.novaUserId` now optional; all API calls send `state.user.userId` (external) instead of `novaUserId`; all requests include `Authorization: Bearer <apiKey>` header; removed `organisation_id`/`app_id` from request bodies |

## What Did NOT Change

- **PostgreSQL FK**: `user_experience.user_id` stays as UUID FK to `users.pid`
- **create-user response**: Still returns `nova_user_id` (useful for debugging)
- **ClickHouse table DDL**: Column types remain `String` (no schema migration)
- **`api.ts`**: Already supported custom headers
- **Backend request models for users/metrics**: Already used `str` for `user_id`
- **sync-nova-objects endpoint**: No user_id involved

## Migration Notes

- Existing ClickHouse data has nova UUIDs stored as `user_id`
- New data will have external user_id strings
- A backfill script can update historical data using the `users.pid -> users.user_id` mapping:
  ```sql
  -- Example per-table backfill (run for each ClickHouse table)
  ALTER TABLE org_X_app_Y.raw_events
  UPDATE user_id = '<external_id>'
  WHERE user_id = '<nova_uuid_string>'
  ```

## SDK Usage (After)

```tsx
<NovaProvider
  config={{
    apiKey: process.env.NOVA_SDK_API_KEY!,
    apiEndpoint: process.env.NOVA_API_ENDPOINT!,
    registry: NovaRegistry,
  }}
>
  <App />
</NovaProvider>
```

```tsx
// Identify user with their external ID
await setUser({ userId: "user-123", userProfile: { country: "US" } });

// All subsequent calls use external userId automatically
await loadAllExperiences();
await trackEvent("button_clicked", { page: "/home" });
```
