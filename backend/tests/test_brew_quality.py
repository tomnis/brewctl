"""
Tests for brew quality scoring module.
"""
import pytest
from datetime import datetime, timedelta
from brewserver.brew_quality import (
    calculate_flow_rate_errors,
    calculate_flow_rate_stability,
    calculate_completeness,
    calculate_efficiency,
    compute_quality_score,
    get_score_grade,
    format_quality_report,
    BrewQualityMetrics,
)


class TestCalculateFlowRateErrors:
    """Tests for calculate_flow_rate_errors function."""
    
    def test_empty_flow_rates(self):
        errors, mae, rmse, max_error = calculate_flow_rate_errors([], 0.05)
        assert errors == []
        assert mae == 0.0
        assert rmse == 0.0
        assert max_error == 0.0
    
    def test_perfect_flow_rates(self):
        """Flow rates exactly at target should have zero error."""
        flow_rates = [0.05, 0.05, 0.05, 0.05, 0.05]
        errors, mae, rmse, max_error = calculate_flow_rate_errors(flow_rates, 0.05)
        assert mae == 0.0
        assert rmse == 0.0
        assert max_error == 0.0
    
    def test_some_deviation(self):
        """Flow rates with some deviation."""
        flow_rates = [0.05, 0.06, 0.05, 0.04, 0.05]
        target = 0.05
        errors, mae, rmse, max_error = calculate_flow_rate_errors(flow_rates, target)
        # Errors: [0, 0.01, 0, 0.01, 0]
        assert mae == pytest.approx(0.004, rel=0.01)
        assert max_error == pytest.approx(0.01, rel=0.01)
    
    def test_high_deviation(self):
        """Flow rates with high deviation."""
        flow_rates = [0.05, 0.10, 0.05, 0.00, 0.05]
        target = 0.05
        errors, mae, rmse, max_error = calculate_flow_rate_errors(flow_rates, target)
        # Errors: [0, 0.05, 0, 0.05, 0]
        assert mae == pytest.approx(0.02, rel=0.01)
        assert max_error == pytest.approx(0.05, rel=0.01)


class TestCalculateFlowRateStability:
    """Tests for calculate_flow_rate_stability function."""
    
    def test_empty_flow_rates(self):
        std_dev, within_epsilon = calculate_flow_rate_stability([])
        assert std_dev == 0.0
        assert within_epsilon == 0.0
    
    def test_single_reading(self):
        """Single reading should have 100% stability."""
        std_dev, within_epsilon = calculate_flow_rate_stability([0.05])
        assert std_dev == 0.0
        assert within_epsilon == 100.0
    
    def test_stable_flow_rates(self):
        """Stable flow rates should have low std dev."""
        flow_rates = [0.05, 0.051, 0.049, 0.05, 0.05]
        std_dev, within_epsilon = calculate_flow_rate_stability(flow_rates, epsilon=0.008)
        assert std_dev < 0.01
    
    def test_unstable_flow_rates(self):
        """Unstable flow rates should have high std dev."""
        flow_rates = [0.05, 0.10, 0.05, 0.00, 0.05]
        std_dev, within_epsilon = calculate_flow_rate_stability(flow_rates, epsilon=0.008)
        assert std_dev > 0.02


class TestCalculateCompleteness:
    """Tests for calculate_completeness function."""
    
    def test_exact_match(self):
        pct = calculate_completeness(1000, 1000)
        assert pct == pytest.approx(100.0, rel=0.01)
    
    def test_under_target(self):
        pct = calculate_completeness(900, 1000)
        assert pct == pytest.approx(90.0, rel=0.01)
    
    def test_over_target(self):
        pct = calculate_completeness(1100, 1000)
        assert pct == pytest.approx(110.0, rel=0.01)
    
    def test_zero_target(self):
        pct = calculate_completeness(100, 0)
        assert pct == 0.0


