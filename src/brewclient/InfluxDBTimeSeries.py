from influxdb_client import InfluxDBClient, Point
from ..base.time_series import TimeSeries

class InfluxDBTimeSeries(TimeSeries):

    def __init__(self, url, token, org, bucket, timeout=30_000):
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        # Initialize InfluxDB client here (not implemented)
        self.influxdb = InfluxDBClient(url=url, token=token, org=org, timeout=timeout)


    def get_current_weight(self) -> float:
        query_api = self.influxdb.query_api()
        # TODO use bucket here
        query = 'from(bucket: "coldbrew")\
            |> range(start: -10s)\
            |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")'
        tables = query_api.query(org=self.org, query=query)
        for table in tables:
            for record in table.records:
                print(f"Time: {record.get_time()}, Value: {record.get_value()}")

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
        result = tables[-1].records[-1]
        # TODO consider calculating the mean here
        return result.get_value()