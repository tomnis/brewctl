"""Prometheus metrics shared by both services.

Every metric for *both* modes is declared here. An unset gauge simply never
appears in a given process's output, and keeping one file is what stops the
names from drifting apart between the api and the hardware service.

Two deliberate choices:

- A private ``CollectorRegistry`` rather than the default one. The default
  registry auto-registers ``python_gc_*`` (which installs a ``gc.callbacks``
  hook), ``python_info`` and ``process_*`` -- roughly fifteen extra series and a
  GC hook inside the hardware process on a 416 MB Pi Zero 2 W.
- Metrics are declared once at import. The module cache is what prevents
  ``Duplicated timeseries in CollectorRegistry`` when several test modules
  import this; never declare them inside a function.

Values that are only meaningful *now* (scale data age, valve position) are
registered with ``set_function`` and evaluated at scrape time. Setting them from
a write path would make them ~0 by construction and freeze them exactly when the
thing they measure stops working.
"""

from typing import Callable, Optional

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    generate_latest,
)

REGISTRY = CollectorRegistry()

# Callables registered by whichever service imported us, consulted at scrape
# time. Kept out of the metric objects so reset_metrics() can rebuild those
# without losing the wiring.
_scale_age_source: Optional[Callable[[], Optional[float]]] = None
_valve_position_source: Optional[Callable[[], Optional[float]]] = None


def _declare() -> None:
    """(Re)declare every metric against the current registry."""
    global flow_rate, flow_rate_error, valve_position, valve_commands
    global brews, scale_data_age, influx_write_failures
    global watchdog_trips, scale_connected, scale_healthy
    global scale_reconnects, sse_clients

    # --- api service ---------------------------------------------------------
    flow_rate = Gauge(
        "brewctl_flow_rate_grams_per_second",
        "Flow rate measured by the running brew. Frozen at its last live value "
        "while the brew is PAUSED.",
        ["brew_id"],
        registry=REGISTRY,
    )
    flow_rate_error = Gauge(
        "brewctl_flow_rate_error",
        "target_flow_rate - measured flow rate for the running brew. Frozen at "
        "its last live value while the brew is PAUSED.",
        registry=REGISTRY,
    )
    valve_position = Gauge(
        "brewctl_valve_position",
        "Current valve position in steps. Read at scrape time; survives the end "
        "of a brew because the physical valve does too.",
        registry=REGISTRY,
    )
    valve_position.set_function(_read_valve_position)
    valve_commands = Counter(
        "brewctl_valve_commands",
        "Valve commands returned by a strategy and actually applied.",
        ["command"],
        registry=REGISTRY,
    )
    brews = Counter(
        "brewctl_brews",
        "Brews by terminal outcome.",
        ["outcome"],
        registry=REGISTRY,
    )
    scale_data_age = Gauge(
        "brewctl_scale_data_age_seconds",
        "Age of the newest reading in the in-process weight buffer, at scrape time.",
        registry=REGISTRY,
    )
    scale_data_age.set_function(_read_scale_age)
    influx_write_failures = Counter(
        "brewctl_influx_write_failures",
        "InfluxDB writes that raised.",
        registry=REGISTRY,
    )

    # --- hardware service ----------------------------------------------------
    watchdog_trips = Counter(
        "brewctl_watchdog_trips",
        "Times the hardware watchdog fired and returned the valve to start.",
        registry=REGISTRY,
    )
    scale_connected = Gauge(
        "brewctl_scale_connected",
        "1 when the scale reports connected, 0 otherwise.",
        registry=REGISTRY,
    )
    scale_healthy = Gauge(
        "brewctl_scale_healthy",
        "1 when the scale is connected AND has delivered a reading recently. A "
        "connected-but-silent scale reports scale_connected 1 and this 0.",
        registry=REGISTRY,
    )
    scale_reconnects = Counter(
        "brewctl_scale_reconnects",
        "Reconnect cycles started by the scale monitor. One cycle is a whole "
        "reconnect_with_backoff() call, not an individual attempt.",
        registry=REGISTRY,
    )
    sse_clients = Gauge(
        "brewctl_sse_clients",
        "Currently connected SSE clients.",
        ["stream"],
        registry=REGISTRY,
    )


def _read_scale_age() -> float:
    if _scale_age_source is None:
        return float("nan")
    age = _scale_age_source()
    return float("nan") if age is None else age


def _read_valve_position() -> float:
    if _valve_position_source is None:
        return float("nan")
    position = _valve_position_source()
    return float("nan") if position is None else float(position)


def set_scale_age_source(source: Callable[[], Optional[float]]) -> None:
    """Register the scrape-time source for brewctl_scale_data_age_seconds."""
    global _scale_age_source
    _scale_age_source = source


def set_valve_position_source(source: Callable[[], Optional[float]]) -> None:
    """Register the scrape-time source for brewctl_valve_position."""
    global _valve_position_source
    _valve_position_source = source


def clear_brew_metrics() -> None:
    """Drop per-brew series when a brew ends.

    A gauge keeps its last value forever, so a finished brew would otherwise
    leave a live-looking flow rate on the dashboard. Clearing the labelled
    flow-rate gauge doubles as the cardinality guard -- brew_id is a uuid, and
    at most one series should be live at a time.

    The scrape-time gauges (valve position, scale data age) are deliberately
    untouched: they re-read their source on every scrape.
    """
    flow_rate.clear()
    flow_rate_error.set(0)


def reset_metrics() -> None:
    """Rebuild the registry from scratch. For test fixtures.

    prometheus_client has no public reset for an unlabeled counter -- .clear()
    only drops label children -- so the whole registry is rebuilt instead of
    poking at private counter state.
    """
    global REGISTRY
    REGISTRY = CollectorRegistry()
    _declare()


def metrics_response() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


_declare()
