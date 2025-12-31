
from ..base.valve import Valve
import requests

class HttpValve(Valve):

    def __init__(self, brewer_url: str):
        self.brewer_url = brewer_url
        self._brew_id = None


    def acquire(self) -> str:
        """Acquire the valve for exclusive use."""
        response = requests.post(f"{self.brewer_url}/valve/acquire")
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
        """Release the valve for exclusive use."""
        response = requests.post(f"{self.brewer_url}/valve/release", params={"brew_id": self._brew_id})
        if response.status_code == 200:
            print("Released valve")
        else:
            print("Failed to release valve")

    def step_forward(self):
        """Open the valve one step."""
        response = requests.post(f"{self.brewer_url}/valve/forward/1", params={"brew_id": self._brew_id})
        if response.status_code == 200:
            print("Stepped valve forward")
        else:
            print(response)
            print(response.json())
            print("Failed to step valve forward")

    def step_backward(self):
        """Open the valve one step."""
        response = requests.post(f"{self.brewer_url}/valve/backward/1", params={"brew_id": self._brew_id})
        if response.status_code == 200:
            print("Stepped valve backward")
        else:
            print(response)
            print(response.json())
            print("Failed to step valve backward")

    def return_to_start(self):
        pass

    def __enter__(self):
        # Initialize any resources if needed
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Clean up resources if needed
        self.release()