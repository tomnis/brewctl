from abc import ABC, abstractmethod

from log import logger

class AbstractScale(ABC):
    """
    An abstract base class representing a scale.
    Defines the interface for scale implementations.

    Designed as a wrapper around Lunar scale to allow for easier mocking and testing.
    """

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Check if the scale is connected."""
        pass

    @abstractmethod
    def connect(self):
        """Connect to the scale."""
        pass

    @abstractmethod
    def disconnect(self):
        """Disconnect from the scale."""
        pass

    @abstractmethod
    def get_weight(self) -> float:
        """Get the current weight in grams from the scale."""
        pass

    @abstractmethod
    def get_units(self) -> str:
        """Get the units of measurement from the scale."""
        pass

    @abstractmethod
    def get_battery_percentage(self) -> int:
        """Get the battery percentage of the scale."""
        pass



class MockScale(AbstractScale):
    """A mock implementation of the Scale class for testing purposes."""
    import random

    def __init__(self):
        self._connected = False
        self._weight = 0.0
        self._units = 'grams'
        self._battery_percentage = 100
        self._auto_off = 10

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self):
        logger.info("[Mock] Scale connected.")
        self._connected = True

    def disconnect(self):
        logger.info("[Mock] Scale disconnected.")
        self._connected = False

    def get_weight(self) -> float:
        """Simulate weight changes for testing."""
        delta = self.random.random() / 2
        self._weight += delta
        return self._weight

    def get_units(self) -> str:
        return self._units

    def get_battery_percentage(self) -> int:
        return self._battery_percentage