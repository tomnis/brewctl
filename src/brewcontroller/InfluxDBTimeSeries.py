from time_series import AbstractTimeSeries

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from retry import retry

# TODO might want to split this out further,
# brewclient doesn't need to write data, only read it
# doesn't seem like a good idea to split this into read and write abstract classes
# what about providing a bucket name as a parameter?
class InfluxDBTimeSeries(AbstractTimeSeries):

    def __init__(self, url, token, org, bucket, timeout=30_000):
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.influxdb = InfluxDBClient(url=url, token=token, org=org, timeout=timeout)


    @retry(tries=10, delay=2)
    def write_scale_data(self, weight: float, battery_pct: int):
        p = Point("coldbrew").field("weight_grams", weight).field("battery_pct", battery_pct)
        # TODO this should be async
        write_api = self.influxdb.write_api(write_options=SYNCHRONOUS)
        write_api.write(bucket=self.bucket, record=p)



    def get_current_weight(self) -> float:
        query_api = self.influxdb.query_api()
        # TODO use bucket here? is convenient to read from real data
        query = 'from(bucket: "coldbrew")\
            |> range(start: -10s)\
            |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")'
        tables = query_api.query(org=self.org, query=query)
        for table in tables:
            for record in table.records:
                print(f"Time: {record.get_time()}, Value: {record.get_value()}")

        # TODO handle empty case
        result = tables[-1].records[-1]
        return result.get_value()

    def get_current_flow_rate(self) -> float:
        query_api = self.influxdb.query_api()
        query = 'import "experimental/aggregate"\
        from(bucket: "coldbrew")\
          |> range(start: -2m)\
          |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")\
          |> aggregate.rate(every: 1m, unit: 1s)'
        tables = query_api.query(org=self.org, query=query)
        for table in tables:
            for record in table.records:
                print(f"Time: {record.get_time()}, Value: {record.get_value()}")

        # TODO it does actually seem better to take the last value here
        # even though its noisy and not necessarily representative of the full period
        # TODO handle empty case
        result = tables[-1].records[-1]
        # TODO consider calculating the mean here
        return result.get_value()