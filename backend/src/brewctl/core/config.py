import os

from .log import logger

# ===== Core Configuration =====
# Shared configuration that applies to all components
BREWCTL_IS_PROD = os.environ.get('BREWCTL_IS_PROD', "false") == "true"
logger.info(f"BREWCTL_IS_PROD = {BREWCTL_IS_PROD}")

# Frontend configuration
BREWCTL_FRONTEND_ORIGIN = os.getenv('BREWCTL_FRONTEND_ORIGIN', 'http://localhost:5173')
BREWCTL_FRONTEND_API_URL = os.getenv("BREWCTL_FRONTEND_API_URL", 'http://localhost:8000/api')

# ===== Brew-specific Configuration =====
# These settings are core to the brewing logic and shared across components
BREWCTL_TARGET_FLOW_RATE = float(os.environ.get('BREWCTL_TARGET_FLOW_RATE', '0.05'))
logger.info(f"BREWCTL_TARGET_FLOW_RATE = {BREWCTL_TARGET_FLOW_RATE}")

BREWCTL_EPSILON = float(os.environ.get('BREWCTL_EPSILON', '0.008'))

# Target weight settings (includes vessel weight)
BREWCTL_TARGET_WEIGHT_GRAMS = int(os.environ.get('BREWCTL_TARGET_WEIGHT_GRAMS', '1337'))
BREWCTL_VESSEL_WEIGHT_GRAMS = int(os.environ.get('BREWCTL_VESSEL_WEIGHT_GRAMS', '229'))

# Collection intervals
BREWCTL_SCALE_READ_INTERVAL = float(os.getenv("BREWCTL_SCALE_READ_INTERVAL", "0.5"))
BREWCTL_VALVE_INTERVAL_SECONDS = int(os.environ.get('BREWCTL_VALVE_INTERVAL_SECONDS', '90'))
logger.info(f"BREWCTL_VALVE_INTERVAL_SECONDS = {BREWCTL_VALVE_INTERVAL_SECONDS}")

# ===== WebSocket Configuration =====
# These settings are shared for real-time updates
BREWCTL_WS_PUSH_INTERVAL = float(os.getenv("BREWCTL_WS_PUSH_INTERVAL", "1.0"))
logger.info(f"BREWCTL_WS_PUSH_INTERVAL = {BREWCTL_WS_PUSH_INTERVAL}")

BREWCTL_WS_HEALTH_PUSH_INTERVAL = float(os.getenv("BREWCTL_WS_HEALTH_PUSH_INTERVAL", "5.0"))
logger.info(f"BREWCTL_WS_HEALTH_PUSH_INTERVAL = {BREWCTL_WS_HEALTH_PUSH_INTERVAL}")

# ===== Scale Reconnection Configuration =====
# Shared scale connection settings
# TODO i dont think these 3 are needed
BREWCTL_SCALE_RECONNECT_RETRIES = int(os.environ.get('BREWCTL_SCALE_RECONNECT_RETRIES', '5'))
BREWCTL_SCALE_RECONNECT_BASE_DELAY = float(os.environ.get('BREWCTL_SCALE_RECONNECT_BASE_DELAY', '1.0'))
BREWCTL_SCALE_RECONNECT_MAX_DELAY = float(os.environ.get('BREWCTL_SCALE_RECONNECT_MAX_DELAY', '30.0'))