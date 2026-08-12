# 4. Notifications

## Problem

A cold brew runs for hours. The only way to learn that it finished, errored, or that the watchdog
shut the valve is to have the frontend open. Nothing pushes.

The events worth knowing about all already exist as identifiable moments in the code:

- brew completed — the `STOP` branch in `brew_step_task` (`api/server.py`)
- brew errored — the error handler in the same task, which already builds a `BrewErrorResponse`
- watchdog tripped and closed the valve — `hardware/server.py`
- scale disconnected mid-brew — `HttpScale` cache goes disconnected (see spec #5)
- brew approaching target — e.g. 90% of `target_weight`, so there is time to get to the kitchen

## Design

A small `notifier` module in the api service with one pluggable backend, chosen by env var.
Default off, so nothing changes for anyone who does not configure it.

```
BREWCTL_NOTIFY_BACKEND      none | ntfy | webhook   (default none)
BREWCTL_NOTIFY_URL          ntfy topic URL, or generic webhook URL
BREWCTL_NOTIFY_TOKEN        optional bearer token
BREWCTL_NOTIFY_EVENTS       comma-separated allowlist; default: complete,error,watchdog
```

ntfy first — it is a single HTTP POST, needs no account, and has phone apps. The generic webhook
backend posts the event as JSON, which covers Home Assistant, Discord, and anything else.

Interface:

```python
class Notifier(Protocol):
    async def notify(self, event: NotifyEvent) -> None: ...

@dataclass
class NotifyEvent:
    kind: str                 # complete | error | watchdog | scale_lost | near_target
    title: str
    body: str
    priority: str             # low | default | high
    brew_id: str | None
    url: str | None           # deep link to the brew in the frontend
```

### Rules that matter

- **Never block or fail the brew.** Every send is fire-and-forget with a short timeout, wrapped so
  an exception is logged and swallowed. A down notification server must not kill a brew.
- **Deduplicate.** The watchdog can trip repeatedly; the scale can flap. Rate-limit per event kind
  to one message per N minutes (default 5).
- **The watchdog event originates in the hardware service**, which has no notifier and should not
  grow one. Options: the hardware service exposes the trip in its status stream and the api service
  notices and notifies (preferred — keeps hardware dumb), or hardware posts a callback to the api.
  Go with the first: add a `watchdog_tripped` counter/timestamp to the valve SSE payload, and have
  `HttpValve` surface it.

### Frontend

Nothing required. Optionally a settings panel that shows whether notifications are configured and
a "send test notification" button, which is worth the small effort — misconfigured webhooks are
otherwise silent.

## Files touched

- new `backend/src/brewctl/api/notify.py`
- `backend/src/brewctl/api/config.py` — the four env vars
- `backend/src/brewctl/api/server.py` — emit at complete, error, near-target
- `backend/src/brewctl/hardware/server.py` — expose watchdog trip in the valve status payload
- `backend/src/brewctl/api/http_valve.py` — cache and expose it
- `docker-compose.yml`, `deploy/pi/hardware.env.example` — document the vars

## Testing

- A fake notifier records events; assert one `complete` event per finished mock brew with the right
  brew id.
- Backend raising an exception does not fail the brew.
- Rate limiter suppresses the second of two identical events inside the window.

## Size

Small. Half a day. Highest value-per-line of anything in this directory.
