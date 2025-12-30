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