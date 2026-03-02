import logging

logger = logging.getLogger(__name__)


class KalmanFilter:
    """
    A simple 1D Kalman Filter for smoothing flow rate measurements.
    
    State: x = flow rate (g/s)
    Process model: x_k = x_{k-1} + w (random walk)
    Measurement model: z_k = x_k + v (noisy observation)
    
    Parameters:
        q: Process noise covariance (how much the flow naturally varies)
        r: Measurement noise covariance (how noisy our sensor readings are)
    """
    
    def __init__(self, q: float = 0.001, r: float = 0.1, initial_estimate: float = 0.0, initial_error: float = 1.0):
        self.q: float = float(q)  # Process noise covariance
        self.r: float = r  # Measurement noise covariance
        
        self.x: float = initial_estimate  # Current state estimate
        self.p: float = initial_error      # Current estimate error covariance
        self.is_initialized = initial_error < 1e9  # Have we received our first measurement?
    
    def update(self, measurement: float) -> float:
        """
        Update the filter with a new measurement.
        
        Args:
            measurement: The raw flow rate reading from the sensor
            
        Returns:
            The filtered (smoothed) flow rate estimate
        """
        if measurement is None:
            return self.x
        
        if not self.is_initialized:
            # First measurement - just use it as our initial estimate
            self.x = measurement
            self.p = self.r
            self.is_initialized = True
            return self.x
        
        # Prediction step: predict current state and error
        # Since we're using a random walk model, x_pred = x_prev
        x_pred: float = self.x
        logger.info(f"p: {self.p}")
        logger.info(f"q: {self.q}")

        p_pred = float(self.p) + float(self.q)

        logger.info(f"p_pred: {p_pred}")
        logger.info(f"r: {self.r}")
        # Update step: incorporate the measurement
        # Kalman gain
        k = p_pred / (float(p_pred) + float(self.r))
        
        # Update state estimate
        self.x = x_pred + k * (measurement - x_pred)
        
        # Update error estimate
        self.p = (1 - k) * p_pred
        
        return self.x
    
    def reset(self):
        """Reset the filter to its initial state."""
        self.x = 0.0
        self.p = 1.0
        self.is_initialized = False
