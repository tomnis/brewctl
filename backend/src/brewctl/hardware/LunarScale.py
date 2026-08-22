from ..core.scale import AbstractScale

from pyacaia import AcaiaScale
from pyacaia import *

import pyacaia
import threading
import time

from ..core.log import logger
from ..core.config import (
    BREWCTL_SCALE_RECONNECT_RETRIES,
    BREWCTL_SCALE_RECONNECT_BASE_DELAY,
    BREWCTL_SCALE_RECONNECT_MAX_DELAY,
)


class LunarScale(AbstractScale):
    """
    A class representing a Lunar scale, implementing the AbstractScale interface.
    Wraps around the AcaiaScale from the pyacaia library.
    """

    def __init__(self, mac_address: str, max_retries: int = None, base_delay: float = None, max_delay: float = None):
        self.mac_address: str = mac_address
        self.scale: AcaiaScale = AcaiaScale(mac=self.mac_address)
        # reconnect_with_backoff() swaps self.scale from a threadpool worker while
        # the SSE tick, /health and /api/scale/status read it from others.
        self._lock = threading.Lock()
        # Allow override of defaults via constructor, otherwise use config
        self.max_retries = max_retries if max_retries is not None else BREWCTL_SCALE_RECONNECT_RETRIES
        self.base_delay = base_delay if base_delay is not None else BREWCTL_SCALE_RECONNECT_BASE_DELAY
        self.max_delay = max_delay if max_delay is not None else BREWCTL_SCALE_RECONNECT_MAX_DELAY

    @property
    def connected(self) -> bool:
        scale = self.scale
        return scale is not None and scale.connected

    def connect(self):
        logger.info(f"Connecting to Lunar scale at MAC {self.mac_address}...")
        # A fresh AcaiaScale has to earn its health back: its weight starts as None
        # and only a notification packet sets it, so carrying the old timestamp over
        # would mask a connection that reconnects but never streams.
        self.clear_weight_history()
        with self._lock:
            self.scale = AcaiaScale(self.mac_address)
            scale = self.scale
        return scale.connect()

    def reconnect_with_backoff(self) -> bool:
        """
        Connect to the scale with exponential backoff retry logic.
        
        Returns True if connection was successful, False otherwise.
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Scale connection attempt {attempt + 1}/{self.max_retries} for MAC {self.mac_address}...")
                self.clear_weight_history()
                with self._lock:
                    self.scale = AcaiaScale(self.mac_address)
                    scale = self.scale
                result = scale.connect()

                if result or scale.connected:
                    logger.info(f"Successfully connected to scale at MAC {self.mac_address} on attempt {attempt + 1}")
                    return True
                    
            except Exception as e:
                last_error = e
                logger.warning(f"Scale connection attempt {attempt + 1} failed: {e}")
            
            # Calculate delay with exponential backoff, capped at max_delay
            if attempt < self.max_retries - 1:  # Don't sleep after the last attempt
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.info(f"Retrying scale connection in {delay:.1f} seconds...")
                time.sleep(delay)
        
        logger.error(f"Failed to connect to scale after {self.max_retries} attempts. Last error: {last_error}")
        return False

    def disconnect(self):
        # The AcaiaScale object stays in place. Nulling it made every subsequent
        # read (connected, /health, the SSE tick, the scale monitor) raise
        # AttributeError instead of simply reporting a disconnected scale, which
        # left nothing able to drive a reconnect.
        scale = self.scale
        if scale is not None:
            scale.disconnect()
        self.clear_weight_history()
        time.sleep(0.5)

    def get_weight(self) -> float:
        # Logic to get weight in grams from the Lunar scale
        weight = self.scale.weight
        # None here means no notification packet has ever arrived on this AcaiaScale
        # instance -- pyacaia never resets weight to None once it has been set.
        self.note_weight(weight)
        return weight

    def get_units(self) -> str:
        # Logic to get units from the Lunar scale
        return self.scale.units

    def get_battery_percentage(self) -> float:
        # Logic to get battery percentage from the Lunar scale
        return self.scale.battery

    def get_auto_off(self) -> int:
        return self.scale.auto_off