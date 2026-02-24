import os

from log import logger

# TODO not sure why these are logger.infoed twice by fastapi cli
BREWCTL_IS_PROD = os.environ.get('BREWCTL_IS_PROD', "false") == "true"
logger.info(f"BREWCTL_IS_PROD = {BREWCTL_IS_PROD}")
BREWCTL_SCALE_MAC_ADDRESS = os.environ['BREWCTL_SCALE_MAC_ADDRESS'] if BREWCTL_IS_PROD else ""
BREWCTL_INFLUXDB_URL = os.environ['BREWCTL_INFLUXDB_URL']
logger.info(f"BREWCTL_INFLUXDB_URL = {BREWCTL_INFLUXDB_URL}")
BREWCTL_INFLUXDB_TOKEN = os.environ['BREWCTL_INFLUXDB_TOKEN']
BREWCTL_INFLUXDB_ORG = os.environ['BREWCTL_INFLUXDB_ORG']
logger.info(f"BREWCTL_INFLUXDB_ORG = {BREWCTL_INFLUXDB_ORG}")

# if this is ever changed, need to also change grafana dashboard queries
BREWCTL_INFLUXDB_BUCKET = os.getenv('BREWCTL_INFLUXDB_BUCKET', 'coldbrew') if BREWCTL_IS_PROD else os.getenv('BREWCTL_INFLUXDB_BUCKET', 'coldbrew') + '-dev'
logger.info(f"BREWCTL_INFLUXDB_BUCKET = {BREWCTL_INFLUXDB_BUCKET}")

BREWCTL_FRONTEND_ORIGIN = os.getenv('BREWCTL_FRONTEND_ORIGIN', 'http://localhost:5173')


# ===== brew-specific configuration =====
# collect as much raw data as we can
BREWCTL_SCALE_READ_INTERVAL = float(os.getenv("BREWCTL_SCALE_READ_INTERVAL", "0.5"))
# the target flow rate in grams per second. Adjust the valve to maintain this flow rate.
BREWCTL_TARGET_FLOW_RATE = float(os.environ.get('BREWCTL_TARGET_FLOW_RATE', '0.05'))
logger.info(f"BREWCTL_TARGET_FLOW_RATE = {BREWCTL_TARGET_FLOW_RATE}")
BREWCTL_EPSILON = float(os.environ.get('BREWCTL_EPSILON', '0.008'))
# how often to check the flow rate and adjust the valve (in seconds)
BREWCTL_VALVE_INTERVAL_SECONDS = int(os.environ.get('BREWCTL_VALVE_INTERVAL_SECONDS', '90'))
logger.info(f"BREWCTL_VALVE_INTERVAL_SECONDS = {BREWCTL_VALVE_INTERVAL_SECONDS}")

BREWCTL_TARGET_WEIGHT_GRAMS = int(os.environ.get('BREWCTL_TARGET_WEIGHT_GRAMS', '1337'))
BREWCTL_VESSEL_WEIGHT_GRAMS = int(os.environ.get('BREWCTL_VESSEL_WEIGHT_GRAMS', '229'))
# ===== end brew-specific configuration =====


BREWCTL_FRONTEND_API_URL= os.getenv("BREWCTL_FRONTEND_API_URL", 'http://localhost:8000/api')


# ===== scale reconnection configuration =====
BREWCTL_SCALE_RECONNECT_RETRIES = int(os.environ.get('BREWCTL_SCALE_RECONNECT_RETRIES', '5'))
BREWCTL_SCALE_RECONNECT_BASE_DELAY = float(os.environ.get('BREWCTL_SCALE_RECONNECT_BASE_DELAY', '1.0'))
BREWCTL_SCALE_RECONNECT_MAX_DELAY = float(os.environ.get('BREWCTL_SCALE_RECONNECT_MAX_DELAY', '30.0'))
# ===== end scale reconnection configuration =====
