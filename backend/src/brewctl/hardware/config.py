import os

from ..core.log import logger

# ===== Hardware Configuration =====
# Configuration specific to hardware components (scale and valve)
# These settings are only needed by hardware services running on Raspberry Pi

# Scale configuration
# The MAC shipped in deploy/pi/hardware.env.example. install.sh copies that file
# verbatim on a fresh install, so this exact value reaching a running service means
# nobody edited it -- treat it as unset rather than dialling a nonexistent device.
BREWCTL_SCALE_MAC_PLACEHOLDER = 'AA:BB:CC:DD:EE:FF'
BREWCTL_SCALE_MAC_ADDRESS = os.environ.get('BREWCTL_SCALE_MAC_ADDRESS', '').strip()
if BREWCTL_SCALE_MAC_ADDRESS.upper() == BREWCTL_SCALE_MAC_PLACEHOLDER:
    BREWCTL_SCALE_MAC_ADDRESS = ''

if BREWCTL_SCALE_MAC_ADDRESS:
    logger.info(f"BREWCTL_SCALE_MAC_ADDRESS = {BREWCTL_SCALE_MAC_ADDRESS}")
elif os.environ.get('BREWCTL_IS_PROD', 'false') == 'true':
    # Fail at startup, not at the first connect attempt. create_scale() gates on
    # BREWCTL_IS_PROD alone, so an unset or unedited MAC would otherwise build a
    # LunarScale that can never connect -- the service comes up, /health reports
    # on a scale that was never going to work, and the cause is buried in a BLE
    # timeout. Same reasoning as the InfluxDB token check in api/config.py.
    raise ValueError(
        "BREWCTL_IS_PROD=true but BREWCTL_SCALE_MAC_ADDRESS is unset or still the "
        f"{BREWCTL_SCALE_MAC_PLACEHOLDER} placeholder from hardware.env.example. "
        "Set the real scale MAC in /etc/brewctl/hardware.env "
        "(find it with: bluetoothctl scan on)."
    )
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