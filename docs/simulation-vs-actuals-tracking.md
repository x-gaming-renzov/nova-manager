# Feature: Simulation vs Actuals Tracking

## Problem

Simulations produce projected values (e.g., "we expect CAC of $2.19 in July"). As real data comes in (actual events, actual spend), there's no built-in way to compare projected vs actual performance. Users have to manually construct cross-scenario formulas to see the gap.

## What's needed

1. **Actuals ingestion alongside simulations** — A clear workflow for ingesting real business data under `scenario_id="actuals"` as the months progress. Could be automated from accounting/finance systems or manual upload.

2. **Variance computation** — Given a simulation scenario and actuals, compute the difference for every metric:
   - `variance = actual - projected`
   - `variance_pct = (actual - projected) / projected`
   - Flag metrics that are off by more than X%

3. **Comparison API** — An endpoint like:
   ```
   GET /api/v1/simulations/{id}/compare/?actuals_scenario_id=actuals
   ```
   Returns side-by-side values: projected, actual, variance for each metric and month.

4. **Time-aware tracking** — As months pass, lock in actuals for completed months while keeping projections for future months. For example, in September:
   - Jul, Aug: show actuals
   - Sep-Dec: show projections
   - Blend them into a single "best estimate" view

5. **Alert thresholds** — Notify when actuals deviate from projections beyond a threshold (e.g., "October CAC is 40% above projection").

## Current state

- Simulations write to `business_metrics` with `scenario_id="scenario_v2"` etc.
- The business data API accepts `scenario_id="actuals"` for real data
- Formula metrics can reference either scenario via operand config
- A manual cross-scenario formula works today but requires the user to build it themselves:
  ```json
  {
    "operands": {
      "actual_cac": { "type": "operational", "config": { "metric_name": "total_marketing_spend", "scenario_id": "actuals" } },
      "projected_cac": { "type": "operational", "config": { "metric_name": "total_marketing_spend", "scenario_id": "scenario_v2" } }
    },
    "expression": "actual_cac - projected_cac"
  }
  ```

## Design considerations

- Should variance be computed on raw metrics (spend, MAU) or on KPIs (CAC, ROAS)?
- Should the comparison endpoint live under `/simulations/` or `/metrics/`?
- How to handle months where actuals don't exist yet (return projections? null? flag as "pending")?
- Should there be a dedicated "actuals" entity or is `scenario_id="actuals"` sufficient?
