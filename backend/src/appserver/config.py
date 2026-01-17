import os

# TODO probably want a better name for this
COLDBREW_VALVE_URL = os.environ.get('COLDBREW_VALVE_URL', 'http://localhost:8000')
print(f"COLDBREW_VALVE_URL = {COLDBREW_VALVE_URL}")