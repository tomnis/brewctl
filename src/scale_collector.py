from pyacaia import AcaiaScale
from pyacaia import *
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from retry import retry
import pyacaia
import time
import influxdb_client
import os
from constants import *


# TODO this should be async
scale=AcaiaScale(mac=COLDBREW_SCALE_MAC_ADDRESS)
scale.connect()

# battery value in percent
print("battery", scale.battery)

# scale units is 'grams' or 'ounces'
print("units", scale.units)

# minutes of idle before auto-off
print("auto-off", scale.auto_off)

org = COLDBREW_INFLUXDB_ORG
bucket_name = COLDBREW_INFLUXDB_BUCKET

client = InfluxDBClient(url=COLDBREW_INFLUXDB_URL, token=COLDBREW_INFLUXDB_TOKEN, org=org, timeout=30_000)
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
def write_scale_data(scale, client):
    weight = scale.weight
    print(scale.weight) # this is the property we can use to read the weigth in realtime

    p = Point("coldbrew").field("weight_grams", weight).field("battery_pct", scale.battery)
    client = InfluxDBClient(url=COLDBREW_INFLUXDB_URL, token=COLDBREW_INFLUXDB_TOKEN, org=org, timeout=30_000)
    # TODO this should be async
    write_api = client.write_api(write_options=SYNCHRONOUS)
    write_api.write(bucket=bucket_name, record=p)


#read and print the weight
while(True):

    write_scale_data(scale, client)
    time.sleep(0.5)
    # check if the scale is still connected, perhaps it was turned off?
    # TODO there should be some more error handling around this
    if not scale.connected:
        break
    # TODO should reconnect influxdbclient

scale.disconnect()
