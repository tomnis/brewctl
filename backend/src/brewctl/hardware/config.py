import os

from ..core.log import logger

# ===== Hardware Configuration =====
# Configuration specific to hardware components (scale and valve)
# These settings are only needed by hardware services running on Raspberry Pi

# Scale configuration
BREWCTL_SCALE_MAC_ADDRESS = os.environ.get('BREWCTL_SCALE_MAC_ADDRESS', '')
if BREWCTL_SCALE_MAC_ADDRESS:
    logger.info(f"BREWCTL_SCALE_MAC_ADDRESS = {BREWCTL_SCALE_MAC_ADDRESS}")
else:
    logger.warning("BREWCTL_SCALE_MAC_ADDRESS not set - using mock scale")

# Valve configuration  
BREWCTL_VALVE_MOTOR_NUMBER = int(os.environ.get('BREWCTL_VALVE_MOTOR_NUMBER', '1'))
logger.info(f"BREWCTL_VALVE_MOTOR_NUMBER = {BREWCTL_VALVE_MOTOR_NUMBER}")

# Hardware-specific logging
BREWCTL_HARDWARE_LOG_LEVEL = os.environ.get('BREWCTL_HARDWARE_LOG_LEVEL', 'INFO')
logger.info(f"BREWCTL_HARDWARE_LOG_LEVEL = {BREWCTL_HARDWARE_LOG_LEVEL}")

# Hardware connection timeouts (in seconds)
BREWCTL_HARDWARE_CONNECT_TIMEOUT = float(os.environ.get('BREWCTL_HARDWARE_CONNECT_TIMEOUT', '30.0'))
BREWCTL_HARDWARE_READ_TIMEOUT = float(os.environ.get('BREWCTL_HARDWARE_READ_TIMEOUT', '5.0'))

# Motor step configuration
BREWCTL_MOTOR_STEPS_PER_REVOLUTION = int(os.environ.get('BREWCTL_MOTOR_STEPS_PER_REVOLUTION', '400'))
BREWCTL_MOTOR_STEP_DELAY = float(os.environ.get('BREWCTL_MOTOR_STEP_DELAY', '0.1'))

# Hardware health check intervals
BREWCTL_HARDWARE_HEALTH_CHECK_INTERVAL = float(os.environ.get('BREWCTL_HARDWARE_HEALTH_CHECK_INTERVAL', '10.0'))