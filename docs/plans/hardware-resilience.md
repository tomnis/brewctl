# 5. Hardware resilience — staleness-aware transport

## Problem

`HttpScale` (`backend/src/brewctl/api/http_scale.py`) subscribes to the hardware service's SSE
stream on a background thread and caches the latest values. `get_weight()` returns
`self._weight` from that cache, with no indication of *when* it was written.

The reconnect logic is already reasonable — exponential backoff capped at 30s, `_connected` set
false on connect/HTTP errors. The dangerous case is the one it does not cover: a connection that
stays open but stops delivering data. A wedged TCP connection, a hung hardware process, or a BLE
scale that stopped updating without disconnecting all leave `_connected = True` and a stale weight
in the cache. `httpx` has a 60s timeout on the stream, but that is a long time to control on a
frozen number.

Meanwhile `brew_step_task` reads that cached weight, computes a flow rate that trends to zero
(weight is not changing), and every strategy responds the same way: open the valve. The failure
mode of a frozen scale is a valve driven wide open with no feedback. That is the worst outcome the
system can produce.

The in-process `WeightBuffer` already has exactly the right concept — `is_ready()` and
`is_stale()`, which `brew_step_task` consults before trusting its flow rate. The transport layer
needs the same discipline.

## Design

### Timestamp the cache

In both `HttpScale` and `HttpValve`, record `_last_update_monotonic` on every SSE payload applied.
Add:

```python
@property
def data_age_seconds(self) -> float          # inf if never received
@property
def is_fresh(self) -> bool                   # age < BREWCTL_SCALE_STALE_SECONDS
```

`BREWCTL_SCALE_STALE_SECONDS` defaults to something a few multiples of the hardware publish
interval — 5s if hardware publishes at ~2 Hz.

Then make `connected` mean what callers assume it means: `self._connected and self.is_fresh`.
Keep the raw flag available separately for diagnostics, because "connected but stale" and
"disconnected" want different messages.

### Watchdog the reader, not just the writer

Add a staleness check inside `_run_sse_listener`: if no payload has arrived for
`stale_seconds * 2`, tear the stream down and reconnect rather than waiting for the httpx timeout.
This is what actually rescues a wedged-but-open connection.

### Degrade the brew safely

In `brew_step_task`, before calling `strategy.step()`:

- If the scale reading is stale, **do not** call the strategy with the old weight. Treat it as a
  brew-level fault.
- Grace period (`BREWCTL_SCALE_STALE_GRACE_SECONDS`, default ~15s): hold the valve at its current
  position and keep feeding the heartbeat, so a brief hiccup does not abort a multi-hour brew.
- Past the grace period: return the valve to start, transition the brew to `PAUSED` with an
  informative `error_message`, emit a notification (spec #4), and keep polling. If the scale comes
  back, resume; the brew is recoverable.

Holding position rather than closing is the right call for a short outage — closing and reopening a
stepper valve loses the operating point that took minutes to find. Past the grace period, safety
wins and it closes.

Note the interaction with the hardware watchdog: while paused-on-stale, the api must keep calling
`valve.heartbeat()` if it intends to hold the valve open, otherwise `WATCHDOG_TIMEOUT_SECONDS`
(default 10s) closes it anyway. The existing `sleep_with_heartbeat()` helper is the mechanism —
make sure the degraded path uses it and does not fall back to a plain `asyncio.sleep`.

### Health surface

`GET /api/health` currently reports scale connected / valve available / influx connected. Extend it
so `DEGRADED` is actually reachable:

- `HEALTHY` — everything fresh
- `DEGRADED` — connected but stale data, or Influx down while a brew runs (the brew survives; only
  logging is lost)
- `UNHEALTHY` — no hardware connection, or a brew is faulted

Include `data_age_seconds` for scale and valve in the payload. `useConnectionStatus` and
`ConnectionStatus.tsx` on the frontend then have something meaningful to render — a stale-data
warning is much more actionable than a green dot that lies.

## Files touched

- `backend/src/brewctl/api/http_scale.py`, `http_valve.py` — timestamps, freshness, reader watchdog
- `backend/src/brewctl/api/config.py` — stale and grace thresholds
- `backend/src/brewctl/api/server.py` — degraded path in `brew_step_task`, richer `/api/health`
- `frontend/src/components/ConnectionStatus.tsx`, `brew/useConnectionStatus.ts`

## Testing

- Unit: feed the parser payloads, advance a fake clock, assert `is_fresh` flips.
- Unit: no payloads for `2 * stale` seconds causes a reconnect attempt.
- Integration: mock scale that freezes mid-brew. Assert the valve does not open further, that the
  brew pauses after the grace period, and that it resumes when readings return. This is the test
  that matters — write it first.

## Priority

High. This is not a feature; it is the difference between a scale glitch costing a batch and
costing a flood. Worth doing before anything on this list except possibly #1.
