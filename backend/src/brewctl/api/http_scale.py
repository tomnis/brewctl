import httpx

from brewctl.core.scale import AbstractScale


class HttpScale(AbstractScale):
    """HTTP scale that proxies operations to the hardware server."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str):
        with httpx.Client() as client:
            response = client.request(method, f"{self.base_url}{path}")
            response.raise_for_status()
            return response.json()

    @property
    def connected(self) -> bool:
        return self._request("GET", "/api/scale/status")["connected"]

    def connect(self):
        self._request("POST", "/api/scale/connect")

    def disconnect(self):
        self._request("POST", "/api/scale/disconnect")

    def get_weight(self) -> float:
        return self._request("GET", "/api/scale/status")["weight"]

    def get_units(self) -> str:
        return self._request("GET", "/api/scale/status")["units"]

    def get_battery_percentage(self) -> int:
        return self._request("GET", "/api/scale/status")["battery_pct"]
