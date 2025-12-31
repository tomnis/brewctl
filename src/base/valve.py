import time
from abc import ABC, abstractmethod, ABCMeta
from functools import wraps


# A metaclass modifies the class-creation behavior not the instance creation behavior
class MetaValve(ABCMeta):
    def __new__(cls, name, bases, attrs):
        """Metaclass for tasks."""
        for attr_name, attr_value in attrs.items():
            if attr_name == "step_forward" and callable(attr_value):
                attrs[attr_name] = cls.step_forward_decorator(attr_value)
            elif attr_name == "step_backward" and callable(attr_value):
                attrs[attr_name] = cls.step_backward_decorator(attr_value)
        x = super().__new__(cls, name, bases, attrs)
        return x

    @staticmethod
    def step_forward_decorator(func):
        print(f" Decorating method: {func.__qualname__}")
        @wraps(func)
        def wrapper(*args, **kwargs):
            wrapper.calls += 1
            # print(f"called {func.__qualname__} {wrapper.calls} time(s)")
            return func(*args, **kwargs)
        wrapper.calls = 0
        return wrapper

    @staticmethod
    def step_backward_decorator(func):
        print(f" Decorating method: {func.__qualname__}")
        @wraps(func)
        def wrapper(*args, **kwargs):
            wrapper.calls += 1
            # print(f"called {func.__qualname__} {wrapper.calls} time(s)")
            return func(*args, **kwargs)
        wrapper.calls = 0
        return wrapper



class AbstractValve(ABC, metaclass=MetaValve):

    @abstractmethod
    def acquire(self):
        """Acquire the valve for use."""
        pass

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

    def return_to_start(self):
        """Return the valve to the starting position."""
        # jank but we don't know yet how to reset this call value
        forward_steps = self.step_forward.calls
        backward_steps = self.step_backward.calls
        print(f"returning to start with forward and backwared steps: {forward_steps}, {backward_steps}")
        steps_to_move = abs(forward_steps - backward_steps)

        if forward_steps > backward_steps:
            for i in range(steps_to_move):
                self.step_backward()
                time.sleep(0.5)
        else:
            for i in range(steps_to_move):
                self.step_forward()
                time.sleep(0.5)


class MockValve(AbstractValve):
    """A mock implementation of the Valve class for testing purposes."""

    def __init__(self):
        super().__init__()
        self.position = 0  # Track the current position of the valve

    def acquire(self):
        print("[Mock] Valve acquired.")

    def release(self):
        print("[Mock] Valve released.")

    def step_forward(self):
        self.position += 1
        print(f"[Mock] Stepped forward to position {self.position}.")

    def step_backward(self):
        self.position -= 1
        print(f"[Mock] Stepped backward to position {self.position}.")