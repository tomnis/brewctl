from abc import ABC, abstractmethod

class AbstractTimeSeries(ABC):

    @abstractmethod
    def write_scale_data(self, weight: float, battery_pct: int) -> None:
        """Write the current weight to the time series."""
        pass

    @abstractmethod
    def get_current_weight(self) -> float:
        """Get the current weight from the time series."""
        pass

    @abstractmethod
    def get_current_flow_rate(self) -> float:
        """Get the current flow rate from the time series."""
        pass