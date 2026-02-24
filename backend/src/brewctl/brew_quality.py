"""
Brew Quality Scoring Module

Provides functions to compute quality metrics for a completed brew based on
how well the flow rate adhered to the target throughout the brewing process.
"""

import math
from typing import List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

from log import logger


@dataclass
class BrewQualityMetrics:
    """Container for all quality metrics computed for a brew."""
    # Flow rate deviation metrics
    mean_absolute_error: float  # g/s
    root_mean_square_error: float  # g/s
    max_error: float  # g/s
    
    # Stability metrics
    flow_rate_std_dev: float  # g/s
    time_within_epsilon_pct: float  # 0-100%
    
    # Completeness metrics
    target_weight: float  # grams
    actual_weight: float  # grams
    weight_achieved_pct: float  # 0-100+
    
    # Timing metrics
    expected_duration_seconds: float
    actual_duration_seconds: float
    efficiency_ratio: float  # <1 = faster than expected, >1 = slower
    
    # Overall score
    overall_score: float  # 0-100


def calculate_flow_rate_errors(
    flow_rates: List[float], 
    target_flow_rate: float
) -> Tuple[List[float], float, float, float]:
    """
    Calculate error metrics for a list of flow rate readings.
    
    Args:
        flow_rates: List of flow rate readings in g/s
        target_flow_rate: The target flow rate in g/s
        
    Returns:
        Tuple of (errors, mean_absolute_error, rmse, max_error)
    """
    if not flow_rates:
        return [], 0.0, 0.0, 0.0
    
    errors = [abs(fr - target_flow_rate) for fr in flow_rates]
    
    mean_absolute_error = sum(errors) / len(errors)
    
    squared_errors = [e ** 2 for e in errors]
    rmse = math.sqrt(sum(squared_errors) / len(squared_errors))
    
    max_error = max(errors)
    
    return errors, mean_absolute_error, rmse, max_error


def calculate_flow_rate_stability(
    flow_rates: List[float], 
    epsilon: float = 0.008
) -> Tuple[float, float]:
    """
    Calculate stability metrics for flow rate readings.
    
    Args:
        flow_rates: List of flow rate readings in g/s
        epsilon: The acceptable deviation threshold (g/s)
        
    Returns:
        Tuple of (standard_deviation, time_within_epsilon_pct)
    """
    if not flow_rates:
        return 0.0, 0.0
    
    n = len(flow_rates)
    if n < 2:
        return 0.0, 100.0
    
    mean = sum(flow_rates) / n
    
    # Standard deviation
    variance = sum((fr - mean) ** 2 for fr in flow_rates) / (n - 1)  # sample std dev
    std_dev = math.sqrt(variance)
    
    # Percentage of readings within epsilon of target
    # We calculate this based on variance from the mean, not target
    # A reading is "stable" if it's close to the recent average
    readings_within_epsilon = sum(1 for fr in flow_rates if abs(fr - mean) <= epsilon)
    within_epsilon_pct = (readings_within_epsilon / n) * 100
    
    return std_dev, within_epsilon_pct


def calculate_completeness(
    actual_weight: float,
    target_weight: float
) -> float:
    """
    Calculate the percentage of target weight achieved.
    
    Args:
        actual_weight: The actual final weight achieved (grams)
        target_weight: The target weight (grams)
        
    Returns:
        Percentage of target achieved (can exceed 100%)
    """
    if target_weight <= 0:
        return 0.0
    return (actual_weight / target_weight) * 100


def calculate_efficiency(
    target_weight: float,
    target_flow_rate: float,
    actual_duration_seconds: float
) -> Tuple[float, float]:
    """
    Calculate brewing efficiency based on expected vs actual duration.
    
    Args:
        target_weight: Target coffee weight (grams, excluding vessel)
        target_flow_rate: Target flow rate (g/s)
        actual_duration_seconds: Actual time taken for brew
        
    Returns:
        Tuple of (expected_duration_seconds, efficiency_ratio)
    """
    coffee_weight = target_weight  # This is total weight including vessel in the model
    # Actually target_weight in the model includes vessel_weight
    # So we need to calculate coffee only
    
    # Expected: if we hit exactly target flow rate the whole time
    if target_flow_rate <= 0:
        return 0.0, 0.0
    
    expected_duration = coffee_weight / target_flow_rate
    
    if expected_duration <= 0:
        return 0.0, 0.0
    
    efficiency_ratio = actual_duration_seconds / expected_duration
    
    return expected_duration, efficiency_ratio


