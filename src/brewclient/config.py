import os

# TODO probably want a better name for this
COLDBREW_VALVE_URL = os.environ.get('COLDBREW_VALVE_URL', 'http://localhost:8000')


COLDBREW_TARGET_FLOW_RATE = float(os.environ.get('COLDBREW_TARGET_FLOW_RATE', '0.05'))
COLDBREW_EPSILON = float(os.environ.get('COLDBREW_EPSILON', '0.008'))