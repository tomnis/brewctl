"""
Unit tests for server helper functions: serialize_status, _build_base_params,
_get_default_base_params, and ConnectionManager.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewserver.server import serialize_status, _build_base_params, ConnectionManager
from brewserver.model import StartBrewRequest, Brew, BrewState


class TestSerializeStatus:
    """Tests for the serialize_status helper."""

    def test_none_input(self):
        assert serialize_status(None) is None

    def test_empty_dict(self):
        assert serialize_status({}) == {}

    def test_no_datetime_values(self):
        d = {"status": "ok", "count": 42}
        assert serialize_status(d) == {"status": "ok", "count": 42}

    def test_datetime_converted_to_iso(self):
        dt = datetime(2026, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        d = {"time_started": dt, "name": "test"}
        result = serialize_status(d)
        assert result["time_started"] == dt.isoformat()
        assert result["name"] == "test"

    def test_multiple_datetime_fields(self):
        dt1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        dt2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        d = {"start": dt1, "end": dt2, "value": 5}
        result = serialize_status(d)
        assert result["start"] == dt1.isoformat()
        assert result["end"] == dt2.isoformat()
        assert result["value"] == 5

    def test_none_values_preserved(self):
        d = {"time_completed": None, "status": "brewing"}
        result = serialize_status(d)
        assert result["time_completed"] is None
        assert result["status"] == "brewing"


class TestBuildBaseParams:
    """Tests for _build_base_params."""

    def test_extracts_all_fields_from_request(self):
        # StartBrewRequest is a @dataclass+BaseModel hybrid that's broken in pydantic v2
        # Use a mock with the expected attributes instead
        req = MagicMock()
        req.target_flow_rate = 0.1
        req.scale_interval = 1.0
        req.valve_interval = 60
        req.target_weight = 1000
        req.vessel_weight = 200
        req.epsilon = 0.01
        
        params = _build_base_params(req)
        assert params["target_flow_rate"] == 0.1
        assert params["scale_interval"] == 1.0
        assert params["valve_interval"] == 60
        assert params["target_weight"] == 1000
        assert params["vessel_weight"] == 200
        assert params["epsilon"] == 0.01

    def test_returns_all_expected_keys(self):
        req = MagicMock()
        req.target_flow_rate = 0.05
        req.scale_interval = 0.5
        req.valve_interval = 90
        req.target_weight = 1337
        req.vessel_weight = 229
        req.epsilon = 0.008
        
        params = _build_base_params(req)
        assert "target_flow_rate" in params
        assert "scale_interval" in params
        assert "valve_interval" in params
        assert "target_weight" in params
        assert "vessel_weight" in params
        assert "epsilon" in params


class TestConnectionManager:
    """Tests for the WebSocket ConnectionManager."""

    def test_initial_state(self):
        cm = ConnectionManager()
        assert cm.active_connections == []

    @pytest.mark.anyio
    async def test_connect_adds_websocket(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        assert ws in cm.active_connections
        ws.accept.assert_awaited_once()

    @pytest.mark.anyio
    async def test_disconnect_removes_websocket(self):
        cm = ConnectionManager()
        ws = AsyncMock()
        await cm.connect(ws)
        cm.disconnect(ws)
        assert ws not in cm.active_connections

    @pytest.mark.anyio
    async def test_broadcast_sends_to_all(self):
        cm = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await cm.connect(ws1)
        await cm.connect(ws2)
        
        msg = {"status": "brewing"}
        await cm.broadcast(msg)
        
        ws1.send_json.assert_awaited_once_with(msg)
        ws2.send_json.assert_awaited_once_with(msg)

    @pytest.mark.anyio
    async def test_broadcast_removes_failed_connection(self):
        cm = ConnectionManager()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = Exception("connection lost")
        
        await cm.connect(ws_good)
        await cm.connect(ws_bad)
        
        await cm.broadcast({"status": "test"})
        
        # Bad connection should be removed
        assert ws_bad not in cm.active_connections
        assert ws_good in cm.active_connections

    @pytest.mark.anyio
    async def test_broadcast_empty_connections(self):
        cm = ConnectionManager()
        # Should not raise
        await cm.broadcast({"status": "test"})


class TestBrewDataclass:
    """Tests for the Brew dataclass."""

    def test_brew_creation(self):
        now = datetime.now(timezone.utc)
        brew = Brew(
            id="test-123",
            status=BrewState.BREWING,
            time_started=now,
            target_weight=1337,
            vessel_weight=229,
        )
        assert brew.id == "test-123"
        assert brew.status == BrewState.BREWING
        assert brew.time_started == now
        assert brew.time_completed is None
        assert brew.error_message is None

    def test_brew_with_error(self):
        now = datetime.now(timezone.utc)
        brew = Brew(
            id="test-456",
            status=BrewState.ERROR,
            time_started=now,
            target_weight=1337,
            vessel_weight=229,
            error_message="scale disconnected",
        )
        assert brew.error_message == "scale disconnected"

    def test_brew_completed(self):
        now = datetime.now(timezone.utc)
        later = now
        brew = Brew(
            id="test-789",
            status=BrewState.COMPLETED,
            time_started=now,
            time_completed=later,
            target_weight=1337,
            vessel_weight=229,
        )
        assert brew.time_completed == later

    def test_brew_status_mutable(self):
        now = datetime.now(timezone.utc)
        brew = Brew(id="x", status=BrewState.BREWING, time_started=now, target_weight=100, vessel_weight=0)
        brew.status = BrewState.PAUSED
        assert brew.status == BrewState.PAUSED


class TestStartBrewRequest:
    """Tests for the StartBrewRequest model.
    
    Note: StartBrewRequest uses @dataclass + BaseModel which is incompatible
    with pydantic v2 direct instantiation. We test it via the API instead.
    """

    def test_start_brew_request_has_expected_fields(self):
        """Verify the class has the expected field definitions."""
        fields = StartBrewRequest.__dataclass_fields__
        assert "target_flow_rate" in fields
        assert "scale_interval" in fields
        assert "valve_interval" in fields
        assert "target_weight" in fields
        assert "vessel_weight" in fields
        assert "epsilon" in fields
        assert "strategy" in fields
        assert "strategy_params" in fields

    def test_start_brew_request_field_defaults(self):
        """Verify default values are set on the pydantic model fields."""
        # The @dataclass+BaseModel hybrid stores defaults in pydantic fields, not dataclass fields
        pydantic_fields = StartBrewRequest.__pydantic_fields__
        assert pydantic_fields["strategy"].default.value == "default"
        assert pydantic_fields["strategy_params"].default == {}
