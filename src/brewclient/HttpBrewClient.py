from brew_client import AbstractBrewClient

import requests

class HttpBrewClient(AbstractBrewClient):
    """
    Client for controlling a brew valve via HTTP requests.
    Once a brew is initiated, the server will begin polling the scale and writing that data to influxdb
    From the clients perspective, prefer to use server endpoints rather than underlying queries if possible
    """

    def __init__(self, brewer_url: str):
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
            print(response.json())
            self._brew_id = brew_id
            return brew_id
        else:
            print(response.json())
            print("Failed to acquire valve")
            raise RuntimeError("Failed to acquire valve")

    def release(self):
        """Release the valve (finish a brew) for exclusive use."""
        response = requests.post(f"{self.brewer_url}/brew/release", params={"brew_id": self._brew_id})
        if response.status_code == 200:
            print("Released valve")
        else:
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
        pass

    def __enter__(self):
        """Context manager entry: acquire the brew, involves a request to create acquire new brew_id."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit: release the brew."""
        self.release()