import time
from influxdb_client import InfluxDBClient, Point
from config import *
from MotorKitValve import MotorKitValve

org = COLDBREW_INFLUXDB_ORG
bucket_name = COLDBREW_INFLUXDB_BUCKET
token = COLDBREW_INFLUXDB_TOKEN
client = InfluxDBClient(url=COLDBREW_INFLUXDB_URL, token=token, org=org, timeout=30_000)

target_flow_rate = 0.05
epsilon = 0.008


initial_weight = 0
is_first_time = True

valve = MotorKitValve(1)

def get_current_weight(influx_client, org):
    # TODO don't use global
    global initial_weight
    global is_first_time

    query_api = client.query_api()
    query = 'from(bucket: "coldbrew")\
            |> range(start: -10s)\
            |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")'
    tables = query_api.query(org=org, query=query)
    for table in tables:
        for record in table.records:
            print(f"Time: {record.get_time()}, Value: {record.get_value()}")
    result = tables[-1].records[-1]

    # track our starting weight to derive a delta of when we should stop
    if is_first_time:
        is_first_time = False
        initial_weight = result

    return result.get_value()

def get_flow_rate(influx_client, org):
    query_api = client.query_api()
    query = 'import "experimental/aggregate"\
    from(bucket: "coldbrew")\
      |> range(start: -2m)\
      |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")\
      |> aggregate.rate(every: 1m, unit: 1s)'
    tables = query_api.query(org=org, query=query)
    for table in tables:
        for record in table.records:
            print(f"Time: {record.get_time()}, Value: {record.get_value()}")

    #results = [x.get_value() for x in tables[-1].records[-3:]]
    #results = [x for x in results if x is not None]
    result = tables[-1].records[-2]
    #print(result)

    #return mean(results)
    return result.get_value()


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
        result = get_flow_rate(client, org)
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

        time.sleep(interval)
        current_weight = get_current_weight(client, org)

    # reached target weight, fully close the valve
    print(f"reached target weight")
    valve.return_to_start()



if __name__ == "__main__":
    main()
