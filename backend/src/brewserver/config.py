import os

from log import logger

# TODO not sure why these are logger.infoed twice by fastapi cli
COLDBREW_IS_PROD = os.environ.get('COLDBREW_IS_PROD', "false") == "true"
logger.info(f"COLDBREW_IS_PROD = {COLDBREW_IS_PROD}")
COLDBREW_SCALE_MAC_ADDRESS = os.environ['COLDBREW_SCALE_MAC_ADDRESS'] if COLDBREW_IS_PROD else ""
COLDBREW_INFLUXDB_URL = os.environ['COLDBREW_INFLUXDB_URL']
logger.info(f"COLDBREW_INFLUXDB_URL = {COLDBREW_INFLUXDB_URL}")
COLDBREW_INFLUXDB_TOKEN = os.environ['COLDBREW_INFLUXDB_TOKEN']
COLDBREW_INFLUXDB_ORG = os.environ['COLDBREW_INFLUXDB_ORG']
logger.info(f"COLDBREW_INFLUXDB_ORG = {COLDBREW_INFLUXDB_ORG}")

# if this is ever changed, need to also change grafana dashboard queries
COLDBREW_INFLUXDB_BUCKET = os.getenv('COLDBREW_INFLUXDB_BUCKET', 'coldbrew') if COLDBREW_IS_PROD else os.getenv('COLDBREW_INFLUXDB_BUCKET', 'coldbrew') + '-dev'
logger.info(f"COLDBREW_INFLUXDB_BUCKET = {COLDBREW_INFLUXDB_BUCKET}")

COLDBREW_FRONTEND_ORIGIN = os.getenv('COLDBREW_FRONTEND_ORIGIN', 'http://localhost:5173')


# ===== brew-specific configuration =====
# collect as much raw data as we can
COLDBREW_SCALE_READ_INTERVAL = float(os.getenv("COLDBREW_SCALE_READ_INTERVAL", "0.5"))
# the target flow rate in grams per second. Adjust the valve to maintain this flow rate.
COLDBREW_TARGET_FLOW_RATE = float(os.environ.get('COLDBREW_TARGET_FLOW_RATE', '0.05'))
logger.info(f"COLDBREW_TARGET_FLOW_RATE = {COLDBREW_TARGET_FLOW_RATE}")
COLDBREW_EPSILON = float(os.environ.get('COLDBREW_EPSILON', '0.008'))
# how often to check the flow rate and adjust the valve (in seconds)
COLDBREW_VALVE_INTERVAL_SECONDS = int(os.environ.get('COLDBREW_VALVE_INTERVAL_SECONDS', '60'))
logger.info(f"COLDBREW_VALVE_INTERVAL_SECONDS = {COLDBREW_VALVE_INTERVAL_SECONDS}")

COLDBREW_TARGET_WEIGHT_GRAMS = int(os.environ.get('COLDBREW_TARGET_WEIGHT_GRAMS', '1337'))
# ===== end brew-specific configuration =====


COLDBREW_FRONTEND_API_URL= os.getenv("COLDBREW_FRONTEND_API_URL", 'http://localhost:8000/api')