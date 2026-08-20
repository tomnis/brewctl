"""
Bare / should send people to the UI.

The api used to have no root route, so `http://<host>/` answered 404 on the
published port, through Traefik, and in prod-local alike -- a dead end for anyone
who did not already know the UI is served at /app.
"""


def test_root_redirects_to_the_app(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    # Trailing slash on purpose: /app would take a second hop through the catchall.
    assert response.headers["location"] == "/app/"


def test_root_redirect_is_not_permanent(client):
    # 308 would be cached by browsers indefinitely and is painful to walk back.
    assert client.get("/", follow_redirects=False).status_code != 308


def test_health_is_unaffected(client):
    # The container healthcheck probes /api/health, not /. A redirect is not a
    # health signal, so this must keep answering 200 directly.
    assert client.get("/api/health").status_code == 200