def compute_quality_score(
    flow_rates: List[float],
    target_flow_rate: float,
    epsilon: float,
    target_weight: float,
    vessel_weight: float,
    actual_weight: float,
    time_started: datetime,
    time_completed: datetime
) -> BrewQualityMetrics:
    """
    Compute comprehensive quality metrics for a brew.
    
    Args:
        flow_rates: List of flow rate readings during the brew (g/s)
        target_flow_rate: The target flow rate (g/s)
        epsilon: Acceptable deviation threshold (g/s)
        target_weight: Target total weight including vessel (grams)
        vessel_weight: Weight of empty vessel (grams)
        actual_weight: Actual final weight (grams)
        time_started: When the brew started
        time_completed: When the brew completed
        
    Returns:
        BrewQualityMetrics with all computed scores
    """
    # Calculate flow rate error metrics
    errors, mae, rmse, max_error = calculate_flow_rate_errors(flow_rates, target_flow_rate)
    
    # Calculate stability metrics
    std_dev, within_epsilon_pct = calculate_flow_rate_stability(flow_rates, epsilon)
    
    # Calculate completeness
    weight_pct = calculate_completeness(actual_weight, target_weight)
    
    # Calculate timing efficiency
    coffee_target = target_weight - vessel_weight
    expected_duration, efficiency_ratio = calculate_efficiency(
        coffee_target, target_flow_rate, 
        (time_completed - time_started).total_seconds()
    )
    
    # Calculate overall score (0-100)
    # Weights: 50% flow accuracy, 25% stability, 25% completeness
    
    # Flow score: penalize MAE. 0.01 g/s error = 90, 0.05 g/s = 50
    flow_score = max(0, min(100, 100 - (mae * 1000)))
    
    # Stability score: lower std dev = higher score
    # 0.001 g/s std dev = 100, 0.01 g/s = 50
    stability_score = max(0, min(100, 100 - (std_dev * 5000)))
    
    # Completeness score: actual / target, capped at 100 for scoring
    completeness_score = min(100, weight_pct)
    
    overall_score = (
        (flow_score * 0.70) +
        (stability_score * 0.25) +
        (completeness_score * 0.05)
    )
    
    actual_duration = (time_completed - time_started).total_seconds()
    
    return BrewQualityMetrics(
        mean_absolute_error=mae,
        root_mean_square_error=rmse,
        max_error=max_error,
        flow_rate_std_dev=std_dev,
        time_within_epsilon_pct=within_epsilon_pct,
        target_weight=target_weight,
        actual_weight=actual_weight,
        weight_achieved_pct=weight_pct,
        expected_duration_seconds=expected_duration,
        actual_duration_seconds=actual_duration,
        efficiency_ratio=efficiency_ratio,
        overall_score=overall_score
    )


def get_score_grade(score: float) -> str:
    """
    Convert a numeric score to a letter grade.
    
    Args:
        score: Numeric score from 0-100
        
    Returns:
        Letter grade (A+, A, B+, B, C+, C, D, F)
    """
    if score >= 95:
        return "A+"
    elif score >= 90:
        return "A"
    elif score >= 85:
        return "B+"
    elif score >= 80:
        return "B"
    elif score >= 75:
        return "C+"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    else:
        return "F"


def format_quality_report(metrics: BrewQualityMetrics) -> str:
    """
    Format quality metrics as a human-readable report.
    
    Args:
        metrics: The computed quality metrics
        
    Returns:
        Formatted string report
    """
    grade = get_score_grade(metrics.overall_score)
    
    report = f"""
Brew Quality Report
===================
Overall Score: {metrics.overall_score:.1f}/100 ({grade})

Flow Rate Performance:
  - Mean Absolute Error: {metrics.mean_absolute_error:.4f} g/s
  - Root Mean Square Error: {metrics.root_mean_square_error:.4f} g/s
  - Max Error: {metrics.max_error:.4f} g/s

Stability:
  - Standard Deviation: {metrics.flow_rate_std_dev:.4f} g/s
  - Time within epsilon: {metrics.time_within_epsilon_pct:.1f}%

Completeness:
  - Target: {metrics.target_weight:.0f}g
  - Actual: {metrics.actual_weight:.0f}g
  - Achieved: {metrics.weight_achieved_pct:.1f}%

Timing:
  - Expected: {metrics.expected_duration_seconds:.0f}s
  - Actual: {metrics.actual_duration_seconds:.0f}s
  - Efficiency: {metrics.efficiency_ratio:.2f}x
"""
    return report.strip()
