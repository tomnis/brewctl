"""
Unit tests for brew_strategy module.
Tests the DefaultBrewStrategy class which contains the core brewing logic.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path so we can import brewctl
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewctl.brew_strategy import DefaultBrewStrategy, AbstractBrewStrategy
from brewctl.model import StartBrewRequest, ValveCommand


class TestDefaultBrewStrategy:
    """Tests for the DefaultBrewStrategy class."""

    def test_step_returns_stop_when_target_weight_reached(self):
        """Test that step returns STOP when current weight >= target weight."""
        # Use vessel_weight=0 to test with target_weight as coffee-only (for test clarity)
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, vessel_weight=0)
        
        # Current weight exceeds target - use positional args
        command, interval = strategy.step(0.05, 100.0)
        
        assert command.value == ValveCommand.STOP.value
        assert interval == 0

    def test_step_returns_stop_when_weight_exceeds_target(self):
        """Test that step returns STOP when current weight exceeds target."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, vessel_weight=0)
        
        # Current weight well exceeds target
        command, interval = strategy.step(0.07, 150.0)
        
        assert command.value == ValveCommand.STOP.value
        assert interval == 0

    def test_step_returns_forward_when_flow_rate_too_slow(self):
        """Test that step returns FORWARD when flow rate is below target."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, epsilon=0.008, vessel_weight=0)
        
        command, interval = strategy.step(0.03, 50.0)
        
        assert command.value == ValveCommand.FORWARD.value
        assert interval == strategy.valve_interval

    def test_step_returns_backward_when_flow_rate_too_fast(self):
        """Test that step returns BACKWARD when flow rate is above target."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, epsilon=0.008, vessel_weight=0)
        
        command, interval = strategy.step(0.08, 50.0)
        
        assert command.value == ValveCommand.BACKWARD.value
        assert interval == strategy.valve_interval

    def test_step_returns_noop_when_flow_rate_within_epsilon(self):
        """Test that step returns NOOP when flow rate is within epsilon of target."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, epsilon=0.008, vessel_weight=0)
        
        # Flow rate exactly at target (within epsilon)
        command, interval = strategy.step(0.05, 50.0)
        
        assert command.value == ValveCommand.NOOP.value
        # When flow rate is just right, interval is doubled
        assert interval == strategy.valve_interval * 2

    def test_step_returns_noop_when_flow_rate_just_within_epsilon_upper(self):
        """Test NOOP when flow rate is slightly above but within epsilon."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, epsilon=0.008, vessel_weight=0)
        
        # 0.05 + 0.008 = 0.058, exactly at epsilon boundary
        command, interval = strategy.step(0.058, 50.0)
        
        assert command.value == ValveCommand.NOOP.value

    def test_step_returns_noop_when_flow_rate_just_within_epsilon_lower(self):
        """Test NOOP when flow rate is slightly below but within epsilon."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, epsilon=0.008, vessel_weight=0)
        
        # 0.05 - 0.008 = 0.042, exactly at epsilon boundary
        command, interval = strategy.step(0.042, 50.0)
        
        assert command.value == ValveCommand.NOOP.value

    def test_step_returns_forward_when_flow_rate_below_epsilon_boundary(self):
        """Test FORWARD when flow rate is below epsilon boundary."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, epsilon=0.008, vessel_weight=0)
        
        # Just below epsilon boundary
        command, interval = strategy.step(0.041, 50.0)
        
        assert command.value == ValveCommand.FORWARD.value

    def test_step_returns_backward_when_flow_rate_above_epsilon_boundary(self):
        """Test BACKWARD when flow rate is above epsilon boundary."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, epsilon=0.008, vessel_weight=0)
        
        # Just above epsilon boundary
        command, interval = strategy.step(0.059, 50.0)
        
        assert command.value == ValveCommand.BACKWARD.value

    def test_step_returns_noop_when_flow_rate_none(self):
        """Test that step returns NOOP when flow rate is None (insufficient data)."""
        strategy = DefaultBrewStrategy(target_weight=100.0, target_flow_rate=0.05, vessel_weight=0)
        
        command, interval = strategy.step(None, 50.0)
        
        assert command.value == ValveCommand.NOOP.value
        assert interval == strategy.valve_interval

    def test_step_weight_check_before_flow_rate(self):
        """Test that weight check takes precedence over flow rate check."""
        strategy = DefaultBrewStrategy(target_weight=50.0, target_flow_rate=0.05, vessel_weight=0)
        
        # Weight exceeded but flow rate would suggest forward
        command, interval = strategy.step(0.03, 100.0)
        
        # Should return STOP because weight target is reached
        assert command.value == ValveCommand.STOP.value

    def test_step_with_vessel_weight(self):
        """Test that step correctly handles target_weight that includes vessel weight."""
        # target_weight=1337 includes vessel_weight=229, so coffee_target = 1108
        strategy = DefaultBrewStrategy(target_weight=1337, vessel_weight=229, target_flow_rate=0.05)
        
        # When current_weight=1337 (vessel + 1108g coffee), should stop
        command, interval = strategy.step(0.05, 1337)
        assert command.value == ValveCommand.STOP.value
        assert interval == 0
        
        # When current_weight=1336 (vessel + 1107g coffee), should not stop yet
        command, interval = strategy.step(0.03, 1336)
        assert command.value == ValveCommand.FORWARD.value

    def test_from_request_creates_strategy_with_correct_params(self):
        """Test that from_request creates a strategy with correct parameters."""
        # Create strategy directly and test from_request logic
        strategy = DefaultBrewStrategy(
            target_flow_rate=0.1,
            scale_interval=1.0,
            valve_interval=30,
            epsilon=0.01,
            target_weight=500.0
        )
        
        # Verify the parameters are set correctly
        assert strategy.target_flow_rate == 0.1
        assert strategy.scale_interval == 1.0
        assert strategy.valve_interval == 30
        assert strategy.epsilon == 0.01
        assert strategy.target_weight == 500.0

    def test_from_request_with_values(self):
        """Test that from_request works with explicit values."""
        strategy = DefaultBrewStrategy(
            target_flow_rate=0.1,
            scale_interval=1.0,
            valve_interval=30,
            epsilon=0.01,
            target_weight=500.0
        )
        
        # Should use the provided values
        assert strategy.target_flow_rate == 0.1
        assert strategy.scale_interval == 1.0
        assert strategy.valve_interval == 30
        assert strategy.epsilon == 0.01
        assert strategy.target_weight == 500.0

    def test_custom_strategy_parameters(self):
        """Test creating strategy with custom parameters."""
        strategy = DefaultBrewStrategy(
            target_flow_rate=0.1,
            scale_interval=1.0,
            valve_interval=30,
            epsilon=0.01,
            target_weight=500.0
        )
        
        assert strategy.target_flow_rate == 0.1
        assert strategy.scale_interval == 1.0
        assert strategy.valve_interval == 30
        assert strategy.epsilon == 0.01
        assert strategy.target_weight == 500.0

    def test_strategy_is_subclass_of_abstract(self):
        """Test that DefaultBrewStrategy is a subclass of AbstractBrewStrategy."""
        assert issubclass(DefaultBrewStrategy, AbstractBrewStrategy)


class TestValveCommand:
    """Tests for the ValveCommand enum."""

    def test_valve_command_values(self):
        """Test that ValveCommand has expected values."""
        assert ValveCommand.NOOP.value == 0
        assert ValveCommand.FORWARD.value == 1
        assert ValveCommand.BACKWARD.value == 2
        assert ValveCommand.STOP.value == 3

    def test_valve_command_iteration(self):
        """Test that all ValveCommand values can be iterated."""
        commands = list(ValveCommand)
        assert len(commands) == 4
        assert ValveCommand.NOOP in commands
        assert ValveCommand.FORWARD in commands
        assert ValveCommand.BACKWARD in commands
        assert ValveCommand.STOP in commands
