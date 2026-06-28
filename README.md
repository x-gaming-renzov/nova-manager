# Nova Manager

A FastAPI-based application for managing nova experiences and campaigns.

## Features

- Feature flag management
- User experience personalization
- Campaign management
- Segment management
- Experience management

## Installation

See the Docker setup for containerized deployment.

poetry run python scripts/run_worker.py
uvicorn nova_manager.main:app --host 0.0.0.0 --reload
docker run -d --name redis -p 6379:6379 redis:latest

## Admin access key (`NOVA_ADMIN_KEY`)

A single shared secret gates the privileged surfaces. **Set it in every
environment** — when unset, these surfaces fail closed (deny all):

```
NOVA_ADMIN_KEY=<a long random secret>
```

What it protects:

- **API docs** — `/docs`, `/redoc`, `/openapi.json` require HTTP Basic auth.
  Any username; the password is `NOVA_ADMIN_KEY` (the browser prompts on first
  visit).
- **Self-service registration** — `POST /api/v1/auth/register` requires the
  header `X-Nova-Admin-Key: <key>`.
- **Admin cleanup** — `POST /api/v1/admin/cleanup` (below) requires the same
  header.

### Cleaning a deployed instance over HTTP

`POST /api/v1/admin/cleanup` empties **all** Nova data — every Postgres table and
every per-app ClickHouse analytics table — via `TRUNCATE` (tables are kept, only
emptied). Use the helper script instead of calling it by hand; it always previews
counts first and asks for confirmation:

```
# preview only (no changes)
NOVA_ADMIN_KEY=<key> python -m scripts.cleanup_nova_via_api --url https://nova.example.com --dry-run

# wipe (prompts to confirm; add --yes to skip)
NOVA_ADMIN_KEY=<key> python -m scripts.cleanup_nova_via_api --url https://nova.example.com
```

> `scripts/cleanup_experiences.py` remains for local, DB-direct cleanup of just
> experiences + feature flags.