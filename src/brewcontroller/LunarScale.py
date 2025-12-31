from ..base.scale import AbstractScale

from pyacaia import AcaiaScale
from pyacaia import *

import pyacaia
import time

class LunarScale(AbstractScale):

    def __init__(self, mac_address: str):
        self.mac_address: str = mac_address
        self.scale: AcaiaScale = AcaiaScale(mac_address)

    @property
    def connected(self) -> bool:
        return self.scale.connected

    # TODO could probably do this in __enter__ ?
    def connect(self):
        print(f"Connecting to Lunar scale at MAC {self.mac_address}...")
        return self.scale.connect()


    def disconnect(self):
        self.scale.disconnect()
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