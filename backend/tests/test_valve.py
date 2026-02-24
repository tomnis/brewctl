"""
Unit tests for valve module.
Tests the MockValve and AbstractValve classes.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path so we can import brewctl
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewctl.valve import AbstractValve, MockValve


class TestMockValve:
    """Tests for the MockValve class."""

    def test_mock_valve_initial_position(self):
        """Test that MockValve starts at position 0."""
        valve = MockValve()
        assert valve.position == 0

    def test_step_forward_increments_position(self):
        """Test that step_forward increments the position."""
        valve = MockValve()
        
        valve.step_forward()
        assert valve.position == 1
        
        valve.step_forward()
        assert valve.position == 2

    def test_step_backward_decrements_position(self):
        """Test that step_backward decrements the position."""
        valve = MockValve()
        
        # Move forward first
        valve.step_forward()
        valve.step_forward()
        assert valve.position == 2
        
        # Then move backward
        valve.step_backward()
        assert valve.position == 1

    def test_step_backward_can_go_negative(self):
        """Test that step_backward can go below zero."""
        valve = MockValve()
        
        valve.step_backward()
        assert valve.position == -1
        
        valve.step_backward()
        assert valve.position == -2

    def test_return_to_start_resets_position(self):
        """Test that return_to_start resets position to 0."""
        valve = MockValve()
        
        # Move to a non-zero position
        valve.step_forward()
        valve.step_forward()
        valve.step_forward()
        assert valve.position == 3
        
        # Return to start
        valve.return_to_start()
        assert valve.position == 0

    def test_release_logs_message(self):
        """Test that release logs a message (no exception)."""
        valve = MockValve()
        
        # Should not raise any exception
        valve.release()

    def test_multiple_operations_sequence(self):
        """Test a sequence of operations."""
        valve = MockValve()
        
        # Start at 0
        assert valve.position == 0
        
        # Forward twice
        valve.step_forward()
        valve.step_forward()
        assert valve.position == 2
        
        # Backward once
        valve.step_backward()
        assert valve.position == 1
        
        # Return to start
        valve.return_to_start()
        assert valve.position == 0
        
        # Forward three times
        valve.step_forward()
        valve.step_forward()
        valve.step_forward()
        assert valve.position == 3


class TestAbstractValve:
    """Tests for the AbstractValve class (interface tests)."""

    def test_mock_valve_is_subclass_of_abstract_valve(self):
        """Test that MockValve is a subclass of AbstractValve."""
        assert issubclass(MockValve, AbstractValve)

    def test_abstract_valve_cannot_be_instantiated(self):
        """Test that AbstractValve cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractValve()

    def test_abstract_valve_has_abstract_methods(self):
        """Test that AbstractValve has the expected abstract methods."""
        # These methods should exist on AbstractValve
        assert hasattr(AbstractValve, 'release')
        assert hasattr(AbstractValve, 'step_forward')
        assert hasattr(AbstractValve, 'step_backward')
        assert hasattr(AbstractValve, 'return_to_start')
