import random
import threading
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

    def reconnect_with_backoff(self) -> bool:
        """
        Connect to the scale with exponential backoff retry logic.
        
        Override this in subclasses to implement specific retry behavior.
        Default implementation just calls connect() once.
        
        Returns True if connection was successful, False otherwise.
        """
        self.connect()
        return self.connected



class MockScale(AbstractScale):
    """A mock implementation of the Scale class for testing purposes."""

    def __init__(self):
        self._connected = False
        self._weight = 0.0
        self._units = 'grams'
        self._battery_percentage = 100
        self._auto_off = 10
        self._updater_thread = None
        self._stop_event = threading.Event()

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self):
        logger.info("[Mock] Scale connecting.")
        self._connected = True
        self._stop_event.clear()
        self._start_updater()

    def disconnect(self):
        logger.info("[Mock] Scale resetting weight, disconnecting.")
        self._stop_updater()
        self._weight = 0.0
        self._connected = False

    def _start_updater(self):
        """Start the background thread that increments weight every 2 seconds."""
        self._updater_thread = threading.Thread(target=self._run_updater, daemon=True)
        self._updater_thread.start()

    def _run_updater(self):
        """Background loop that increments weight every 2 seconds."""
        while not self._stop_event.wait(2.0):
            delta = random.random() / 2
            self._weight += delta

    def _stop_updater(self):
        """Stop the background updater thread."""
        self._stop_event.set()
        if self._updater_thread is not None:
            self._updater_thread.join(timeout=1.0)

    def get_weight(self) -> float:
        """Get the current weight in grams from the scale."""
        return self._weight
        # raise Exception("mock scale error")

    def get_units(self) -> str:
        return self._units

    def get_battery_percentage(self) -> int:
        return self._battery_percentage
