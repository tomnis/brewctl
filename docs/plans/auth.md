# 7. Authentication

## Problem

Neither service authenticates anything. Every endpoint on both apps is open, including
`POST /api/valve/nudge/open` and `POST /api/brew/start`. `BREWCTL_CORS_ORIGINS` exists but CORS is
a browser policy, not access control — it stops no non-browser client at all.

Today that is survivable because everything sits on a trusted LAN. It stops being survivable the
moment anything is exposed through a tunnel or reverse proxy, and the failure mode is physical:
anyone who can reach the hardware service can open a valve.

There is also a service-to-service gap. The api service calls the hardware service over plain HTTP
with no credential, so any host on the network can drive the hardware directly, bypassing every
piece of brew logic and safety checking in the api service.

## Design

Deliberately minimal. This is a single-user home system; OAuth would be absurd here.

### Two independent shared secrets

`BREWCTL_API_TOKEN` — for clients (browser, scripts) talking to the api service.
`BREWCTL_HARDWARE_TOKEN` — for the api service talking to the hardware service.

Separate secrets so a leaked browser token cannot drive the hardware directly.

Both checked by FastAPI dependencies:

```python
async def require_token(authorization: str = Header(None)):
    if not CONFIGURED_TOKEN:          # unset -> auth disabled, log a warning at startup
        return
    if not compare_digest(extract_bearer(authorization), CONFIGURED_TOKEN):
        raise HTTPException(401)
```

Use `hmac.compare_digest`, not `==`. Log a loud warning at startup when a token is unset so an
unprotected deployment is obvious rather than silent.

Apply as a router-level dependency rather than per-endpoint, so a newly added endpoint is protected
by default. Exempt `/health` only — monitoring should not need a credential, and it leaks nothing.

### Browser problem

`EventSource` cannot set an `Authorization` header. Three options:

1. Accept the token as a query parameter on SSE endpoints only. Simple; leaks the token into
   access logs and browser history.
2. Exchange the token for an `HttpOnly` cookie at `POST /api/auth/login`, and accept either a
   bearer header or that cookie. Cookies are sent on `EventSource` requests automatically.
3. Use `fetch` with a streaming reader instead of `EventSource` on the frontend.

Go with **2**. It is barely more code than 1, keeps the secret out of URLs, and gives a natural
login screen. Set `SameSite=Strict`, and `Secure` when served over TLS.

Frontend: a login form storing nothing itself (the cookie does the work), plus a 401 interceptor in
`brewService.ts` that redirects to it. SSE hooks need to handle a 401 by stopping rather than
reconnect-looping forever against an auth wall.

### Hardware service

`HttpScale` and `HttpValve` attach `Authorization: Bearer $BREWCTL_HARDWARE_TOKEN` to every request
and to the SSE stream — both use `httpx`, which sets headers on streams without difficulty. This is
strictly easier than the browser case.

Also bind the hardware service to a specific interface rather than `0.0.0.0` where the deployment
allows it. Defence in depth; see `deploy/pi/`.

## Files touched

- new `backend/src/brewctl/core/auth.py` — shared dependency, used by both apps
- `backend/src/brewctl/api/server.py`, `hardware/server.py` — router dependencies, login endpoint
- `backend/src/brewctl/core/config.py` — both token vars
- `backend/src/brewctl/api/http_scale.py`, `http_valve.py` — send the hardware token
- `frontend/src/components/brew/brewService.ts` — 401 handling
- new `frontend/src/components/auth/Login.tsx`
- `deploy/pi/hardware.env.example`, `docker-compose.yml`, `README.md`

## Testing

- Every mutating endpoint returns 401 without a token and 200 with one.
- Unset token disables enforcement (so existing deployments and the test suite are unaffected by
  default) and logs the warning.
- Wrong token is rejected; the comparison is constant-time.

## Size

Small — under a day, most of it frontend. Prerequisite for exposing this system beyond the LAN, and
worth doing before that becomes urgent rather than after.
