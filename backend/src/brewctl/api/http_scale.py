import json
import threading
import time
from typing import Any

import httpx

from brewctl.core.scale import AbstractScale
from brewctl.core.log import logger


class HttpScale(AbstractScale):
    """HTTP scale that proxies operations to the hardware server using SSE."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._sse_url = f"{self.base_url}/sse/scale/status"

        # Cached values from SSE stream
        self._connected: bool = False
        self._weight: float | None = None
        self._units: str | None = None
        self._battery_pct: int | None = None

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
        logger.info(f"Starting SSE listener for scale at {self._sse_url}")

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
                                        self._connected = False
                                        self._weight = None
                                        self._units = None
                                        self._battery_pct = None
                                    else:
                                        self._connected = data.get("connected", False)
                                        self._weight = data.get("weight")
                                        self._units = data.get("units")
                                        self._battery_pct = data.get("battery_pct")

            except httpx.ConnectError as e:
                logger.warning(f"Cannot connect to scale SSE: {e}")
                with self._lock:
                    self._connected = False
            except httpx.HTTPError as e:
                logger.error(f"HTTP error in SSE connection: {e}")
                with self._lock:
                    self._connected = False
            except Exception as e:
                logger.error(f"Unexpected error in SSE listener: {e}")
                with self._lock:
                    self._connected = False

            # Wait before reconnecting
            if not self._stop_event.is_set():
                logger.info(f"Reconnecting to scale SSE in {self._reconnect_delay}s...")
                self._stop_event.wait(self._reconnect_delay)
                # Exponential backoff
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

        logger.info("SSE listener stopped")

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def connect(self):
        """Start the SSE listener thread."""
        if self._sse_task is not None and self._sse_task.is_alive():
            # logger.info("SSE listener already running")
            return

        self._stop_event.clear()
        self._sse_task = threading.Thread(target=self._run_sse_listener, daemon=True)
        self._sse_task.start()
        logger.info("Started SSE listener for scale")

    def disconnect(self):
        """Stop the SSE listener thread."""
        self._stop_event.set()
        if self._sse_task is not None:
            self._sse_task.join(timeout=5.0)
            self._sse_task = None
        logger.info("Stopped SSE listener for scale")

        with self._lock:
            self._connected = False
            self._weight = None
            self._units = None
            self._battery_pct = None

    def get_weight(self) -> float | None:
        with self._lock:
            return self._weight

    def get_units(self) -> str | None:
        with self._lock:
            return self._units

    def get_battery_percentage(self) -> int | None:
        with self._lock:
            return self._battery_pct

    def reconnect_with_backoff(self) -> bool:
        """
        Connect to the scale with exponential backoff retry logic.
        For SSE-based HttpScale, this starts the SSE listener.
        The SSE connection handles reconnection automatically.

        Returns True if connection was successful, False otherwise.
        """
        # Start the SSE listener - it handles reconnection automatically
        self.connect()
        # Give it a moment to establish connection
        time.sleep(0.5)
        return self.connected
