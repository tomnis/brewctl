"""
Tests for AIBrewStrategy -- the LLM-guided valve strategy.

Every test patches httpx.Client inside the strategy module and constructs with
warmup=False, so nothing here touches the network.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from brewctl.api.strategies.AIBrewStrategy import AIBrewStrategy
from brewctl.api.strategies.DefaultBrewStrategy import DefaultBrewStrategy
from brewctl.core.model import BrewStrategyType, ValveCommand


BASE_PARAMS = {
    "target_flow_rate": 0.05,
    "scale_interval": 0.5,
    "valve_interval": 90,
    "target_weight": 1337,
    "vessel_weight": 229,
    "epsilon": 0.008,
}


def make_strategy(**kwargs):
    params = dict(
        target_flow_rate=0.05,
        scale_interval=0.5,
        valve_interval=90,
        target_weight=1337,
        vessel_weight=229,
        epsilon=0.008,
        warmup=False,
    )
    params.update(kwargs)
    return AIBrewStrategy(**params)


def llm_response(content: str):
    """A fake httpx.Client whose POST returns `content` as the model's message."""
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    client = MagicMock()
    client.post.return_value = response
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


def failing_client(exc: Exception):
    client = MagicMock()
    client.post.side_effect = exc
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    return client


def patch_client(client):
    return patch(
        "brewctl.api.strategies.AIBrewStrategy.httpx.Client", return_value=client
    )


class TestDecisions:
    @pytest.mark.parametrize(
        "action,expected",
        [
            ("FORWARD", ValveCommand.FORWARD),
            ("BACKWARD", ValveCommand.BACKWARD),
            ("NOOP", ValveCommand.NOOP),
        ],
    )
    def test_valid_response_maps_to_valve_command(self, action, expected):
        strategy = make_strategy()
        content = f'{{"action": "{action}", "interval_seconds": 30, "reason": "flow off target"}}'
        with patch_client(llm_response(content)):
            assert strategy.step(0.01, 300.0) == (expected, 30)

    def test_json_fences_are_tolerated(self):
        strategy = make_strategy()
        content = '```json\n{"action": "FORWARD", "interval_seconds": 20, "reason": "slow"}\n```'
        with patch_client(llm_response(content)):
            assert strategy.step(0.01, 300.0) == (ValveCommand.FORWARD, 20)

    def test_interval_clamped_to_max(self):
        strategy = make_strategy(min_interval=5, max_interval=60)
        content = '{"action": "NOOP", "interval_seconds": 9000, "reason": "nap"}'
        with patch_client(llm_response(content)):
            assert strategy.step(0.05, 300.0) == (ValveCommand.NOOP, 60)

    def test_interval_clamped_to_min(self):
        strategy = make_strategy(min_interval=5, max_interval=60)
        content = '{"action": "NOOP", "interval_seconds": 0, "reason": "eager"}'
        with patch_client(llm_response(content)):
            assert strategy.step(0.05, 300.0) == (ValveCommand.NOOP, 5)

    def test_model_cannot_stop_the_brew(self):
        """STOP is Python's decision. A model that asks for it gets NOOP."""
        strategy = make_strategy()
        content = '{"action": "STOP", "interval_seconds": 10, "reason": "done i think"}'
        with patch_client(llm_response(content)):
            command, _interval = strategy.step(0.05, 300.0)
        assert command == ValveCommand.NOOP

    def test_history_grows_and_is_bounded(self):
        strategy = make_strategy(history_points=2)
        content = '{"action": "NOOP", "interval_seconds": 10, "reason": "steady"}'
        with patch_client(llm_response(content)):
            for _ in range(4):
                strategy.step(0.05, 300.0)
        assert len(strategy.history) == 2
        # Serialized into the prompt, so it must be a plain string.
        assert strategy.history[-1]["action"] == "NOOP"


class TestSafety:
    def test_target_weight_stops_without_consulting_the_model(self):
        strategy = make_strategy()
        client = llm_response('{"action": "FORWARD", "interval_seconds": 10, "reason": "more"}')
        with patch_client(client):
            # 1600 - 229 vessel = 1371g coffee, past the 1108g target
            assert strategy.step(0.05, 1600.0) == (ValveCommand.STOP, 0)
        assert client.post.call_count == 0


