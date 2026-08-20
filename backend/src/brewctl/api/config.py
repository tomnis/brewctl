import os

from ..core.log import logger
from ..core.secrets import SecretConfigError, read_secret

# ===== API Configuration =====
# Configuration specific to the API service
# These settings are only needed by the API service that handles business logic

# InfluxDB configuration
BREWCTL_INFLUXDB_URL = os.environ.get("BREWCTL_INFLUXDB_URL", "")
if BREWCTL_INFLUXDB_URL:
    logger.info(f"BREWCTL_INFLUXDB_URL = {BREWCTL_INFLUXDB_URL}")
else:
    logger.warning("BREWCTL_INFLUXDB_URL not set - time series functionality disabled")

# Supports BREWCTL_INFLUXDB_TOKEN_FILE, which is how the token reaches the
# container in production without being written into the deployment manifest.
BREWCTL_INFLUXDB_TOKEN = read_secret("BREWCTL_INFLUXDB_TOKEN")
if os.environ.get("BREWCTL_IS_PROD", "false") == "true" and not BREWCTL_INFLUXDB_TOKEN:
    # Fail at startup rather than at the first write, which could be hours into a
    # brew. Only enforced in prod so dev and tests can run without InfluxDB.
    raise SecretConfigError(
        "BREWCTL_IS_PROD is true but no InfluxDB token is configured. "
        "Set BREWCTL_INFLUXDB_TOKEN_FILE (preferred) or BREWCTL_INFLUXDB_TOKEN."
    )

BREWCTL_INFLUXDB_ORG = os.environ.get("BREWCTL_INFLUXDB_ORG", "")
logger.info(f"BREWCTL_INFLUXDB_ORG = {BREWCTL_INFLUXDB_ORG}")

# InfluxDB bucket configuration
BREWCTL_INFLUXDB_BUCKET = os.getenv("BREWCTL_INFLUXDB_BUCKET", "coldbrew")
if os.environ.get("BREWCTL_IS_PROD", "false") != "true":
    BREWCTL_INFLUXDB_BUCKET += "-dev"
logger.info(f"BREWCTL_INFLUXDB_BUCKET = {BREWCTL_INFLUXDB_BUCKET}")

# API server configuration
BREWCTL_API_HOST = os.environ.get("BREWCTL_API_HOST", "0.0.0.0")
BREWCTL_API_PORT = int(os.environ.get("BREWCTL_API_PORT", "8000"))
BREWCTL_API_DEBUG = os.environ.get("BREWCTL_API_DEBUG", "false").lower() == "true"

# CORS configuration
BREWCTL_CORS_ORIGINS = os.environ.get(
    "BREWCTL_CORS_ORIGINS", "http://localhost:5173"
).split(",")

# API rate limiting
BREWCTL_API_RATE_LIMIT_ENABLED = (
    os.environ.get("BREWCTL_API_RATE_LIMIT_ENABLED", "true").lower() == "true"
)
BREWCTL_API_RATE_LIMIT_REQUESTS = int(
    os.environ.get("BREWCTL_API_RATE_LIMIT_REQUESTS", "100")
)
BREWCTL_API_RATE_LIMIT_WINDOW = int(
    os.environ.get("BREWCTL_API_RATE_LIMIT_WINDOW", "60")
)

# Health check configuration
BREWCTL_HEALTH_CHECK_INTERVAL = float(
    os.environ.get("BREWCTL_HEALTH_CHECK_INTERVAL", "30.0")
)

# Brew strategy configuration
BREWCTL_DEFAULT_STRATEGY = os.environ.get("BREWCTL_DEFAULT_STRATEGY", "DEFAULT")
BREWCTL_STRATEGY_TIMEOUT = int(
    os.environ.get("BREWCTL_STRATEGY_TIMEOUT", "300")
)  # 5 minutes

# Quality scoring configuration
BREWCTL_QUALITY_SCORING_ENABLED = (
    os.environ.get("BREWCTL_QUALITY_SCORING_ENABLED", "true").lower() == "true"
)
BREWCTL_QUALITY_SCORING_WINDOW = int(
    os.environ.get("BREWCTL_QUALITY_SCORING_WINDOW", "60")
)  # seconds

# Hardware server URL (constructed from host and port)
#
# Required in prod. Fail loudly at startup rather than letting the None reach
# HttpScale/HttpValve, which are constructed at import time in api/server.py and
# die with `AttributeError: 'NoneType' object has no attribute 'rstrip'` sixty
# lines into a traceback -- a message that says nothing about the missing
# variable. Same reasoning as the InfluxDB token check above.
#
# Off-prod it falls back to the dev default instead of raising: the test suite
# imports this module without any environment, and the compose files set the
# variable explicitly anyway.
BREWCTL_HARDWARE_DEFAULT_URL = "http://localhost:8001"
BREWCTL_HARDWARE_URL = os.environ.get("BREWCTL_HARDWARE_URL", "").strip()
if not BREWCTL_HARDWARE_URL:
    if os.environ.get("BREWCTL_IS_PROD", "false") == "true":
        raise ValueError(
            "BREWCTL_IS_PROD is true but BREWCTL_HARDWARE_URL is not set. "
            "Set it to the hardware service, e.g. http://coldbrewer.local:8000"
        )
    BREWCTL_HARDWARE_URL = BREWCTL_HARDWARE_DEFAULT_URL
    logger.warning(
        f"BREWCTL_HARDWARE_URL not set - defaulting to {BREWCTL_HARDWARE_URL}"
    )
logger.info(f"BREWCTL_HARDWARE_URL = {BREWCTL_HARDWARE_URL}")
