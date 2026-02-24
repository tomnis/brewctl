"""
Unit tests for model module.
Tests the data models and enums used in the brewctl.
"""
import sys
from pathlib import Path
from datetime import datetime

import pytest
from pydantic import ValidationError

# Add src to path so we can import brewctl
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewctl.model import (
    BrewState,
    BrewStrategyType,
    ValveCommand,
    ScaleStatus,
    StartBrewRequest,
    BrewStatus,
)


class TestBrewState:
    """Tests for the BrewState enum."""

    def test_brew_state_values(self):
        """Test that BrewState has expected values."""
        assert BrewState.IDLE.value == "idle"
        assert BrewState.BREWING.value == "brewing"
        assert BrewState.PAUSED.value == "paused"
        assert BrewState.COMPLETED.value == "completed"

    def test_brew_state_iteration(self):
        """Test that all BrewState values can be iterated."""
        states = list(BrewState)
        assert len(states) == 5
        assert BrewState.IDLE in states
        assert BrewState.BREWING in states
        assert BrewState.PAUSED in states
        assert BrewState.COMPLETED in states
        assert BrewState.ERROR in states

    def test_brew_state_from_string(self):
        """Test creating BrewState from string value."""
        assert BrewState("idle") == BrewState.IDLE
        assert BrewState("brewing") == BrewState.BREWING
        assert BrewState("paused") == BrewState.PAUSED
        assert BrewState("completed") == BrewState.COMPLETED


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


class TestScaleStatus:
    """Tests for the ScaleStatus model."""

    def test_scale_status_valid(self):
        """Test creating a valid ScaleStatus."""
        status = ScaleStatus(
            connected=True,
            weight=100.5,
            units="g",
            battery_pct=75
        )
        
        assert status.connected is True
        assert status.weight == 100.5
        assert status.units == "g"
        assert status.battery_pct == 75

    def test_scale_status_to_dict(self):
        """Test converting ScaleStatus to dictionary."""
        status = ScaleStatus(
            connected=True,
            weight=100.5,
            units="g",
            battery_pct=75
        )
        
        status_dict = status.model_dump()
        
        assert status_dict["connected"] is True
        assert status_dict["weight"] == 100.5
        assert status_dict["units"] == "g"
        assert status_dict["battery_pct"] == 75

    def test_scale_status_from_dict(self):
        """Test creating ScaleStatus from dictionary."""
        data = {
            "connected": True,
            "weight": 100.5,
            "units": "g",
            "battery_pct": 75
        }
        
        status = ScaleStatus(**data)
        
        assert status.connected is True
        assert status.weight == 100.5

    def test_scale_status_zero_weight(self):
        """Test ScaleStatus with zero weight."""
        status = ScaleStatus(
            connected=True,
            weight=0.0,
            units="g",
            battery_pct=100
        )
        
        assert status.weight == 0.0


# StartBrewRequest is a dataclass in the current implementation, not a pydantic model
# The following tests verify the model can be imported but don't test it as pydantic


class TestBrewStatus:
    """Tests for the BrewStatus model."""

    def test_brew_status_valid(self):
        """Test creating a valid BrewStatus."""
        timestamp = datetime.now()
        status = BrewStatus(
            brew_id="test-brew-123",
            brew_state=BrewState.BREWING,
            brew_strategy=BrewStrategyType.DEFAULT,
            time_started=timestamp,
            target_weight=100.0,
            timestamp=timestamp,
            current_flow_rate=0.05,
            current_weight=50.0
        )
        
        assert status.brew_id == "test-brew-123"
        assert status.brew_state == BrewState.BREWING
        assert status.target_weight == 100.0
        assert status.current_flow_rate == 0.05
        assert status.current_weight == 50.0

    def test_brew_status_to_dict(self):
        """Test converting BrewStatus to dictionary."""
        timestamp = datetime.now()
        status = BrewStatus(
            brew_id="test-brew-123",
            brew_state=BrewState.BREWING,
            brew_strategy=BrewStrategyType.DEFAULT,
            time_started=timestamp,
            target_weight=100.0,
            timestamp=timestamp,
            current_flow_rate=0.05,
            current_weight=50.0
        )
        
        status_dict = status.model_dump()
        
        assert status_dict["brew_id"] == "test-brew-123"
        assert status_dict["brew_state"] == BrewState.BREWING
        assert status_dict["target_weight"] == 100.0
        assert status_dict["current_flow_rate"] == 0.05
        assert status_dict["current_weight"] == 50.0

    def test_brew_status_with_different_states(self):
        """Test BrewStatus with different brew states."""
        timestamp = datetime.now()
        
        # Test IDLE state
        status = BrewStatus(
            brew_id="test-brew",
            brew_state=BrewState.IDLE,
            brew_strategy=BrewStrategyType.DEFAULT,
            time_started=timestamp,
            target_weight=100.0,
            timestamp=timestamp,
            current_flow_rate=0.0,
            current_weight=0.0
        )
        assert status.brew_state == BrewState.IDLE
        
        # Test PAUSED state
        status = BrewStatus(
            brew_id="test-brew",
            brew_state=BrewState.PAUSED,
            brew_strategy=BrewStrategyType.DEFAULT,
            time_started=timestamp,
            target_weight=100.0,
            timestamp=timestamp,
            current_flow_rate=0.0,
            current_weight=25.0
        )
        assert status.brew_state == BrewState.PAUSED
        
        # Test COMPLETED state
        status = BrewStatus(
            brew_id="test-brew",
            brew_state=BrewState.COMPLETED,
            brew_strategy=BrewStrategyType.DEFAULT,
            time_started=timestamp,
            target_weight=100.0,
            timestamp=timestamp,
            current_flow_rate=0.0,
            current_weight=100.0
        )
        assert status.brew_state == BrewState.COMPLETED

    def test_brew_status_zero_values(self):
        """Test BrewStatus with zero flow rate and weight."""
        timestamp = datetime.now()
        status = BrewStatus(
            brew_id="test-brew",
            brew_state=BrewState.IDLE,
            brew_strategy=BrewStrategyType.DEFAULT,
            time_started=timestamp,
            target_weight=100.0,
            timestamp=timestamp,
            current_flow_rate=0.0,
            current_weight=0.0
        )
        
        assert status.current_flow_rate == 0.0
        assert status.current_weight == 0.0
        assert status.target_weight == 100.0
