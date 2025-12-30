import time

from config import *
import requests

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from retry import retry

brewer_url = COLDBREW_VALVE_URL

org = COLDBREW_INFLUXDB_ORG
bucket_name = COLDBREW_INFLUXDB_BUCKET

client = InfluxDBClient(url=COLDBREW_INFLUXDB_URL, token=COLDBREW_INFLUXDB_TOKEN, org=org, timeout=30_000)

def ensure_bucket_exists():
    buckets_api = client.buckets_api()
    existing_bucket = buckets_api.find_bucket_by_name(bucket_name)

    if existing_bucket is None:
        # Define retention rules (e.g., expire data after 7 days)
        retention_rules = [influxdb_client.BucketRetentionRules(type="expire", every_seconds=604800)] # 7 days in seconds

        # Create the bucket
        created_bucket = buckets_api.create_bucket(bucket_name=bucket_name, retention_rules=retention_rules, org=org)
        print(f"Bucket '{bucket_name}' created successfully.")
    else:
        print(f"Bucket '{bucket_name}' already exists.")


@retry(tries=10, delay=2)
def write_scale_data(weight: float, battery_pct: int):
    p = Point("coldbrew").field("weight_grams", weight).field("battery_pct", battery_pct)
    client = InfluxDBClient(url=COLDBREW_INFLUXDB_URL, token=COLDBREW_INFLUXDB_TOKEN, org=org, timeout=30_000)
    # TODO this should be async
    write_api = client.write_api(write_options=SYNCHRONOUS)
    write_api.write(bucket=bucket_name, record=p)


def main():
    ensure_bucket_exists()

    while True:
        response = requests.get(f"{brewer_url}/scale")
        if response.status_code == 200:
            json_response = response.json()
            weight = json_response.get("weight")
            battery_pct = json_response.get("battery_pct")
            print(f"Current Weight: {weight}; Battery: {battery_pct}%")
            write_scale_data(weight, battery_pct)
        else:
            print("Failed to retrieve current weight")

        # max out the scale saturation
        time.sleep(0.5)


if __name__ == "__main__":
    main()