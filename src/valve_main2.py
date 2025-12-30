import requests
import time

from config import *
from InfluxDBTimeSeries import InfluxDBTimeSeries

brewer_url = COLDBREW_VALVE_URL

influxdb_url = COLDBREW_INFLUXDB_URL
influxdb_org = COLDBREW_INFLUXDB_ORG
influxdb_bucket = COLDBREW_INFLUXDB_BUCKET
influxdb_token = COLDBREW_INFLUXDB_TOKEN
print(influxdb_bucket)
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


def acquire():
    """Acquire the valve for exclusive use."""
    response = requests.post(f"{brewer_url}/valve/acquire")
    #print(response.json())
    if response.status_code == 200:
        return response.json().get("brew_id")
    else:
        print("Failed to acquire valve")

def release(brew_id: str):
    """Release the valve for exclusive use."""
    response = requests.post(f"{brewer_url}/valve/release", params={"brew_id": brew_id})
    if response.status_code == 200:
        print("Released valve")
    else:
        print("Failed to release valve")

def step_forward(brew_id: str):
    """Open the valve one step."""
    response = requests.post(f"{brewer_url}/valve/forward/1", params={"brew_id": brew_id})
    if response.status_code == 200:
        print("Stepped valve forward")
    else:
        print(response)
        print(response.json())
        print("Failed to step valve forward")

def step_backward(brew_id: str):
    """Close the valve one step."""
    response = requests.post(f"{brewer_url}/valve/backward/1", params={"brew_id": brew_id})
    if response.status_code == 200:
        print("Stepped valve backward")
    else:
        print(response)
        print("Failed to step valve backward")

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

    # TODO move starting weight here
    cur_brew_id = acquire()
    print("Acquired valve for brew id:", cur_brew_id)

    current_weight = 0
    #while current_weight < target_weight:
    while True:
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
            step_forward(cur_brew_id)
        else:
            print("too fast")
            step_backward(cur_brew_id)

        current_weight = get_current_weight()
        time.sleep(interval)

    # reached target weight, fully close the valve
    print(f"reached target weight")
    #valve.return_to_start()

    release(cur_brew_id)


if __name__ == "__main__":
    main()

