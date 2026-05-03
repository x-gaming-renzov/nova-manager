### Formula Metrics

The `formula` metric type composes multiple metrics with arithmetic expressions. Each operand is a full metric definition of any type (`count`, `aggregation`, `ratio`, `retention`, `operational`). This enables composite KPIs like CAC, ROAS, ARPU, and net margin that combine event-based analytics with business operational data.

Computed via `POST /api/v1/metrics/compute/` with `"type": "formula"`.

---

#### ROAS — revenue / spend

Both operands are `operational` metrics querying the `business_metrics` table.

```json
{
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "revenue": {
        "type": "operational",
        "config": { "metric_name": "total_revenue", "aggregation": "sum" }
      },
      "spend": {
        "type": "operational",
        "config": { "metric_name": "marketing_spend", "aggregation": "sum" }
      }
    },
    "expression": "revenue / spend"
  }
}
```

Response

```json
[
  { "period": "2026-07-01", "value": 0.15 },
  { "period": "2026-08-01", "value": 0.6538461538461539 }
]
```

---

#### Net Margin — revenue - spend

Subtraction works the same way.

```json
{
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "revenue": {
        "type": "operational",
        "config": { "metric_name": "total_revenue", "aggregation": "sum" }
      },
      "spend": {
        "type": "operational",
        "config": { "metric_name": "marketing_spend", "aggregation": "sum" }
      }
    },
    "expression": "revenue - spend"
  }
}
```

Response

```json
[
  { "period": "2026-07-01", "value": -6800.0 },
  { "period": "2026-08-01", "value": -4500.0 }
]
```

---

#### CAC — mixing operational + event-based operands

The `spend` operand queries business data, while `mau` counts distinct users from the event stream.

```json
{
  "type": "formula",
  "config": {
    "time_range": { "start": "2026-07-01 00:00:00", "end": "2026-09-01 00:00:00" },
    "granularity": "monthly",
    "group_by": [],
    "operands": {
      "spend": {
        "type": "operational",
        "config": { "metric_name": "marketing_spend", "aggregation": "sum" }
      },
      "mau": {
        "type": "count",
        "config": { "event_name": "session_start", "distinct": true }
      }
    },
    "expression": "spend / mau"
  }
}
```

---

#### Common formula patterns

| KPI | Expression | Operands |
|-----|-----------|----------|
| CAC | `spend / mau` | operational(marketing_spend) / count(distinct session_start) |
| ROAS | `revenue / spend` | operational(total_revenue) / operational(marketing_spend) |
| ARPU | `revenue / mau` | operational(total_revenue) / count(distinct session_start) |
| Net Margin | `revenue - spend` | operational(total_revenue) - operational(marketing_spend) |
| Cost per Tournament | `spend / tournaments` | operational(marketing_spend) / count(tournament.created) |
| Revenue per Tournament | `revenue / tournaments` | operational(total_revenue) / count(tournament.created) |
| Margin % | `(revenue - spend) / revenue` | Two operational operands with parenthesized expression |

---

#### How it works

1. Each operand's config is built into a full SQL sub-query using the same `QueryBuilder` that powers count/aggregation/etc.
2. The formula's `time_range` and `granularity` **override** whatever is set in individual operand configs, ensuring all operands are computed over the same period.
3. Each sub-query becomes a CTE (`WITH op_spend AS (...), op_mau AS (...)`).
4. CTEs are JOINed on `period` (and any `group_by` keys).
5. The expression is applied as the final SELECT, with division denominators automatically wrapped in `nullIf(..., 0)` to prevent divide-by-zero.

---

#### Expression rules

- Allowed tokens: operand names, `+`, `-`, `*`, `/`, `(`, `)`, numeric literals
- Operand names must match keys in the `operands` object
- Division by an operand is automatically safe-divided (`nullIf(x, 0)`)
- Parentheses must be balanced
- No nesting: operand type cannot be `formula`
- SQL keywords, semicolons, quotes, and other injection attempts are rejected

---

#### Config reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `operands` | object | yes | Map of name to `{type, config}`. Each operand is a full metric config. Type cannot be `formula`. |
| `expression` | string | yes | Arithmetic expression using operand names. |
| `time_range` | object or string | yes | Overrides all operand time ranges. |
| `granularity` | string | yes | Overrides all operand granularities. |
| `group_by` | array | no | Applied to all operands. Results joined on period + group keys. |
