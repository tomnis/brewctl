import time
from abc import ABC, abstractmethod

from brewserver.brew_strategy import AbstractBrewStrategy
from brewserver.model import ValveCommand

class AbstractBrewClient(ABC):
    """An abstract base class representing a brew client.
    Defines the interface for brew client implementations.

    A brew client can be used in a resource-semantic way since we defined enter() and exit() methods.
    A brew client can be used with low-level operations, or can use the entire end to end do_brew() method.
    A brew client has a brew strategy that describes what the brew behavior should be for a single iteration of the loop.
    """

    def __init__(self, brew_strategy: AbstractBrewStrategy):
        self.brew_strategy = brew_strategy

    @abstractmethod
    def acquire(self):
        """Start a brewing process with the given recipe."""
        pass

    @abstractmethod
    def release(self):
        """Stop the current brewing process."""
        pass

    @abstractmethod
    def get_current_flow_rate(self) -> float:
        """Get the current flow rate from the server."""
        pass

    @abstractmethod
    def step_forward(self):
        """Move the valve controller one step forward."""
        pass

    @abstractmethod
    def step_backward(self):
        """Move the valve controller one step backward."""
        pass

    @abstractmethod
    def return_to_start(self):
        """Return the valve to the starting position."""
        pass

    def __enter__(self):
        """Context manager entry: acquire the brew, involves a request to create acquire new brew_id."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit: release the brew."""
        self.release()

    def do_brew(self):
        """High-level full end-to-end brew cycle"""
        while True:
            current_flow_rate = self.get_current_flow_rate()
            (valve_command, interval) = self.brew_strategy.step(current_flow_rate)
            if valve_command == ValveCommand.FORWARD:
                self.step_forward()
            elif valve_command == ValveCommand.BACKWARD:
                self.step_backward()

            time.sleep(interval)


import requests

class HttpBrewClient(AbstractBrewClient):
    """
    Client for controlling a brew valve via HTTP requests.
    Once a brew is initiated, the server will begin polling the scale and writing that data to influxdb
    From the clients perspective, prefer to use server endpoints rather than underlying queries if possible
    """

    def __init__(self, brew_strategy: AbstractBrewStrategy, brewer_url: str):
        super().__init__(brew_strategy)
        self.brewer_url = brewer_url
        self._brew_id = None

    def get_current_flow_rate(self) -> float:
        """Get the current flow rate from the server."""
        response = requests.get(f"{self.brewer_url}/brew/flow_rate")
        if response.status_code == 200:
            flow_rate = response.json().get("flow_rate")
            return flow_rate
        else:
            print("Failed to retrieve current flow rate")
            raise RuntimeError("Failed to retrieve current flow rate")

    def acquire(self) -> str:
        """Acquire the valve (start a brew) for exclusive use."""
        response = requests.post(f"{self.brewer_url}/brew/acquire")
        if response.status_code == 200:
            brew_id = response.json().get("brew_id")
            # print(response.json())
            self._brew_id = brew_id
            return brew_id
        else:
            print(response.json())
            print(f"Failed to acquire valve: {response.json()}")
            raise RuntimeError("Failed to acquire valve")

    def release(self):
        """Release the valve (finish a brew) for exclusive use."""
        response = requests.post(f"{self.brewer_url}/brew/release", params={"brew_id": self._brew_id})
        if response.status_code == 200:
            print(f"Released valve for brew_id {self._brew_id}")
        else:
            print(response.json())
            print("Failed to release valve")

    def step_forward(self):
        """Move the valve controller one step forward."""
        response = requests.post(f"{self.brewer_url}/brew/valve/forward", params={"brew_id": self._brew_id})
        if response.status_code == 200:
            print("Stepped valve forward")
        else:
            print(response)
            print(response.json())
            print("Failed to step valve forward")

    def step_backward(self):
        """Move the valve controller one step backward."""
        response = requests.post(f"{self.brewer_url}/brew/valve/backward", params={"brew_id": self._brew_id})
        if response.status_code == 200:
            print("Stepped valve backward")
        else:
            print(response)
            print(response.json())
            print("Failed to step valve backward")

    def return_to_start(self):
        # TODO should implememnt this, but need to monitor and check the torque, it seems we don't have enough torque to fully return to initial position
        pass