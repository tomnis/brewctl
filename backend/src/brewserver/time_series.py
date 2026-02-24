from abc import ABC, abstractmethod
from typing import Any, List, Tuple
from datetime import datetime

from log import logger
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import ASYNCHRONOUS
from retry import retry
from config import COLDBREW_VALVE_INTERVAL_SECONDS


class AbstractTimeSeries(ABC):

    @abstractmethod
    def healthcheck(self) -> bool:
        pass

    @abstractmethod
    def write_scale_data(self, weight: float, battery_pct: int, brew_id: str) -> None:
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
    def get_recent_weight_readings(self, duration_seconds: int = COLDBREW_VALVE_INTERVAL_SECONDS, start_time_filter: datetime | None = None) -> List[Tuple[datetime, float]]:
        """
        Read raw sequential weight values from InfluxDB.
        
        Args:
            duration_seconds: How many seconds of history to query
            start_time_filter: If provided, only include readings from this time onwards.
                              Any readings before this time will be filtered out.
            
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

    def healthcheck(self) -> bool:
        return self.influxdb.ping()

    def write_scale_data(self, weight: float, battery_pct: int, brew_id: str):
        """Write the current weight to the time series asynchronously."""
        # logger.info(f"writing influxdb data: {weight} {battery_pct}")
        p = Point("coldbrew").tag("brew_id", brew_id).field("weight_grams", weight).field("battery_pct", battery_pct)
        # Use ASYNCHRONOUS write to avoid blocking the control loop on network latency
        write_api = self.influxdb.write_api(write_options=ASYNCHRONOUS)
        write_api.write(bucket=self.bucket, record=p)


    @retry(tries=10, delay=4)
    def get_current_weight(self) -> float:
        query_api = self.influxdb.query_api()
        query = f'from(bucket: "{self.bucket}")\
            |> range(start: -10s)\
            |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")'
        tables = query_api.query(org=self.org, query=query)
        # for table in tables:
        #     for record in table.records:
        #         logger.info(f"Time: {record.get_time()}, Value: {record.get_value()}")

        # TODO handle empty case
        result = tables[-1].records[-1]
        return result.get_value()

    @retry(tries=10, delay=4)
    def get_recent_weight_readings(self, duration_seconds: int = COLDBREW_VALVE_INTERVAL_SECONDS, start_time_filter: datetime | None = None) -> List[Tuple[datetime, float]]:
        """
        Read raw sequential weight values from InfluxDB.
        
        Args:
            duration_seconds: How many seconds of history to query
            start_time_filter: If provided, only include readings from this time onwards.
                              Any readings before this time will be filtered out.
            
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
        
        # Filter out readings before start_time_filter if provided
        if start_time_filter is not None:
            readings = [(ts, wt) for ts, wt in readings if ts >= start_time_filter]
        
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
    def get_weight_readings_in_range(
        self, 
        start_time: datetime, 
        end_time: datetime
    ) -> List[Tuple[datetime, float]]:
        """
        Read raw sequential weight values from InfluxDB within a time range.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            List of (timestamp, weight) tuples sorted by time ascending
        """
        query_api = self.influxdb.query_api()
        
        # Calculate duration from start to end
        duration = end_time - start_time
        duration_str = f"-{int(duration.total_seconds())}s"
        
        query = f'from(bucket: "{self.bucket}")\
            |> range(start: {duration_str})\
            |> filter(fn: (r) => r._measurement == "coldbrew" and r._field == "weight_grams")'
        tables = query_api.query(org=self.org, query=query)
        
        readings: List[Tuple[datetime, float]] = []
        for table in tables:
            for record in table.records:
                timestamp = record.get_time()
                value = record.get_value()
                # Filter to only include readings within the time range
                if value is not None and start_time <= timestamp <= end_time:
                    readings.append((timestamp, value))
        
        # Sort by timestamp ascending
        readings.sort(key=lambda x: x[0])
        return readings

    def get_flow_rates_for_brew(
        self, 
        start_time: datetime, 
        end_time: datetime,
        window_seconds: float = COLDBREW_VALVE_INTERVAL_SECONDS
    ) -> List[float]:
        """
        Calculate flow rates for each time window during a brew.
        
        This method divides the brew duration into windows and calculates
        the flow rate for each window based on weight changes.
        
        Args:
            start_time: When the brew started
            end_time: When the brew ended
            window_seconds: Size of each time window for flow rate calculation
            
        Returns:
            List of flow rates (g/s) for each window
        """
        # Get all weight readings for the brew
        all_readings = self.get_weight_readings_in_range(start_time, end_time)
        
        if len(all_readings) < 2:
            logger.warning("Insufficient readings for flow rate calculation")
            return []
        
        flow_rates: List[float] = []
        
        # Calculate flow rate for each window
        # We use a sliding window approach
        i = 0
        n = len(all_readings)
        
        while i < n - 1:
            window_start_time = all_readings[i][0]
            window_end_time = window_start_time.replace(second=window_start_time.second + int(window_seconds))
            
            # Find readings within this window
            window_readings = []
            for j in range(i, n):
                ts, wt = all_readings[j]
                if ts <= window_end_time:
                    window_readings.append((ts, wt))
                else:
                    break
            
            # Calculate flow rate for this window if we have enough points
            if len(window_readings) >= 2:
                flow_rate = self.calculate_flow_rate_from_derivatives(window_readings)
                if flow_rate is not None:
                    flow_rates.append(flow_rate)
            
            # Move to next window (overlap slightly for smoother results)
            i = max(i + 1, len(window_readings) - 1 if window_readings else i + 1)
        
        return flow_rates
