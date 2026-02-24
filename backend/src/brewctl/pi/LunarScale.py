from scale import AbstractScale

from pyacaia import AcaiaScale
from pyacaia import *

import pyacaia
import time

from log import logger
from config import COLDBREW_SCALE_RECONNECT_RETRIES, COLDBREW_SCALE_RECONNECT_BASE_DELAY, COLDBREW_SCALE_RECONNECT_MAX_DELAY


class LunarScale(AbstractScale):
    """
    A class representing a Lunar scale, implementing the AbstractScale interface.
    Wraps around the AcaiaScale from the pyacaia library.
    """

    def __init__(self, mac_address: str, max_retries: int = None, base_delay: float = None, max_delay: float = None):
        self.mac_address: str = mac_address
        self.scale: AcaiaScale = AcaiaScale(mac=self.mac_address)
        # Allow override of defaults via constructor, otherwise use config
        self.max_retries = max_retries if max_retries is not None else COLDBREW_SCALE_RECONNECT_RETRIES
        self.base_delay = base_delay if base_delay is not None else COLDBREW_SCALE_RECONNECT_BASE_DELAY
        self.max_delay = max_delay if max_delay is not None else COLDBREW_SCALE_RECONNECT_MAX_DELAY

    @property
    def connected(self) -> bool:
        return self.scale.connected

    def connect(self):
        print(f"Connecting to Lunar scale at MAC {self.mac_address}...")
        self.scale = AcaiaScale(self.mac_address)
        return self.scale.connect()

    def reconnect_with_backoff(self) -> bool:
        """
        Connect to the scale with exponential backoff retry logic.
        
        Returns True if connection was successful, False otherwise.
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Scale connection attempt {attempt + 1}/{self.max_retries} for MAC {self.mac_address}...")
                self.scale = AcaiaScale(self.mac_address)
                result = self.scale.connect()
                
                if result or self.scale.connected:
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
        # TODO experiment more with disconnect behavior and if we should clear out the scale pointer
        if self.scale is not None:
            self.scale.disconnect()
        self.scale = None
        time.sleep(0.5)


    def get_weight(self) -> float:
        # Logic to get weight in grams from the Lunar scale
        return self.scale.weight

    def get_units(self) -> str:
        # Logic to get units from the Lunar scale
        return self.scale.units

    def get_battery_percentage(self) -> float:
        # Logic to get battery percentage from the Lunar scale
        return self.scale.battery

    def get_auto_off(self) -> int:
        return self.scale.auto_off