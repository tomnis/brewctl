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

# Predictive variant. `predicted_flow_rate` deliberately comes *first*: the grammar
# emits fields in schema order, so the model commits to a prediction before it
# picks an action, and the action is then conditioned on that number. It is
# chain-of-thought reduced to a single token-cheap number -- the useful part of
# thinking without the 900-token trace a reasoning model spends on it.
_PREDICTIVE_SCHEMA = {
    "type": "object",
    "properties": {
        # Nullable on purpose. A required *number* here forced the model to invent
        # a prediction when flow_rate was unknown -- it extrapolated the history,
        # applied the band rule to that invention, and returned FORWARD on a
        # reading it never actually had. Allowing null lets "unknown" survive the
        # grammar instead of being laundered into a number.
        "predicted_flow_rate": {"type": ["number", "null"]},
        "action": {"type": "string", "enum": sorted(_ALLOWED_ACTIONS)},
        "interval_seconds": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["predicted_flow_rate", "action", "interval_seconds", "reason"],
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
        history_points: int = 3,
        min_interval: float = 5.0,
        max_interval: float = None,
        predictive: bool = False,
        dead_time_seconds: float = 120.0,
        max_flow_rate_multiple: float = 4.0,
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
        # Ask the model to predict the next flow rate before acting, to compensate
        # for the coffee bed's dead time. See _build_messages.
        self.predictive = predictive
        self.dead_time_seconds = dead_time_seconds
        # Hard ceiling for the Python guard in step(). Above this the model does not
        # get a vote: a runaway flow closes the valve whatever it says.
        self.max_flow_rate = target_flow_rate * max(1.0, max_flow_rate_multiple)
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
                "default": 3,
                "label": "History Points",
                "description": "Recent readings as context; more is measurably worse, see docs",
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
            "predictive": {
                "type": "string",
                "default": "false",
                "label": "Predictive Mode",
                "description": "true to predict next flow before acting (dead-time compensation)",
            },
            "dead_time_seconds": {
                "type": "number",
                "default": 120.0,
                "label": "Bed Dead Time (s)",
                "description": "How long a valve change takes to show up in flow",
            },
            "max_flow_rate_multiple": {
                "type": "number",
                "default": 4.0,
                "label": "Max Flow (x target)",
                "description": "Above this multiple of target, Python forces BACKWARD",
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
            predictive=str(strategy_params.get("predictive", "")).strip().lower()
            in ("1", "true", "yes", "on"),
            dead_time_seconds=_coerce_float(
                strategy_params.get("dead_time_seconds"), 120.0
            ),
            max_flow_rate_multiple=_coerce_float(
                strategy_params.get("max_flow_rate_multiple"), 4.0
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
            # Suppress chain-of-thought on models that have a thinking mode.
            # Measured on qwen3.5:9b: 30s without, 246s and 935 tokens with, for
            # the same one-line decision. A thinking model left unconstrained
            # exceeds any sane timeout and falls back every step. Servers that do
            # not know the field ignore it.
            "reasoning_effort": "none",
            # temperature 0 alone does not make llama.cpp reproducible -- float
            # non-associativity and batch composition still move sampling between
            # runs, and models were observed answering FORWARD and BACKWARD to
            # identical input. A fixed seed pins it, which matters here because a
            # control loop that emits different commands for the same state is
            # not debuggable.
            "seed": 0,
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
                    "schema": _PREDICTIVE_SCHEMA if self.predictive else _RESPONSE_SCHEMA,
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
        # The band is computed here, not by the model. Every model benchmarked --
        # including a 9B -- failed the "just inside the tolerance edge" cases when
        # asked to derive it from "target +/- epsilon", and a 9B allowed to think
        # spent its first reasoning step doing exactly this subtraction. Handing it
        # two literal numbers removes the arithmetic from the model's job entirely.
        low = self.target_flow_rate - self.epsilon
        high = self.target_flow_rate + self.epsilon
        common = (
            "You control a cold brew coffee valve. Each cycle you choose one action and "
            "how long to wait before deciding again.\n"
            "FORWARD opens the valve one step (more flow). BACKWARD closes it one step "
            "(less flow). NOOP leaves it where it is.\n"
            f"The acceptable flow_rate band is {low:.4f} to {high:.4f} g/s.\n"
        )
        limits = (
            f"interval_seconds must be between {self.min_interval:g} and "
            f"{self.max_interval:g}.\n"
        )
        if self.predictive:
            # Dead-time compensation. A valve step takes ~dead_time_seconds to show
            # up in the flow, because the water has to work through the bed. Acting
            # on the instantaneous reading therefore stacks corrections that have
            # not landed yet, and the loop oscillates. Asking for the prediction
            # first -- and ordering it first in the schema -- makes the model commit
            # to where the flow is heading before it picks an action.
            system = (
                common
                + f"A valve change takes about {self.dead_time_seconds:g} seconds to show up in "
                "flow_rate, because the water must work through the coffee bed. Recent "
                "actions in the history may not have taken effect yet.\n"
                "If flow_rate is unknown, set predicted_flow_rate to null and choose "
                "NOOP. Do not guess a value from the history: this rule wins over "
                "every rule below.\n"
                "Otherwise estimate predicted_flow_rate: what flow_rate will be at the next "
                "cycle, given the trend in the history and any recent action still "
                "arriving. Then apply exactly one rule to your prediction:\n"
                f"  predicted_flow_rate < {low:.4f}  -> FORWARD\n"
                f"  predicted_flow_rate > {high:.4f}  -> BACKWARD\n"
                f"  predicted_flow_rate between {low:.4f} and {high:.4f} (inclusive) -> NOOP\n"
                # Deliberately unbounded, having measured the alternative. Adding
                # explicit magnitude bounds here scored *worse* on 10 reps: it did
                # not stop either model opening the valve on a 5.0 g/s runaway, and
                # it cost qwen3.5:9b its dead-time behaviour (30/30 -> 20/30 on the
                # cases the two rubrics disagree). Magnitude safety lives in
                # _guard(), where it is deterministic; this line stays about trend.
                "If flow_rate is outside the band but already moving toward it, predict it "
                "keeps moving and choose NOOP rather than adding another change.\n"
                + limits
                + "Reply with JSON only: "
                '{"predicted_flow_rate": <number>, "action": "FORWARD"|"BACKWARD"|"NOOP", '
                '"interval_seconds": <number>, "reason": "<max 12 words>"}'
            )
        else:
            system = (
                common
                + "Compare flow_rate to that band and apply exactly one rule:\n"
                f"  flow_rate < {low:.4f}  -> FORWARD\n"
                f"  flow_rate > {high:.4f}  -> BACKWARD\n"
                f"  flow_rate between {low:.4f} and {high:.4f} (inclusive) -> NOOP\n"
                "  flow_rate unknown -> NOOP\n"
                + limits
                + "Reply with JSON only: "
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

    def _guard(self, action: ValveCommand, flow_rate: Optional[float]) -> ValveCommand:
        """Override the model on the two cases it is not allowed to get wrong.

        Same reasoning as the STOP downgrade in step(): some decisions are Python's,
        not the model's. Benchmarked at 10 reps, predictive-mode models answered
        FORWARD on an unknown flow rate (having invented one from the history) and
        NOOP on a 5.0 g/s runaway (having read the rising history as "trending
        toward the band"). Both are prompt-level failures that a prompt fix can
        only make less likely; this makes them impossible.

        Applies to both variants -- the rule variant scored 100% on these cases,
        so the guard is inert there, which is exactly what a backstop should be.
        """
        if flow_rate is None:
            if action is not ValveCommand.NOOP:
                logger.warning(
                    f"guard: flow_rate unknown, overriding {action.name} -> NOOP"
                )
            return ValveCommand.NOOP
        if flow_rate > self.max_flow_rate and action is not ValveCommand.BACKWARD:
            logger.warning(
                f"guard: flow_rate {flow_rate:.4f} g/s exceeds ceiling "
                f"{self.max_flow_rate:.4f} g/s, overriding {action.name} -> BACKWARD"
            )
            return ValveCommand.BACKWARD
        return action


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
            action = self._guard(action, flow_rate)
            logger.info(f"LLM decision: {raw_action} for {interval:g}s -- {reason}")

            self._record(flow_rate, current_weight, action)
            return action, int(interval)
        except Exception as e:
            logger.warning(f"LLM step failed ({type(e).__name__}: {e}), falling back to default strategy")
            action, interval = self.fallback.step(flow_rate, current_weight)
            # Guard the fallback too: it is a different code path, not a trusted one.
            if action is not ValveCommand.STOP:
                action = self._guard(action, flow_rate)
            self._record(flow_rate, current_weight, action)
            return action, interval
