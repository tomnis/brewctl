import time
from config import *
from MotorKitValve import MotorKitValve
from InfluxDBTimeSeries import InfluxDBTimeSeries

url = COLDBREW_INFLUXDB_URL
org = COLDBREW_INFLUXDB_ORG
bucket = COLDBREW_INFLUXDB_BUCKET
token = COLDBREW_INFLUXDB_TOKEN
time_series = InfluxDBTimeSeries(url=url, token=token, org=org, bucket=bucket)

target_flow_rate = 0.05
epsilon = 0.008

initial_weight = 0
is_first_time = True

valve = MotorKitValve(1)

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

    # TODO move starting weight here

    current_weight = 0

    while current_weight < target_weight:
        # get the current flow rate
        print("====")
        result = time_series.get_current_flow_rate()
        print(f"got result: {result}")
        if result is None:
            print("result is none")
            time.sleep(interval)
            continue

        elif abs(target_flow_rate - result) <= epsilon:
            print("just right")
            time.sleep(interval * 2)
            continue
        elif result <= target_flow_rate:
            print("too slow")
            valve.step_forward()
        else:
            print("too fast")
            valve.step_backward()

        current_weight = get_current_weight()
        time.sleep(interval)

    # reached target weight, fully close the valve
    print(f"reached target weight")
    valve.return_to_start()



if __name__ == "__main__":
    main()