class TestFallback:
    """Every failure path keeps the brew running on DefaultBrewStrategy."""

    def expected_default(self, flow_rate, weight):
        return DefaultBrewStrategy(**BASE_PARAMS).step(flow_rate, weight)

    def test_malformed_json_falls_back(self):
        strategy = make_strategy()
        with patch_client(llm_response("I think you should open it a bit?")):
            assert strategy.step(0.01, 300.0) == self.expected_default(0.01, 300.0)

    def test_invalid_action_falls_back(self):
        strategy = make_strategy()
        content = '{"action": "WIGGLE", "interval_seconds": 10, "reason": "why not"}'
        with patch_client(llm_response(content)):
            assert strategy.step(0.01, 300.0) == self.expected_default(0.01, 300.0)

    def test_http_error_falls_back(self):
        strategy = make_strategy()
        response = MagicMock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        client = MagicMock()
        client.post.return_value = response
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        with patch_client(client):
            assert strategy.step(0.01, 300.0) == self.expected_default(0.01, 300.0)

    def test_timeout_falls_back(self):
        strategy = make_strategy()
        with patch_client(failing_client(httpx.ReadTimeout("too slow"))):
            assert strategy.step(0.01, 300.0) == self.expected_default(0.01, 300.0)

    def test_connect_error_falls_back(self):
        strategy = make_strategy()
        with patch_client(failing_client(httpx.ConnectError("ollama is down"))):
            assert strategy.step(0.9, 300.0) == self.expected_default(0.9, 300.0)

    def test_fallback_still_records_history(self):
        strategy = make_strategy()
        with patch_client(failing_client(httpx.ConnectError("down"))):
            strategy.step(0.01, 300.0)
        assert len(strategy.history) == 1


class TestParams:
    def test_string_params_are_coerced_not_defaulted(self):
        """The frontend posts every strategy_param as a string."""
        strategy = AIBrewStrategy.from_params(
            {
                "model": "gemma2:2b",
                "base_url": "http://odroid:11434",
                "temperature": "0.3",
                "timeout_seconds": "9.5",
                "history_points": "4",
                "min_interval": "2",
                "max_interval": "40",
            },
            BASE_PARAMS,
        )
        assert strategy.model == "gemma2:2b"
        assert strategy.base_url == "http://odroid:11434"
        assert strategy.temperature == 0.3
        assert strategy.timeout_seconds == 9.5
        assert strategy.history.maxlen == 4
        assert strategy.min_interval == 2
        assert strategy.max_interval == 40

    def test_blank_and_junk_params_use_defaults(self):
        strategy = AIBrewStrategy.from_params(
            {"model": "  ", "base_url": "", "min_interval": "not a number"},
            BASE_PARAMS,
        )
        assert strategy.model
        assert strategy.base_url
        assert strategy.min_interval == 5.0

    def test_base_url_trailing_slash_is_stripped(self):
        strategy = AIBrewStrategy.from_params(
            {"base_url": "http://odroid:11434/"}, BASE_PARAMS
        )
        assert strategy.base_url == "http://odroid:11434"

    def test_max_interval_defaults_to_valve_interval(self):
        strategy = AIBrewStrategy.from_params({}, BASE_PARAMS)
        assert strategy.max_interval == 90

    def test_registered_under_ai(self):
        from brewctl.api.brew_strategy import BREW_STRATEGY_REGISTRY

        assert BREW_STRATEGY_REGISTRY[BrewStrategyType.AI] is AIBrewStrategy

    def test_params_schema_covers_every_form_field(self):
        schema = AIBrewStrategy.get_params_schema()
        for key in (
            "model",
            "base_url",
            "temperature",
            "timeout_seconds",
            "history_points",
            "min_interval",
            "max_interval",
        ):
            assert key in schema

    def test_warm_start_is_a_noop(self):
        """Stateless with respect to the operating point, so a switch needs no seeding."""
        strategy = make_strategy()
        assert strategy.warm_start(5, 0.05) is None


class TestRequest:
    def test_posts_flat_json_schema_to_chat_completions(self):
        strategy = make_strategy(base_url="http://odroid:11434", model="gemma2:2b")
        client = llm_response('{"action": "NOOP", "interval_seconds": 10, "reason": "ok"}')
        with patch_client(client):
            strategy.step(0.05, 300.0)

        url = client.post.call_args.args[0]
        body = client.post.call_args.kwargs["json"]
        assert url == "http://odroid:11434/v1/chat/completions"
        assert body["model"] == "gemma2:2b"
        assert body["stream"] is False
        assert body["temperature"] == 0.0
        schema = body["response_format"]["json_schema"]["schema"]
        # Flat on purpose -- sub-4B models comply badly with nested schemas.
        assert "$defs" not in schema
        assert list(schema["properties"]) == ["action", "interval_seconds", "reason"]
        # The model is never offered STOP as a choice.
        assert "STOP" not in schema["properties"]["action"]["enum"]

    def test_no_auth_header_without_a_key(self):
        strategy = make_strategy()
        client = llm_response('{"action": "NOOP", "interval_seconds": 10, "reason": "ok"}')
        with patch_client(client):
            strategy.step(0.05, 300.0)
        assert "Authorization" not in client.post.call_args.kwargs["headers"]

    def test_auth_header_when_a_key_is_set(self):
        strategy = make_strategy()
        client = llm_response('{"action": "NOOP", "interval_seconds": 10, "reason": "ok"}')
        with (
            patch_client(client),
            patch("brewctl.api.strategies.AIBrewStrategy.BREWCTL_LLM_API_KEY", "sekrit"),
        ):
            strategy.step(0.05, 300.0)
        assert client.post.call_args.kwargs["headers"]["Authorization"] == "Bearer sekrit"


