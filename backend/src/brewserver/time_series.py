from abc import ABC, abstractmethod
from typing import Any, List, Tuple
from datetime import datetime

from log import logger
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from retry import retry
from config import COLDBREW_VALVE_INTERVAL_SECONDS


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

    @abstractmethod
    def get_flow_rate_since(self, start_time: datetime) -> float | None:
        """Get the flow rate from readings since the given start time."""
        pass

    def get_recent_weight_readings(self, duration_seconds: int = COLDBREW_VALVE_INTERVAL_SECONDS) -> List[Tuple[datetime, float]]:
        """
        Read raw sequential weight values from InfluxDB.
        
        Args:
            duration_seconds: How many seconds of history to query
            
        Returns:
            List of (timestamp, weight) tuples sorted by time ascending
        """
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
    def get_recent_weight_readings(self, duration_seconds: int = COLDBREW_VALVE_INTERVAL_SECONDS) -> List[Tuple[datetime, float]]:
        """
        Read raw sequential weight values from InfluxDB.
        
        Args:
            duration_seconds: How many seconds of history to query
            
        Returns:
            List of (timestamp, weight) tuples sorted by time ascending
        """
        query_api = self.influxdb.query_api()
        query = f'from(bucket: "{self.bucket}")\
            |> range(start: -{duration_seconds}s)\
            |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")'
        tables = query_api.query(org=self.org, query=query)
        
        readings: List[Tuple[datetime, float]] = []
        for table in tables:
            for record in table.records:
                timestamp = record.get_time()
                value = record.get_value()
                if value is not None:
                    readings.append((timestamp, value))
        
        # Sort by timestamp ascending
        readings.sort(key=lambda x: x[0])
        # logger.info(f"Retrieved {len(readings)} weight readings from the last {duration_seconds} seconds")
        return readings

    def calculate_flow_rate_from_derivatives(
        self, 
        readings: List[Tuple[datetime, float]]
    ) -> float | None:
        """
        Calculate flow rate by computing the derivative from raw weight readings.
        
        Args:
            readings: List of (timestamp, weight) tuples sorted by time ascending
            
        Returns:
            Flow rate in grams per second, or None if insufficient data
        """
        if len(readings) < 2:
            logger.warning("Insufficient readings for derivative calculation")
            return None
        
        # Calculate derivative between the first and last readings
        prev_time, prev_weight = readings[0]
        curr_time, curr_weight = readings[-1]
        
        time_diff = (curr_time - prev_time).total_seconds()
        
        if time_diff <= 0:
            logger.warning("Invalid time difference between readings")
            return None
        
        weight_diff = curr_weight - prev_weight
        rate = weight_diff / time_diff
        
        # logger.info(f"Calculated flow rate: {weight_diff:.2f}g over {time_diff:.1f}s = {rate:.4f} g/s")
        return rate

    @retry(tries=10, delay=4)
    def get_current_flow_rate(self) -> float | None:
        """
        Get the current flow rate by calculating derivatives from raw weight readings.
        
        This method reads sequential weight values from InfluxDB and calculates
        the derivative (rate of change) in Python, rather than using InfluxDB's
        built-in aggregate.rate() function.
        """
        # Read raw sequential weight values (aligned with VALVE_INTERVAL)
        readings = self.get_recent_weight_readings(duration_seconds=COLDBREW_VALVE_INTERVAL_SECONDS)
        
        if not readings:
            logger.warning("No weight readings available for flow rate calculation")
            return None
        
        # Calculate flow rate from derivatives
        return self.calculate_flow_rate_from_derivatives(readings)

    @retry(tries=10, delay=4)
    def get_flow_rate_since(self, start_time: datetime) -> float | None:
        """
        Get the flow rate from readings since the given start time.
        
        This method filters weight readings to only include those from the given
        start_time onwards, which is useful when starting a new brew after a
        previous brew has finished (to avoid picking up stale weight data).
        
        Args:
            start_time: The timestamp to filter readings from
            
        Returns:
            Flow rate in grams per second, or None if insufficient data
        """
        query_api = self.influxdb.query_api()
        # Query from the start_time onwards
        query = f'from(bucket: "{self.bucket}")\
            |> range(start: {start_time.isoformat()})\
            |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")'
        tables = query_api.query(org=self.org, query=query)
        
        readings: List[Tuple[datetime, float]] = []
        for table in tables:
            for record in table.records:
                timestamp = record.get_time()
                value = record.get_value()
                if value is not None:
                    readings.append((timestamp, value))
        
        # Sort by timestamp ascending
        readings.sort(key=lambda x: x[0])
        
        if not readings:
            logger.warning(f"No weight readings found since {start_time}")
            return None
        
        # logger.info(f"Retrieved {len(readings)} weight readings since {start_time}")
        
        # Calculate flow rate from derivatives
        return self.calculate_flow_rate_from_derivatives(readings)
