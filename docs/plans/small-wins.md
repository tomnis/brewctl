# 8. Small wins

Independent, individually small changes. Each is a few hours at most. Roughly ordered by value.

---

## 8.1 Vessel weight — done, not as auto-tare

**Rejected: auto-tare.** The original proposal was to read the scale when the start form opens,
prefill `vessel_weight`, and add a tare button. There is one brew vessel and its weight is known up
front, so there is nothing to detect. `vessel_weight` was not even a form field — there was nothing
to prefill.

The actual defects, both fixed:

- The weight was the literal `229` in two unconnected places: `core/config.py`
  (`BREWCTL_VESSEL_WEIGHT_GRAMS`) and a hardcoded `vessel_weight: 229` in the `/api/brew/start` body
  built by `StartBrew.tsx`. The frontend value won, because `start_brew` uses `req.vessel_weight`
  whenever a body is present — so setting the env var on the control host did nothing for brews
  started from the UI. The frontend now omits the field entirely and the config default applies.
  Changing vessels is an env var change plus a restart, no code change. `StartBrewRequest` still
  accepts `vessel_weight`, so API callers can override per brew.
- `BrewStatus` did not expose `vessel_weight`, so the UI compared gross weight to gross target: an
  empty 229 g vessel already read as 17% brewed. `BrewStatus` now carries it, `formatProgressBar`
  moved to `components/brew/progress.ts`, and the bar is computed net of the vessel.

**Follow-up, not done:** `target_weight` is *gross* — it includes the vessel (see the comment in
`core/config.py`). So switching to a vessel of a different weight without also adjusting
`BREWCTL_TARGET_WEIGHT_GRAMS` silently changes how much coffee gets brewed; the env var alone does
not express "same recipe, different vessel". Making the target mean coffee touches every strategy's
`coffee_target`, `brew_quality.py`, and the UI's target field, so it is its own change.

---

## 8.2 Prometheus metrics

Add `GET /metrics` to both services via `prometheus-client`. Almost all the values already exist as
local variables; they just are not exported.

Api service:

- `brewctl_flow_rate_grams_per_second{brew_id}` gauge
- `brewctl_flow_rate_error` gauge — the single most useful line on a dashboard
- `brewctl_valve_position` gauge
- `brewctl_valve_commands_total{command}` counter
- `brewctl_brews_total{outcome}` counter
- `brewctl_scale_data_age_seconds` gauge (see spec #5)
- `brewctl_influx_write_failures_total` counter

Hardware service:

- `brewctl_watchdog_trips_total` counter
- `brewctl_scale_connected` gauge
- `brewctl_sse_clients` gauge

Pairs well with the InfluxDB instance already in the stack. Cheap, and it makes every other spec
here easier to evaluate after the fact.