class TestSafetyGuard:
    """The two decisions the model is not allowed to get wrong.

    Both were found by benchmarking at 10 reps: predictive-mode models answered
    FORWARD on an unknown flow rate (having invented one from the history) and
    NOOP on a 5.0 g/s runaway (having read a rising history as "trending toward
    the band"). The prompt was fixed too, but only this guard makes them
    impossible.
    """

    @pytest.mark.parametrize("action", ["FORWARD", "BACKWARD", "NOOP"])
    def test_unknown_flow_is_forced_to_noop(self, action):
        strategy = make_strategy()
        content = f'{{"action": "{action}", "interval_seconds": 30, "reason": "x"}}'
        with patch_client(llm_response(content)):
            command, _ = strategy.step(None, 500)
        assert command == ValveCommand.NOOP

    @pytest.mark.parametrize("action", ["FORWARD", "NOOP"])
    def test_runaway_flow_is_forced_backward(self, action):
        strategy = make_strategy()
        content = f'{{"action": "{action}", "interval_seconds": 30, "reason": "x"}}'
        with patch_client(llm_response(content)):
            command, _ = strategy.step(5.0, 500)
        assert command == ValveCommand.BACKWARD

    def test_ceiling_is_a_multiple_of_target(self):
        strategy = make_strategy(target_flow_rate=0.05, max_flow_rate_multiple=4.0)
        assert strategy.max_flow_rate == pytest.approx(0.20)

    def test_flow_below_the_ceiling_is_left_to_the_model(self):
        """0.09 g/s is far too fast but not a runaway -- the model still decides."""
        strategy = make_strategy()
        content = '{"action": "NOOP", "interval_seconds": 30, "reason": "x"}'
        with patch_client(llm_response(content)):
            command, _ = strategy.step(0.09, 500)
        assert command == ValveCommand.NOOP

    def test_guard_is_inert_on_normal_readings(self):
        strategy = make_strategy()
        content = '{"action": "FORWARD", "interval_seconds": 30, "reason": "x"}'
        with patch_client(llm_response(content)):
            command, _ = strategy.step(0.041, 500)
        assert command == ValveCommand.FORWARD

    def test_guard_applies_to_the_fallback_path_too(self):
        """A different code path is not a trusted one."""
        strategy = make_strategy()
        with patch_client(failing_client(httpx.ConnectError("down"))):
            command, _ = strategy.step(5.0, 500)
        assert command == ValveCommand.BACKWARD

    def test_guard_does_not_block_the_target_weight_stop(self):
        """STOP comes from Python before the model is consulted; the guard must not eat it."""
        strategy = make_strategy()
        with patch_client(llm_response('{"action": "NOOP", "interval_seconds": 30, "reason": "x"}')):
            command, _ = strategy.step(None, 1337 + 229)
        assert command == ValveCommand.STOP


class TestPredictivePrompt:
    def test_predicted_flow_rate_is_nullable(self):
        from brewctl.api.strategies.AIBrewStrategy import _PREDICTIVE_SCHEMA

        assert _PREDICTIVE_SCHEMA["properties"]["predicted_flow_rate"]["type"] == [
            "number",
            "null",
        ]

    def test_trend_override_is_left_unbounded(self):
        """Bounding it was measured and reverted -- see the comment in _build_messages.

        Explicit magnitude bounds did not stop either model opening the valve on a
        runaway, and cost qwen3.5:9b its dead-time behaviour. Magnitude safety is
        _guard()'s job; this line stays about trend only.
        """
        strategy = make_strategy(predictive=True)
        system = strategy._build_messages(0.041, 500)[0]["content"]
        assert "already moving toward it" in system
        assert "0.0260" not in system and "0.0740" not in system

    def test_unknown_flow_rule_precedes_the_band_rules(self):
        strategy = make_strategy(predictive=True)
        system = strategy._build_messages(None, 500)[0]["content"]
        assert system.index("unknown") < system.index("predicted_flow_rate <")
