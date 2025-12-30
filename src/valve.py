from abc import ABC, abstractmethod

class Valve(ABC):

    def __init__(self):
        self._breadcrumbs = dict()

    @abstractmethod
    def release(self):
        """Release the valve."""
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
        pass

    def reset_breadcrumbs(self):
        """Clear the breadcrumbs."""
        self._breadcrumbs = dict()


class MockValve(Valve):
    """A mock implementation of the Valve class for testing purposes."""

    def __init__(self):
        super().__init__()
        self.position = 0  # Track the current position of the valve

    def release(self):
        print("Valve released.")

    def step_forward(self):
        self.position += 1
        print(f"Stepped forward to position {self.position}.")

    def step_backward(self):
        self.position -= 1
        print(f"Stepped backward to position {self.position}.")

    def return_to_start(self):
        print(f"Returning to start from position {self.position}.")
        self.position = 0
        print("Returned to start position 0.")