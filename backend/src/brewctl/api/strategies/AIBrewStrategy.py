"""
Brew strategy that asks a local LLM what the valve should do next.

Deliberately gimmicky as a control algorithm -- the point is teaching. It is one
legible loop: gather real sensor state, serialize it into a prompt, POST it to a
chat-completions endpoint, parse structured JSON back, and move a physical valve
with the answer.

Notes for anyone reading this as the demo:

- The LLM is never allowed to stop the brew. The target-weight check below runs
  before the model is consulted, and a model that returns "STOP" anyway is
  downgraded to NOOP.
- Every failure path -- timeout, non-2xx, malformed JSON, an action outside the
  allowed set -- delegates to a plain DefaultBrewStrategy instead of raising, so
  an unreachable Ollama degrades the brew rather than ending it.
- In a dry run the brew clock is compressed (default 60x) but an LLM call still
  costs wall-clock seconds, so dry runs with this strategy are LLM-latency-bound
  rather than interval-bound. That is expected; do not scale the timeout.
"""
import json
import re
import threading
import time
from collections import deque
from typing import Any, Dict, Optional, Tuple

import httpx

from brewctl.core.config import *
from brewctl.api.config import *
from brewctl.core.model import ValveCommand, BrewStrategyType
from brewctl.core.log import logger
from .DefaultBrewStrategy import (
    AbstractBrewStrategy,
    DefaultBrewStrategy,
    register_strategy,
)


# The actions the model is allowed to pick. STOP is deliberately absent -- ending
# the brew is a Python decision, never the model's.
_ALLOWED_ACTIONS = {
    "FORWARD": ValveCommand.FORWARD,
    "BACKWARD": ValveCommand.BACKWARD,
    "NOOP": ValveCommand.NOOP,
}

# Flat on purpose: no $defs, no nesting. Sub-4B models comply well with flat
# schemas and degrade badly on nested ones. `action` is listed first so the
# grammar commits to the decision before spending tokens on the reason.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": sorted(_ALLOWED_ACTIONS)},
        "interval_seconds": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["action", "interval_seconds", "reason"],
    "additionalProperties": False,
}

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _coerce_float(value: Any, default: float) -> float:
    """Coerce a strategy param to float, tolerating the strings the frontend sends.

    The shared _extract_float rejects strings and silently returns its default,
    which would make every param on this strategy's form a no-op.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (list, tuple)) and value:
        return _coerce_float(value[0], default)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        logger.warning(f"Could not coerce {value!r} to float, using default: {default}")
        return default


def _coerce_str(value: Any, default: str) -> str:
    """Coerce a strategy param to a non-empty string, else the default."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and value:
        return _coerce_str(value[0], default)
    text = str(value).strip()
    return text or default


