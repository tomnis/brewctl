import time

import random

from brewclient.config import *
from base.config import *
from InfluxDBTimeSeries import InfluxDBTimeSeries
from HttpValve import HttpValve

brewer_url = COLDBREW_VALVE_URL

influxdb_url = COLDBREW_INFLUXDB_URL
influxdb_org = COLDBREW_INFLUXDB_ORG
influxdb_bucket = COLDBREW_INFLUXDB_BUCKET
influxdb_token = COLDBREW_INFLUXDB_TOKEN
print(f"using influxdb bucket: {influxdb_bucket}")
time_series = InfluxDBTimeSeries(url=influxdb_url, token=influxdb_token, org=influxdb_org, bucket=influxdb_bucket)

target_flow_rate = 0.05
epsilon = 0.008

initial_weight = 0
is_first_time = True


def main():

    """The main function of the script."""
    interval = 60
    #interval = 0.5
    # target total weight, don't bother taring
    #target_weight = 100 #1137
    target_weight = 1137

    # sleep to let the initial saturation drain
    # TODO should add a param for this
    #time.sleep(120)
    # TODO should use a enter/exit here

    current_weight = 0

    #while current_weight < target_weight:
    with HttpValve(brewer_url) as valve:
        for i in range(32):
            r = random.random()
            if r > 0.8:
                valve.step_backward()
            else:
                valve.step_forward()
            time.sleep(0.5)

        # TODO investigate this further, not enough torque?
        valve.return_to_start()


if __name__ == "__main__":
    main()