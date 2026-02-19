from abc import ABC, abstractmethod
from typing import Any

from log import logger
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from retry import retry


class AbstractTimeSeries(ABC):

    @abstractmethod
    def write_scale_data(self, weight: float, battery_pct: int) -> None:
        """Write the current weight to the time series."""
        pass

    @abstractmethod
    def get_current_weight(self) -> float:
        """Get the current weight from the time series."""
        pass

    @abstractmethod
    def get_current_flow_rate(self) -> float:
        """Get the current flow rate from the time series."""
        pass



class InfluxDBTimeSeries(AbstractTimeSeries):

    def __init__(self, url, token, org, bucket, timeout=30_000):
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        # logger.info(f"instantiated client: {self.url} {self.org} {self.bucket}")
        self.influxdb = InfluxDBClient(url=url, token=token, org=org, timeout=timeout)


    @retry(tries=10, delay=4)
    def write_scale_data(self, weight: float, battery_pct: int):
        # logger.info(f"writing influxdb data: {weight} {battery_pct}")
        p = Point("coldbrew").field("weight_grams", weight).field("battery_pct", battery_pct)
        # TODO this should be async
        write_api = self.influxdb.write_api(write_options=SYNCHRONOUS)
        write_api.write(bucket=self.bucket, record=p)


    @retry(tries=10, delay=4)
    def get_current_weight(self) -> float:
        query_api = self.influxdb.query_api()
        query = f'from(bucket: "{self.bucket}")\
            |> range(start: -10s)\
            |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")'
        tables = query_api.query(org=self.org, query=query)
        for table in tables:
            for record in table.records:
                logger.info(f"Time: {record.get_time()}, Value: {record.get_value()}")

        # TODO handle empty case
        result = tables[-1].records[-1]
        return result.get_value()

    @retry(tries=10, delay=4)
    def get_current_flow_rate(self) -> float | None:
        query_api = self.influxdb.query_api()
        query = f'import "experimental/aggregate"\
        from(bucket: "{self.bucket}")\
          |> range(start: -3m)\
          |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")\
          |> aggregate.rate(every: 1m, unit: 1s)'
        tables = query_api.query(org=self.org, query=query)
        
        # Filter to only include complete 1-minute intervals (window duration >= 55 seconds)
        # This excludes the last partial interval which causes noisy readings
        complete_records = []
        for table in tables:
            for i, record in enumerate(table.records):
                if i == 0:
                    continue  # Skip first record as we need a previous record to compare
                prev_record = table.records[i - 1]
                current_time = record.get_time()
                prev_time = prev_record.get_time()
                window_duration = (current_time - prev_time).total_seconds()
                
                value = record.get_value()
                if value is None:
                    value = 0.0
                
                logger.info(f"Time: {current_time}, Value: {value:.4f}, Window: {window_duration:.1f}s")
                
                # Only include records where the window is at least 55 seconds (allowing some tolerance)
                if window_duration >= 55:
                    complete_records.append(record)
        
        # Handle empty case
        if not complete_records:
            logger.warning("No complete flow rate intervals found")
            return None
        
        # Return the last complete interval (most recent full minute)
        result = complete_records[-1]
        return result.get_value()
