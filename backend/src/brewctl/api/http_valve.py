import httpx

from brewctl.core.valve import AbstractValve


class HttpValve(AbstractValve):
    """HTTP valve that proxies operations to the hardware server."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str):
        with httpx.Client() as client:
            response = client.request(method, f"{self.base_url}{path}")
            response.raise_for_status()
            return response.json()

    def step_forward(self):
        self._request("POST", "/api/valve/nudge/open")

    def step_backward(self):
        self._request("POST", "/api/valve/nudge/close")

    def return_to_start(self):
        self._request("POST", "/api/valve/return_to_start")

    def release(self):
        self._request("POST", "/api/valve/release")

    def get_position(self) -> int:
        return self._request("GET", "/api/valve/position")["position"]
