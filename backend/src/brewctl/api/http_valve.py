import json
import threading
import time
from typing import Any

import httpx

from brewctl.core.valve import AbstractValve
from brewctl.core.log import logger


class HttpValve(AbstractValve):
    """HTTP valve that proxies operations to the hardware server using SSE."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._sse_url = f"{self.base_url}/sse/valve/status"

        # Cached values from SSE stream
        self._available: bool = False
        self._position: int | None = None

        # Thread safety
        self._lock = threading.RLock()

        # SSE connection state
        self._sse_task: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._reconnect_delay = 1.0  # Start with 1 second delay
        self._max_reconnect_delay = 30.0  # Cap at 30 seconds

    def _parse_sse_line(self, line: str) -> dict[str, Any] | None:
        """Parse a single SSE line and extract data."""
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str:
                try:
                    return json.loads(data_str)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SSE data: {e}")
        return None

    def _run_sse_listener(self):
        """Background thread that listens to SSE stream."""
        logger.info(f"Starting SSE listener for valve at {self._sse_url}")

        while not self._stop_event.is_set():
            try:
                # Use a streaming client to read SSE
                with httpx.Client(timeout=60.0) as client:
                    with client.stream("GET", self._sse_url) as response:
                        response.raise_for_status()

                        # Reset reconnect delay on successful connection
                        self._reconnect_delay = 1.0

                        for line in response.iter_lines():
                            if self._stop_event.is_set():
                                break

                            data = self._parse_sse_line(line)
                            if data:
                                with self._lock:
                                    # Update cached values
                                    if "error" in data:
                                        # Hardware server unavailable
                                        self._available = False
                                        self._position = None
                                    else:
                                        self._available = data.get("available", False)
                                        self._position = data.get("position")

            except httpx.ConnectError as e:
                logger.warning(f"Cannot connect to valve SSE: {e}")
                with self._lock:
                    self._available = False
            except httpx.HTTPError as e:
                logger.error(f"HTTP error in SSE connection: {e}")
                with self._lock:
                    self._available = False
            except Exception as e:
                logger.error(f"Unexpected error in SSE listener: {e}")
                with self._lock:
                    self._available = False

            # Wait before reconnecting
            if not self._stop_event.is_set():
                logger.info(f"Reconnecting to valve SSE in {self._reconnect_delay}s...")
                self._stop_event.wait(self._reconnect_delay)
                # Exponential backoff
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

        logger.info("SSE listener stopped")

    @property
    def available(self) -> bool:
        """Check if the valve is available (connected via SSE)."""
        with self._lock:
            return self._available

    def connect(self):
        """Start the SSE listener thread."""
        if self._sse_task is not None and self._sse_task.is_alive():
            # logger.info("SSE listener already running")
            return

        self._stop_event.clear()
        self._sse_task = threading.Thread(target=self._run_sse_listener, daemon=True)
        self._sse_task.start()
        logger.info("Started SSE listener for valve")

    def disconnect(self):
        """Stop the SSE listener thread."""
        self._stop_event.set()
        if self._sse_task is not None:
            self._sse_task.join(timeout=5.0)
            self._sse_task = None
        logger.info("Stopped SSE listener for valve")

        with self._lock:
            self._available = False
            self._position = None

    def connect_with_backoff(self) -> bool:
        """
        Connect to the valve with exponential backoff retry logic.
        For SSE-based HttpValve, this starts the SSE listener.
        The SSE connection handles reconnection automatically.

        Returns True if connection was successful, False otherwise.
        """
        # Start the SSE listener - it handles reconnection automatically
        self.connect()
        # Give it a moment to establish connection
        time.sleep(0.5)
        return self.available

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
        """
        Get the valve position from cached SSE data.
        Falls back to HTTP request if SSE is not available.
        """
        with self._lock:
            if self._position is not None:
                return self._position

        # Fallback to HTTP request if SSE hasn't provided position yet
        return self._request("GET", "/api/valve/position")["position"]
