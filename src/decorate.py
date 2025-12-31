from abc import ABC, abstractmethod, ABCMeta
from functools import wraps


# A metaclass modifies the class-creation behavior not the instance creation behavior
class Meta(ABCMeta):
    # def __new__(cls, name, bases, dct):
    #     x = super().__new__(cls, name, bases, dct)
    #     x.attr = 100
    #     return x

    def __new__(cls, name, bases, attrs):
        """Metaclass for tasks."""
        for attr_name, attr_value in attrs.items():
            if attr_name == "forward" and callable(attr_value):
                attrs[attr_name] = cls.forward_decorator(attr_value)
            elif attr_name == "backward" and callable(attr_value):
                attrs[attr_name] = cls.backward_decorator(attr_value)
        x = super().__new__(cls, name, bases, attrs)
        x._breadcrumbs = dict()
        return x

    @staticmethod
    def forward_decorator(func):
        print(f" Decorating method: {func.__qualname__}")
        @wraps(func)
        def wrapper(*args, **kwargs):
            wrapper.calls += 1
            print(f"called {func.__qualname__} {wrapper.calls} time(s)")
            return func(*args, **kwargs)
        wrapper.calls = 0
        return wrapper

    @staticmethod
    def backward_decorator(func):
        print(f" Decorating method: {func.__qualname__}")
        @wraps(func)
        def wrapper(*args, **kwargs):
            wrapper.calls += 1
            print(f"called {func.__qualname__} {wrapper.calls} time(s)")
            return func(*args, **kwargs)
        wrapper.calls = 0
        return wrapper





class AbstractDecor(ABC, metaclass=Meta):

    def __init__(self):
        print(f"in AbstractDecor init, breadcrumbs: {self._breadcrumbs}")
        pass

    @abstractmethod
    def forward(self):
        pass

    @abstractmethod
    def backward(self):
        pass

    def return_to_start(self):
        print(f"Returning to start with forwardSteps: {self.forward.calls}")
        print(f"Returning to start with backwardSteps: {self.backward.calls}")
        pass


    def reset(self):
        # self.forward.calls = self.forward.calls - 1
        pass


class ConcreteDecorated(AbstractDecor):

    def __init__(self):
        super().__init__()

    def forward(self):
        pass

    def backward(self):
        pass

def main():
    decorator = ConcreteDecorated()
    # print(decorator.attr)
    decorator.forward()
    decorator.forward()
    print(decorator.forward.calls)
    print(decorator._breadcrumbs)
    decorator.reset()
    print(decorator.forward.calls)
    print(decorator._breadcrumbs)

    decorator.return_to_start()

if __name__ == "__main__":
    main()