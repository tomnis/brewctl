"""
Unit tests for the brew strategy registry and factory function.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewserver.brew_strategy import (
    create_brew_strategy,
    BREW_STRATEGY_REGISTRY,
    DefaultBrewStrategy,
    PIDBrewStrategy,
    MPCBrewStrategy,
    AdaptiveGainSchedulingBrewStrategy,
    KalmanPIDBrewStrategy,
    SmithPredictorAdvancedBrewStrategy,
    AbstractBrewStrategy,
)
from brewserver.model import BrewStrategyType


BASE_PARAMS = {
    "target_flow_rate": 0.05,
    "scale_interval": 0.5,
    "valve_interval": 90,
    "target_weight": 1337,
    "vessel_weight": 229,
    "epsilon": 0.008,
}


class TestBrewStrategyRegistry:
    """Tests for the strategy registry."""

    def test_all_strategy_types_registered(self):
        """Test that all BrewStrategyType values are registered."""
        for strategy_type in BrewStrategyType:
            assert strategy_type in BREW_STRATEGY_REGISTRY, f"{strategy_type} not registered"

    def test_registry_maps_to_correct_classes(self):
        """Test that registry maps types to correct strategy classes."""
        assert BREW_STRATEGY_REGISTRY[BrewStrategyType.DEFAULT] is DefaultBrewStrategy
        assert BREW_STRATEGY_REGISTRY[BrewStrategyType.PID] is PIDBrewStrategy
        assert BREW_STRATEGY_REGISTRY[BrewStrategyType.MPC] is MPCBrewStrategy
        assert BREW_STRATEGY_REGISTRY[BrewStrategyType.ADAPTIVE_GAIN_SCHEDULING] is AdaptiveGainSchedulingBrewStrategy
        assert BREW_STRATEGY_REGISTRY[BrewStrategyType.KALMAN_PID] is KalmanPIDBrewStrategy
        assert BREW_STRATEGY_REGISTRY[BrewStrategyType.SMITH_PREDICTOR_ADVANCED] is SmithPredictorAdvancedBrewStrategy

    def test_all_registered_classes_are_abstract_subclasses(self):
        """Test that all registered classes are subclasses of AbstractBrewStrategy."""
        for strategy_type, cls in BREW_STRATEGY_REGISTRY.items():
            assert issubclass(cls, AbstractBrewStrategy), f"{cls} is not a subclass of AbstractBrewStrategy"


class TestCreateBrewStrategy:
    """Tests for the create_brew_strategy factory function."""

    def test_create_default_strategy(self):
        """Test creating a default strategy."""
        strategy = create_brew_strategy(BrewStrategyType.DEFAULT, {}, BASE_PARAMS)
        assert isinstance(strategy, DefaultBrewStrategy)
        assert strategy.target_flow_rate == 0.05

    def test_create_pid_strategy(self):
        """Test creating a PID strategy."""
        strategy = create_brew_strategy(BrewStrategyType.PID, {"kp": 2.0, "ki": 0.2, "kd": 0.1}, BASE_PARAMS)
        assert isinstance(strategy, PIDBrewStrategy)
        assert strategy.kp == 2.0
        assert strategy.ki == 0.2
        assert strategy.kd == 0.1

    def test_create_mpc_strategy(self):
        """Test creating an MPC strategy."""
        strategy = create_brew_strategy(BrewStrategyType.MPC, {"horizon": 20}, BASE_PARAMS)
        assert isinstance(strategy, MPCBrewStrategy)
        assert strategy.horizon == 20

    def test_create_kalman_pid_strategy(self):
        """Test creating a Kalman PID strategy."""
        strategy = create_brew_strategy(BrewStrategyType.KALMAN_PID, {"q": 0.01, "r": 0.5}, BASE_PARAMS)
        assert isinstance(strategy, KalmanPIDBrewStrategy)

    def test_create_adaptive_gain_scheduling_strategy(self):
        """Test creating an adaptive gain scheduling strategy."""
        strategy = create_brew_strategy(BrewStrategyType.ADAPTIVE_GAIN_SCHEDULING, {}, BASE_PARAMS)
        assert isinstance(strategy, AdaptiveGainSchedulingBrewStrategy)

    def test_create_smith_predictor_strategy(self):
        """Test creating a Smith Predictor strategy."""
        strategy = create_brew_strategy(BrewStrategyType.SMITH_PREDICTOR_ADVANCED, {}, BASE_PARAMS)
        assert isinstance(strategy, SmithPredictorAdvancedBrewStrategy)

    def test_create_unknown_strategy_raises_error(self):
        """Test that creating an unknown strategy type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy type"):
            create_brew_strategy("nonexistent", {}, BASE_PARAMS)

    def test_base_params_propagated(self):
        """Test that base params are correctly propagated to all strategies."""
        for strategy_type in BrewStrategyType:
            strategy = create_brew_strategy(strategy_type, {}, BASE_PARAMS)
            assert strategy.target_flow_rate == 0.05
            assert strategy.target_weight == 1337
            assert strategy.vessel_weight == 229

    def test_strategy_params_override_defaults(self):
        """Test that strategy-specific params override defaults."""
        strategy = create_brew_strategy(BrewStrategyType.PID, {"kp": 5.0}, BASE_PARAMS)
        assert strategy.kp == 5.0

    def test_empty_strategy_params_uses_defaults(self):
        """Test that empty strategy params use default values."""
        strategy = create_brew_strategy(BrewStrategyType.PID, {}, BASE_PARAMS)
        assert strategy.kp == 1.0  # default
        assert strategy.ki == 0.1  # default
        assert strategy.kd == 0.05  # default


class TestGetParamsSchema:
    """Tests for get_params_schema on each strategy."""

    def test_default_schema_is_empty(self):
        """Default strategy has no extra params."""
        assert DefaultBrewStrategy.get_params_schema() == {}

    def test_pid_schema_has_expected_keys(self):
        schema = PIDBrewStrategy.get_params_schema()
        assert "kp" in schema
        assert "ki" in schema
        assert "kd" in schema

    def test_mpc_schema_has_expected_keys(self):
        schema = MPCBrewStrategy.get_params_schema()
        assert "horizon" in schema
        assert "plant_gain" in schema

    def test_kalman_pid_schema_has_expected_keys(self):
        schema = KalmanPIDBrewStrategy.get_params_schema()
        assert "kp" in schema
        assert "q" in schema
        assert "r" in schema

    def test_adaptive_gain_schema_has_expected_keys(self):
        schema = AdaptiveGainSchedulingBrewStrategy.get_params_schema()
        assert "kp_low" in schema
        assert "kp_med" in schema
        assert "kp_high" in schema
        assert "adaptation_enabled" in schema

    def test_smith_predictor_schema_has_expected_keys(self):
        schema = SmithPredictorAdvancedBrewStrategy.get_params_schema()
        assert "dead_time" in schema
        assert "plant_gain" in schema
        assert "q" in schema
        assert "r" in schema
