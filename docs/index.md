# Nova Manager API Documentation

Welcome to the Nova Manager API documentation. This manual provides an exhaustive list of APIs grouped by product domains and explains how to use each endpoint with examples.

### Base URL and Versioning

- Base URL: your host (e.g., https://api.your-domain.com)
- API Version: v1
- All API routes are mounted under prefixes like `/api/v1/<domain>` unless otherwise noted.

### Authentication

- Most endpoints require a JWT Bearer token in the `Authorization` header.
- Header: `Authorization: Bearer <access_token>`
- Obtain tokens via the Auth endpoints.
- Some endpoints also require organisation context and/or app context; see endpoint notes.

### Categories

- Auth: `docs/auth.md`
- Objects (Feature Flags): `docs/objects.md`
- Experiences: `docs/experiences.md`
- Segments: `docs/segments.md`
- Metrics: `docs/metrics.md`
- Business Data: `docs/business-data.md`
- Operational Metrics: `docs/operational-metrics.md`
- Formula Metrics: `docs/formula-metrics.md`
- Personalisation: `docs/personalisations.md`
- Events: `docs/events.md`
- Evaluation (Runtime): `docs/evaluation.md`
- Users: `docs/users.md`
- Invitations: `docs/invitations.md`
- Recommendations: `docs/recommendations.md`

### Conventions

- UUIDs are referred to as `pid` in responses when applicable.
- All timestamps are ISO-8601 unless otherwise stated.
- Errors are returned as JSON with appropriate HTTP status codes. Validation errors include details.
