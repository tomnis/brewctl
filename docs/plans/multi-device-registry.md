# 6. Multi-device registry

## Problem

The api service talks to exactly one hardware node: `BREWCTL_HARDWARE_URL`, a single env var read
at import time in `api/config.py`. Brew state is a single module-global `cur_brew` in
`api/server.py`, and the two brew tasks terminate by comparing `brew_id == cur_brew.id`. One brew,
one machine, forever.

The current branch is called `device_mode` and `deploy/pi/` sets up a per-Pi bare-metal install, so
the direction of travel is already multiple hardware nodes. Worth planning the state model now
even if it is built last.

## Design

### Registry

Table `devices`: id, name, base_url, kind (`hardware`), enabled, last_seen, capabilities JSON,
notes. Seeded from `BREWCTL_HARDWARE_URL` on first startup so existing single-node deployments
migrate silently and keep working with no configuration change.

Capabilities come from the hardware service itself — add `GET /api/capabilities` there, returning
whether a scale and valve are present, which implementations are in use (`LunarScale` vs
`MockScale`), steps per revolution, and a version string. The api service polls it on registration
and periodically. This also gives a clean answer to "is that node running mocks or real hardware",
which is currently invisible.

### State model — the real work

Replace the module globals with a `BrewSession` object held in a `dict[device_id, BrewSession]`:

```python
class BrewSession:
    device_id: str
    brew: Brew
    scale: AbstractScale        # HttpScale bound to that device
    valve: AbstractValve        # HttpValve bound to that device
    strategy: AbstractBrewStrategy
    weight_buffer: WeightBuffer
    tasks: list[asyncio.Task]
```

Everything currently reached as a module global — `cur_brew`, `scale`, `valve`, `weight_buffer` —
becomes a field on the session. The `brew_id == cur_brew.id` loop-termination trick is replaced by
holding a reference to the session and checking `session.cancelled`, or better, by cancelling the
`asyncio.Task` objects directly, which is what they are for.

This is the single largest and most invasive change in this directory. It touches nearly every
endpoint in `api/server.py`. Do it as a mechanical refactor with the existing test suite green
before and after, in its own commit, *before* adding any multi-device behaviour on top. The
`client`/`reset_globals` fixtures in `backend/tests/api/conftest.py` will need to reset the session
map instead of module attributes.

A useful intermediate state: introduce `BrewSession` while still allowing only one, keyed by a
constant device id. That gets the refactor landed and tested without any new user-facing surface.

### API

Every brew endpoint gains an optional `device_id`. When the registry holds exactly one enabled
device, it is inferred — so existing clients and the current frontend keep working unchanged.

```
GET    /api/devices
POST   /api/devices              { name, base_url }
PATCH  /api/devices/{id}
DELETE /api/devices/{id}
GET    /api/devices/{id}/health  proxied

POST   /api/brew/start?device_id=...
GET    /api/brew/status?device_id=...      # plus GET /api/brews/active for all sessions
GET    /sse/brew/status?device_id=...
```

### Frontend

A device selector in the header, hidden entirely when only one device is registered. `BrewProvider`
becomes parameterised by device id, and SSE URLs in `brew/constants.ts` gain the query parameter.
Note the existing gotcha that those URLs are derived by string-rewriting the API URL — worth
replacing that with a proper URL builder while in there.

An overview page showing all devices and their current brews is the payoff for the whole spec.

## Files touched

Substantially all of `backend/src/brewctl/api/server.py`, plus:

- new `backend/src/brewctl/api/session.py`, `devices.py`
- `backend/src/brewctl/api/config.py` — `BREWCTL_HARDWARE_URL` becomes a seed value, not the source
  of truth
- `backend/src/brewctl/hardware/server.py` — `GET /api/capabilities`
- `backend/tests/api/conftest.py` — session-map reset
- `frontend/src/components/brew/BrewProvider.tsx`, `constants.ts`, `Header.tsx`

## Open questions

- Does one Acaia scale get shared between vessels, or does each device have its own? If shared, the
  model is wrong — the scale is a separate resource that sessions must acquire, and the registry
  needs a scale/valve split rather than a device abstraction.
  **Answer this before building.** It changes the schema.
- Device discovery (mDNS) is tempting and unnecessary. Manual registration by URL is fine for a
  handful of nodes.

## Depends on

Spec #1 for the storage layer. The `BrewSession` refactor can be done independently and first.