@register_strategy(BrewStrategyType.AI)
class AIBrewStrategy(AbstractBrewStrategy):
    """Delegates each valve decision to a small LLM over an OpenAI-compatible API."""

    def __init__(
        self,
        target_flow_rate: float,
        scale_interval: float,
        valve_interval: float,
        target_weight: float,
        vessel_weight: float,
        epsilon: float,
        model: str = None,
        base_url: str = None,
        timeout_seconds: float = None,
        temperature: float = 0.0,
        history_points: int = 12,
        min_interval: float = 5.0,
        max_interval: float = None,
        warmup: bool = True,
    ):
        self.target_flow_rate = target_flow_rate
        self.scale_interval = scale_interval
        self.valve_interval = valve_interval
        self.target_weight = target_weight
        self.vessel_weight = vessel_weight
        self.epsilon = epsilon
        self.coffee_target = target_weight - vessel_weight

        self.model = model if model is not None else BREWCTL_LLM_MODEL
        self.base_url = (base_url if base_url is not None else BREWCTL_LLM_BASE_URL).rstrip("/")
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else BREWCTL_LLM_TIMEOUT_SECONDS
        )
        self.temperature = temperature
        self.min_interval = min_interval
        self.max_interval = max_interval if max_interval is not None else valve_interval

        # Every failure path lands here rather than raising, so the brew survives
        # an Ollama that is down, slow, or talking nonsense.
        self.fallback = DefaultBrewStrategy(
            target_flow_rate=target_flow_rate,
            scale_interval=scale_interval,
            valve_interval=valve_interval,
            epsilon=epsilon,
            target_weight=target_weight,
            vessel_weight=vessel_weight,
        )

        # Self-contained history, so the strategy needs no injection of time_series
        # or the WeightBuffer to give the model context.
        self.history: deque = deque(maxlen=max(1, int(history_points)))
        self.started_at = time.monotonic()

        if warmup:
            self._start_warmup()

    # ----- construction from the API's param dicts -----

    @classmethod
    def get_params_schema(cls) -> Dict[str, Any]:
        return {
            "model": {
                "type": "string",
                "default": BREWCTL_LLM_MODEL,
                "label": "Model",
                "description": "Ollama model tag, e.g. llama3.2:3b or gemma2:2b",
            },
            "base_url": {
                "type": "string",
                "default": BREWCTL_LLM_BASE_URL,
                "label": "Base URL",
                "description": "OpenAI-compatible server; /v1/chat/completions is appended",
            },
            "temperature": {
                "type": "number",
                "default": 0.0,
                "label": "Temperature",
                "description": "0 for repeatable decisions",
            },
            "timeout_seconds": {
                "type": "number",
                "default": BREWCTL_LLM_TIMEOUT_SECONDS,
                "label": "Request Timeout (s)",
                "description": "Per-call timeout before falling back to the default strategy",
            },
            "history_points": {
                "type": "number",
                "default": 12,
                "label": "History Points",
                "description": "Recent readings shown to the model as context",
            },
            "min_interval": {
                "type": "number",
                "default": 5.0,
                "label": "Min Interval (s)",
                "description": "Floor on the wait the model asks for",
            },
            "max_interval": {
                "type": "number",
                "default": BREWCTL_VALVE_INTERVAL_SECONDS,
                "label": "Max Interval (s)",
                "description": "Ceiling on the wait the model asks for",
            },
        }

    @classmethod
    def from_params(
        cls, strategy_params: Dict[str, Any], base_params: Dict[str, Any]
    ) -> "AIBrewStrategy":
        valve_interval = float(
            base_params.get("valve_interval", BREWCTL_VALVE_INTERVAL_SECONDS)
        )
        return AIBrewStrategy(
            target_flow_rate=float(
                base_params.get("target_flow_rate", BREWCTL_TARGET_FLOW_RATE)
            ),
            scale_interval=float(
                base_params.get("scale_interval", BREWCTL_SCALE_READ_INTERVAL)
            ),
            valve_interval=valve_interval,
            target_weight=float(
                base_params.get("target_weight", BREWCTL_TARGET_WEIGHT_GRAMS)
            ),
            vessel_weight=float(
                base_params.get("vessel_weight", BREWCTL_VESSEL_WEIGHT_GRAMS)
            ),
            epsilon=float(base_params.get("epsilon", BREWCTL_EPSILON)),
            model=_coerce_str(strategy_params.get("model"), BREWCTL_LLM_MODEL),
            base_url=_coerce_str(strategy_params.get("base_url"), BREWCTL_LLM_BASE_URL),
            timeout_seconds=_coerce_float(
                strategy_params.get("timeout_seconds"), BREWCTL_LLM_TIMEOUT_SECONDS
            ),
            temperature=_coerce_float(strategy_params.get("temperature"), 0.0),
            history_points=int(_coerce_float(strategy_params.get("history_points"), 12)),
            min_interval=_coerce_float(strategy_params.get("min_interval"), 5.0),
            max_interval=_coerce_float(
                strategy_params.get("max_interval"), valve_interval
            ),
        )

    # ----- LLM plumbing -----

    def _start_warmup(self) -> None:
        """Fire a throwaway request so the model loads while the brew is still settling.

        The first call to a cold Ollama includes a 30s+ model load. Doing it here
        overlaps that with the brew's first scale readings instead of the first
        step. Daemon thread bounded by the httpx timeout, so it can neither block
        interpreter shutdown nor outlive the brew by much.
        """
        def _warm():
            try:
                self._post([{"role": "user", "content": "ok"}], max_tokens=1)
                logger.info(f"LLM warm-up complete for model {self.model}")
            except Exception as e:
                # Not fatal: the first real step will simply pay the load cost, or
                # fall back if the server is genuinely unreachable.
                logger.warning(f"LLM warm-up failed: {e}")

        threading.Thread(target=_warm, name="ai-strategy-warmup", daemon=True).start()

    def _post(self, messages, max_tokens: Optional[int] = None) -> Dict[str, Any]:
        """POST to the OpenAI-compatible chat-completions endpoint and return the body."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        else:
            # llama.cpp turns this into a GBNF grammar, so the model is
            # mechanically unable to emit non-conforming tokens. The JSON-parse
            # fallback below still stays in, for servers that ignore it.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "valve_decision",
                    "strict": True,
                    "schema": _RESPONSE_SCHEMA,
                },
            }

        headers = {"Content-Type": "application/json"}
        if BREWCTL_LLM_API_KEY:
            headers["Authorization"] = f"Bearer {BREWCTL_LLM_API_KEY}"

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/v1/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()

    def _build_messages(self, flow_rate: Optional[float], current_weight: Optional[float]):
        coffee_weight = (
            (current_weight - self.vessel_weight) if current_weight is not None else None
        )
        system = (
            "You control a cold brew coffee valve. Each cycle you choose one action and "
            "how long to wait before deciding again.\n"
            f"Target flow rate: {self.target_flow_rate:.4f} g/s "
            f"(tolerance +/- {self.epsilon:.4f}).\n"
            "FORWARD opens the valve one step (more flow). BACKWARD closes it one step "
            "(less flow). NOOP leaves it where it is.\n"
            "If flow is below target choose FORWARD, if above choose BACKWARD, if within "
            "tolerance choose NOOP. If flow rate is unknown, choose NOOP.\n"
            f"interval_seconds must be between {self.min_interval:g} and "
            f"{self.max_interval:g}.\n"
            "Reply with JSON only: "
            '{"action": "FORWARD"|"BACKWARD"|"NOOP", "interval_seconds": <number>, '
            '"reason": "<max 12 words>"}'
        )
        lines = [
            f"elapsed_s: {time.monotonic() - self.started_at:.1f}",
            f"flow_rate: {'unknown' if flow_rate is None else f'{flow_rate:.4f} g/s'}",
            f"coffee_weight: {'unknown' if coffee_weight is None else f'{coffee_weight:.1f} g'}",
            f"target_weight: {self.coffee_target:.1f} g",
        ]
        if self.history:
            lines.append("recent history (oldest first):")
            for point in self.history:
                flow = point["flow_rate"]
                lines.append(
                    f"  t={point['elapsed_s']:.1f}s "
                    f"weight={point['weight_g'] if point['weight_g'] is not None else 'unknown'} "
                    f"flow={'unknown' if flow is None else f'{flow:.4f}'} "
                    f"action={point['action']}"
                )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(lines)},
        ]

    @staticmethod
    def _parse_content(content: str) -> Dict[str, Any]:
        """Parse the model's message content as JSON, tolerating ```json fences."""
        fenced = _FENCE_RE.match(content or "")
        if fenced:
            content = fenced.group(1)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
        return parsed

    def _record(
        self,
        flow_rate: Optional[float],
        current_weight: Optional[float],
        action: ValveCommand,
    ) -> None:
        coffee_weight = (
            round(current_weight - self.vessel_weight, 1)
            if current_weight is not None
            else None
        )
        self.history.append(
            {
                "elapsed_s": time.monotonic() - self.started_at,
                "weight_g": coffee_weight,
                "flow_rate": flow_rate,
                # The name, not the enum or its int value: this dict is
                # serialized into the prompt, and FORWARD reads better than 1.
                "action": action.name,
            }
        )

    # ----- the control step -----

    def step(
        self, flow_rate: Optional[float], current_weight: Optional[float]
    ) -> Tuple[ValveCommand, int]:
        # Target weight is checked in Python, before the model is consulted and
        # regardless of what it would have said. The LLM cannot end a brew, and
        # cannot keep one running past its target.
        coffee_weight = (
            (current_weight - self.vessel_weight) if current_weight is not None else None
        )
        if coffee_weight is not None and coffee_weight >= self.coffee_target:
            logger.info(
                f"target weight reached: {coffee_weight}g (coffee) >= "
                f"{self.coffee_target}g (coffee target)"
            )
            return ValveCommand.STOP, 0

        try:
            body = self._post(self._build_messages(flow_rate, current_weight))
            content = body["choices"][0]["message"]["content"]
            decision = self._parse_content(content)

            raw_action = str(decision.get("action", "")).strip().upper()
            if raw_action == "STOP":
                # The model does not get to end the brew. Treat it as "do nothing"
                # rather than as an error -- the weight check above is the only
                # thing that stops a brew.
                logger.warning("LLM returned STOP, which it is not allowed to do; treating as NOOP")
                raw_action = "NOOP"
            if raw_action not in _ALLOWED_ACTIONS:
                raise ValueError(f"invalid action: {decision.get('action')!r}")
            action = _ALLOWED_ACTIONS[raw_action]

            interval = _coerce_float(decision.get("interval_seconds"), self.valve_interval)
            interval = max(self.min_interval, min(self.max_interval, interval))

            reason = str(decision.get("reason", "")).strip()
            logger.info(f"LLM decision: {raw_action} for {interval:g}s -- {reason}")

            self._record(flow_rate, current_weight, action)
            return action, int(interval)
        except Exception as e:
            logger.warning(f"LLM step failed ({type(e).__name__}: {e}), falling back to default strategy")
            action, interval = self.fallback.step(flow_rate, current_weight)
            self._record(flow_rate, current_weight, action)
            return action, interval
