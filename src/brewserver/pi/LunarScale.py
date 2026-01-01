from scale import AbstractScale

from pyacaia import AcaiaScale
from pyacaia import *

import pyacaia
import time

class LunarScale(AbstractScale):
    """
    A class representing a Lunar scale, implementing the AbstractScale interface.
    Wraps around the AcaiaScale from the pyacaia library.
    """

    def __init__(self, mac_address: str):
        self.mac_address: str = mac_address
        self.scale: AcaiaScale = AcaiaScale(mac=self.mac_address)

    @property
    def connected(self) -> bool:
        return self.scale.connected

    def connect(self):
        print(f"Connecting to Lunar scale at MAC {self.mac_address}...")
        self.scale = AcaiaScale(self.mac_address)
        return self.scale.connect()


    def disconnect(self):
        # TODO experiment more with disconnect behavior and if we should clear out the scale pointer
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