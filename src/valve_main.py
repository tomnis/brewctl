import time

from base.config import *
from brewclient.InfluxDBTimeSeries import InfluxDBTimeSeries
from brewclient.HttpValve import HttpValve

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

def get_current_weight():
    # TODO don't use global
    global initial_weight
    global is_first_time

    result = time_series.get_current_weight()
    # track our starting weight to derive a delta of when we should stop
    if is_first_time:
        is_first_time = False
        initial_weight = result

    return result

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
        # TODO block until current flow rate decreases
        while True:
            # get the current flow rate
            print("====")
            current_flow_rate = time_series.get_current_flow_rate()
            print(f"got result: {current_flow_rate}")
            if current_flow_rate is None:
                print("result is none")
                time.sleep(interval)
                continue

            elif abs(target_flow_rate - current_flow_rate) <= epsilon:
                print("just right")
                time.sleep(interval * 2)
                continue
            elif current_flow_rate <= target_flow_rate:
                print("too slow")
                valve.step_forward()
            else:
                print("too fast")
                valve.step_backward()

            # TODO can just check the weight from the scale here
            current_weight = get_current_weight()
            time.sleep(interval)

        # reached target weight, fully close the valve
        print(f"reached target weight")
        #valve.return_to_start()

        valve.release()


if __name__ == "__main__":
    main()

