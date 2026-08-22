import os

from .log import logger

# ===== Core Configuration =====
# Shared configuration that applies to all components
BREWCTL_IS_PROD = os.environ.get("BREWCTL_IS_PROD", "false") == "true"
logger.info(f"BREWCTL_IS_PROD = {BREWCTL_IS_PROD}")

# Frontend configuration
BREWCTL_FRONTEND_ORIGIN = os.getenv("BREWCTL_FRONTEND_ORIGIN", "http://localhost:5173")
BREWCTL_FRONTEND_API_URL = os.getenv(
    "BREWCTL_FRONTEND_API_URL", "http://localhost:8000/api"
)

# ===== Brew-specific Configuration =====
# These settings are core to the brewing logic and shared across components
BREWCTL_TARGET_FLOW_RATE = float(os.environ.get("BREWCTL_TARGET_FLOW_RATE", "0.05"))
logger.info(f"BREWCTL_TARGET_FLOW_RATE = {BREWCTL_TARGET_FLOW_RATE}")

BREWCTL_EPSILON = float(os.environ.get("BREWCTL_EPSILON", "0.008"))

# Target weight settings (includes vessel weight)
BREWCTL_TARGET_WEIGHT_GRAMS = int(os.environ.get("BREWCTL_TARGET_WEIGHT_GRAMS", "1337"))
BREWCTL_VESSEL_WEIGHT_GRAMS = int(os.environ.get("BREWCTL_VESSEL_WEIGHT_GRAMS", "229"))
# Logged because this is the value to check first when a brew stops at the wrong
# weight: it is subtracted from every target, and nothing in the UI sets it.
logger.info(f"BREWCTL_VESSEL_WEIGHT_GRAMS = {BREWCTL_VESSEL_WEIGHT_GRAMS}")

# Collection intervals
BREWCTL_SCALE_READ_INTERVAL = float(os.getenv("BREWCTL_SCALE_READ_INTERVAL", "0.5"))
BREWCTL_SCALE_BUFFER_SIZE = int(os.getenv("BREWCTL_SCALE_BUFFER_SIZE", "64"))
BREWCTL_VALVE_INTERVAL_SECONDS = int(
    os.environ.get("BREWCTL_VALVE_INTERVAL_SECONDS", "90")
)
logger.info(f"BREWCTL_VALVE_INTERVAL_SECONDS = {BREWCTL_VALVE_INTERVAL_SECONDS}")

# ===== Realtime push configuration (SSE) =====
# These settings are shared for real-time updates
BREWCTL_WS_PUSH_INTERVAL = float(os.getenv("BREWCTL_WS_PUSH_INTERVAL", "1.0"))
logger.info(f"BREWCTL_WS_PUSH_INTERVAL = {BREWCTL_WS_PUSH_INTERVAL}")

BREWCTL_WS_HEALTH_PUSH_INTERVAL = float(
    os.getenv("BREWCTL_WS_HEALTH_PUSH_INTERVAL", "5.0")
)
logger.info(f"BREWCTL_WS_HEALTH_PUSH_INTERVAL = {BREWCTL_WS_HEALTH_PUSH_INTERVAL}")

# ===== Scale Reconnection Configuration =====
# Shared scale connection settings
# TODO i dont think these 3 are needed
BREWCTL_SCALE_RECONNECT_RETRIES = int(
    os.environ.get("BREWCTL_SCALE_RECONNECT_RETRIES", "5")
)
BREWCTL_SCALE_RECONNECT_BASE_DELAY = float(
    os.environ.get("BREWCTL_SCALE_RECONNECT_BASE_DELAY", "1.0")
)
BREWCTL_SCALE_RECONNECT_MAX_DELAY = float(
    os.environ.get("BREWCTL_SCALE_RECONNECT_MAX_DELAY", "30.0")
)
# Patience window for a CONNECTED-but-silent scale. The hardware scale monitor
# keeps the BLE link for this long before tearing it down (a connected scale
# that is not streaming may simply be an event-driven one between weight
# changes; reconnect churn made recovery worse -- see
# docs/plans/scale-recovery-stability-plan.md). The api uses the same value as
# a brew guard: silence longer than this mid-brew fails the brew and returns
# the valve, because the strategy cannot act on a None flow and the valve
# would otherwise pour open-loop. 0 disables the api-side guard.
BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS = float(
    os.environ.get("BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS", "30.0")
)
