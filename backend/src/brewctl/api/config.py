import os

from ..core.log import logger

# ===== API Configuration =====
# Configuration specific to the API service
# These settings are only needed by the API service that handles business logic

# InfluxDB configuration
BREWCTL_INFLUXDB_URL = os.environ.get("BREWCTL_INFLUXDB_URL", "")
if BREWCTL_INFLUXDB_URL:
    logger.info(f"BREWCTL_INFLUXDB_URL = {BREWCTL_INFLUXDB_URL}")
else:
    logger.warning("BREWCTL_INFLUXDB_URL not set - time series functionality disabled")

BREWCTL_INFLUXDB_TOKEN = os.environ.get("BREWCTL_INFLUXDB_TOKEN", "")
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

# Hardware server connection (for proxying valve calls)
BREWCTL_HARDWARE_HOST = os.environ.get("BREWCTL_HARDWARE_HOST", "localhost")
BREWCTL_HARDWARE_PORT = int(os.environ.get("BREWCTL_HARDWARE_PORT", "8000"))
logger.info(f"BREWCTL_HARDWARE_HOST = {BREWCTL_HARDWARE_HOST}")
logger.info(f"BREWCTL_HARDWARE_PORT = {BREWCTL_HARDWARE_PORT}")