class TestCalculateEfficiency:
    """Tests for calculate_efficiency function."""
    
    def test_exact_match(self):
        """Brew that takes exactly expected time."""
        expected, ratio = calculate_efficiency(
            target_weight=1000,  # 1kg coffee
            target_flow_rate=0.05,  # 0.05 g/s = 50g per 1000s
            actual_duration_seconds=20000  # 20000s = 1000g / 0.05g/s
        )
        assert expected == pytest.approx(20000, rel=0.01)
        assert ratio == pytest.approx(1.0, rel=0.01)
    
    def test_fast_brew(self):
        """Brew that finishes faster than expected."""
        expected, ratio = calculate_efficiency(
            target_weight=1000,
            target_flow_rate=0.05,
            actual_duration_seconds=15000  # faster than 20000s
        )
        assert ratio == pytest.approx(0.75, rel=0.01)
    
    def test_slow_brew(self):
        """Brew that takes longer than expected."""
        expected, ratio = calculate_efficiency(
            target_weight=1000,
            target_flow_rate=0.05,
            actual_duration_seconds=30000  # slower than 20000s
        )
        assert ratio == pytest.approx(1.5, rel=0.01)
    
    def test_zero_flow_rate(self):
        expected, ratio = calculate_efficiency(1000, 0, 100)
        assert expected == 0.0
        assert ratio == 0.0


class TestComputeQualityScore:
    """Tests for compute_quality_score function."""
    
    def test_perfect_brew(self):
        """A perfect brew with flow rate exactly at target."""
        # 200 seconds of flow at exactly 0.05 g/s = 10g of coffee (tiny test brew)
        flow_rates = [0.05] * 100
        start = datetime.now()
        end = start + timedelta(seconds=200)
        
        metrics = compute_quality_score(
            flow_rates=flow_rates,
            target_flow_rate=0.05,
            epsilon=0.008,
            target_weight=239,  # 229 vessel + 10g coffee
            vessel_weight=229,
            actual_weight=239,
            time_started=start,
            time_completed=end
        )
        
        assert metrics.mean_absolute_error == pytest.approx(0.0, abs=0.001)
        assert metrics.overall_score == pytest.approx(100.0, abs=1.0)
    
    def test_poor_brew(self):
        """A poor brew with high flow rate deviation."""
        # Alternating between 0 and 0.1 g/s - very unstable
        flow_rates = [0.0, 0.1] * 50
        start = datetime.now()
        end = start + timedelta(seconds=200)
        
        metrics = compute_quality_score(
            flow_rates=flow_rates,
            target_flow_rate=0.05,
            epsilon=0.008,
            target_weight=239,
            vessel_weight=229,
            actual_weight=239,
            time_started=start,
            time_completed=end
        )
        
        # Should have high error and low score
        assert metrics.mean_absolute_error > 0.03
        assert metrics.overall_score < 70
    
    def test_incomplete_brew(self):
        """A brew that didn't reach target weight."""
        flow_rates = [0.05] * 100
        start = datetime.now()
        end = start + timedelta(seconds=200)
        
        metrics = compute_quality_score(
            flow_rates=flow_rates,
            target_flow_rate=0.05,
            epsilon=0.008,
            target_weight=1337,
            vessel_weight=229,
            actual_weight=1000,  # Only got 1000g instead of 1337g
            time_started=start,
            time_completed=end
        )
        
        # Should be penalized for incompleteness
        assert metrics.weight_achieved_pct == pytest.approx(74.8, rel=0.1)


class TestGetScoreGrade:
    """Tests for get_score_grade function."""
    
    def test_grade_boundaries(self):
        assert get_score_grade(100) == "A+"
        assert get_score_grade(95) == "A+"
        assert get_score_grade(94) == "A"
        assert get_score_grade(90) == "A"
        assert get_score_grade(89) == "B+"
        assert get_score_grade(85) == "B+"
        assert get_score_grade(84) == "B"
        assert get_score_grade(80) == "B"
        assert get_score_grade(79) == "C+"
        assert get_score_grade(75) == "C+"
        assert get_score_grade(74) == "C"
        assert get_score_grade(70) == "C"
        assert get_score_grade(69) == "D"
        assert get_score_grade(60) == "D"
        assert get_score_grade(59) == "F"
        assert get_score_grade(0) == "F"


class TestFormatQualityReport:
    """Tests for format_quality_report function."""
    
    def test_report_format(self):
        """Test that report is formatted correctly."""
        metrics = BrewQualityMetrics(
            mean_absolute_error=0.01,
            root_mean_square_error=0.015,
            max_error=0.03,
            flow_rate_std_dev=0.005,
            time_within_epsilon_pct=75.0,
            target_weight=1337,
            actual_weight=1300,
            weight_achieved_pct=97.2,
            expected_duration_seconds=22160,
            actual_duration_seconds=23000,
            efficiency_ratio=1.04,
            overall_score=85.5
        )
        
        report = format_quality_report(metrics)
        
        assert "85.5" in report
        assert "B+" in report
        assert "1337" in report
        assert "1300" in report
