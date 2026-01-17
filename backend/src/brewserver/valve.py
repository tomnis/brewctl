from abc import ABC, abstractmethod

class AbstractValve(ABC):

    @abstractmethod
    def release(self):
        """Release the valve (underlying motor is now allowed to spin freely)."""
        pass

    @abstractmethod
    def step_forward(self):
        """Take one step forward."""
        pass

    @abstractmethod
    def step_backward(self):
        """Take one step backward."""
        pass

    @abstractmethod
    def return_to_start(self):
        """Return the valve to the starting position."""

from log import logger

class MockValve(AbstractValve):
    """A mock implementation of the Valve class for testing purposes."""

    def __init__(self):
        super().__init__()
        self.position = 0  # Track the current position of the valve

    def release(self):
        logger.info("[Mock] Valve released.")

    def step_forward(self):
        self.position += 1
        logger.info(f"[Mock] Stepped forward to position {self.position}.")

    def step_backward(self):
        self.position -= 1
        logger.info(f"[Mock] Stepped backward to position {self.position}.")

    def return_to_start(self):
        self.position = 0
        logger.info("[Mock] Valve returns to start.")