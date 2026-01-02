from abc import ABC, abstractmethod

from config import *
from typing import Tuple
from model import *

class AbstractBrewStrategy(ABC):
    """encapsulates a brewing strategy for controlling the brew process. assumes that lock strategy has already been handled"""

    @abstractmethod
    def step(self, flow_rate: float) -> Tuple[BrewStatusRecord, int]:
        """Perform a single step in the brewing strategy. """
        pass


class DefaultBrewStrategy(AbstractBrewStrategy):
    """A simple default brewing strategy, naively opening or closing the valve based on the current flow rate."""

    def __init__(self, target_flow_rate=COLDBREW_TARGET_FLOW_RATE, scale_interval=COLDBREW_SCALE_READ_INTERVAL, valve_interval=COLDBREW_VALVE_INTERVAL_SECONDS, epsilon=COLDBREW_EPSILON):
        self.target_flow_rate = target_flow_rate
        self.scale_interval = scale_interval
        self.valve_interval = valve_interval
        self.epsilon = epsilon

    @classmethod
    def from_request(cls, req: StartBrewRequest) -> AbstractBrewStrategy:
        return DefaultBrewStrategy(target_flow_rate=req.target_flow_rate,
                                   scale_interval=req.scale_interval,
                                   valve_interval=req.valve_interval,
                                   epsilon=req.epsilon)

    def step(self, current_flow_rate: float) -> Tuple[ValveCommand, int]:
        """Perform a single step in the default brewing strategy."""
        # return valve command, and sleep time
        msg = f"current flow rate: {current_flow_rate:.4f}g/s"
        if current_flow_rate is None:
            logger.info("result is none")
            return ValveCommand.NOOP, self.valve_interval
        elif abs(self.target_flow_rate - current_flow_rate) <= self.epsilon:
            logger.info(f"{msg} (just right)")
            return ValveCommand.NOOP, self.valve_interval * 2
        # TODO should consider microadjustments here
        elif current_flow_rate <= self.target_flow_rate:
            logger.info(f"{msg} (too slow)")
            return ValveCommand.FORWARD, self.valve_interval
        else:
            logger.info(f"{msg} (too fast)")
            return ValveCommand.BACKWARD, self.valve_interval