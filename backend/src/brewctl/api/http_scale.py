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
        self._http_url = f"{self.base_url}/api/scale"
        self._sse_url = f"{self.base_url}/sse/scale/status"
        logger.info(self._sse_url)

        # Cached values from SSE stream
        self._connected: bool = False
        self._weight: float | None = None
        self._units: str | None = None
        self._battery_pct: int | None = None
        # Mirrored from the hardware payload rather than computed here. Only the Pi
        # sees real BLE packets; a locally-computed staleness would just measure how
        # long ago this object was constructed. None means the hardware service did
        # not send the field -- a v1 Pi -- which callers must read as "unknown".
        self._healthy: bool | None = None
        self._last_weight_age: float | None = None
        # Set once the first SSE frame lands, so callers can wait for one instead of
        # judging a scale that has simply not been heard from yet.
        self._first_frame = threading.Event()

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

    def _invalidate_cache(self):
        """Drop the cached reading when the stream breaks.

        Clearing the weight matters as much as the connected flag: a brew computes
        flow from these values, and a frozen reading looks exactly like a stalled
        pour rather than a lost connection.
        """
        with self._lock:
            self._connected = False
            self._weight = None
            self._units = None
            self._battery_pct = None
            self._healthy = False
            self._last_weight_age = None

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
                            # logger.info(f"scale data: {data}")
                            if data:
                                with self._lock:
                                    # Update cached values
                                    if "error" in data:
                                        # Hardware server unavailable
                                        self._connected = False
                                        self._weight = None
                                        self._units = None
                                        self._battery_pct = None
                                        self._healthy = False
                                        self._last_weight_age = None
                                    else:
                                        self._connected = data.get("connected", False)
                                        self._weight = data.get("weight")
                                        self._units = data.get("units")
                                        self._battery_pct = data.get("battery_pct")
                                        self._healthy = data.get("healthy")
                                        self._last_weight_age = data.get(
                                            "last_weight_age_seconds"
                                        )
                                self._first_frame.set()

            except httpx.ConnectError as e:
                logger.warning(f"Cannot connect to scale SSE: {e}")
                self._invalidate_cache()
            except httpx.HTTPError as e:
                logger.error(f"HTTP error in SSE connection: {e}")
                self._invalidate_cache()
            except Exception as e:
                logger.error(f"Unexpected error in SSE listener: {e}")
                self._invalidate_cache()

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
        """Start the SSE listener thread and connect the hardware scale."""
        # A reconnected stream has to deliver a frame before its cache means
        # anything again.
        self._first_frame.clear()
        # First, call the hardware server to connect the physical scale
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(f"{self._http_url}/connect")
                response.raise_for_status()
                logger.info("Hardware scale connected via server")
        except httpx.HTTPError as e:
            logger.warning(f"Failed to connect hardware scale: {e}")
            # Continue anyway - the SSE listener will handle the error state

        if self._sse_task is not None and self._sse_task.is_alive():
            # logger.info("SSE listener already running")
            return

        self._stop_event.clear()
        self._sse_task = threading.Thread(target=self._run_sse_listener, daemon=True)
        self._sse_task.start()
        logger.info("Started SSE listener for scale")

    def disconnect(self):
        """Stop the SSE listener thread and disconnect the hardware scale."""
        self._stop_event.set()
        if self._sse_task is not None:
            self._sse_task.join(timeout=5.0)
            self._sse_task = None
        logger.info("Stopped SSE listener for scale")

        # Call the hardware server to disconnect the physical scale
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(f"{self._http_url}/disconnect")
                response.raise_for_status()
                logger.info("Hardware scale disconnected via server")
        except httpx.HTTPError as e:
            logger.warning(f"Failed to disconnect hardware scale: {e}")

        self._invalidate_cache()

    def get_weight(self) -> float | None:
        with self._lock:
            return self._weight

    def get_units(self) -> str | None:
        with self._lock:
            return self._units

    def get_battery_percentage(self) -> int | None:
        with self._lock:
            return self._battery_pct

    def healthy(self, max_age: float) -> bool:
        """Override: staleness is the hardware service's call, not ours.

        AbstractScale.healthy() measures against note_weight(), which nothing sets
        on this class -- reads are served from the SSE cache, not from a device.
        An unknown verdict (a v1 Pi) counts as healthy; the brew gate refuses only
        on an explicit False.
        """
        return self.connected and self.is_healthy() is not False

    def is_healthy(self) -> bool | None:
        """Hardware's verdict, or None if it does not report one (a v1 Pi)."""
        with self._lock:
            return self._healthy

    def last_weight_age_seconds(self) -> float | None:
        with self._lock:
            return self._last_weight_age

    def wait_for_first_frame(self, timeout: float) -> bool:
        """Block until one SSE frame has landed. False on timeout.

        A freshly constructed HttpScale knows nothing; the hardware tick is
        SCALE_SSE_INTERVAL (2s) while reconnect_with_backoff only sleeps 0.5s, so
        without this any health check runs before the first frame can arrive.
        """
        return self._first_frame.wait(timeout)

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
