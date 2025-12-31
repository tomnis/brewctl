from abc import ABC, abstractmethod


class TimeSeries(ABC):

    @abstractmethod
    def get_current_weight(self) -> float:
        """Get the current weight from the time series."""
        pass

    @abstractmethod
    def get_current_flow_rate(self) -> float:
        """Get the current flow rate from the time series."""
        pass


