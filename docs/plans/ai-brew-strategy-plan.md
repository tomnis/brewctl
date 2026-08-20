# AI-Powered Brew Strategy

## Context

We want a new brew strategy that delegates valve control decisions to a small LLM hosted on a local
Ollama server. It is deliberately gimmicky as a control algorithm — its purpose is teaching. It gives
students learning about AI and APIs a single, legible loop they can read end to end: gather real
sensor state, serialize it into a prompt, POST it to a chat-completions endpoint, parse structured
JSON back, and act on it — with a physical valve moving as the result.

The strategy queries the model each cycle with the current brew snapshot plus a short history of
recent readings, and asks it for a valve action and how long to wait before asking again.

Two hard constraints shape the design, both from existing repo behavior:

1. `strategy.step()` is called **synchronously on the event loop** by `brew_step_task`
   (`backend/src/brewctl/api/server.py:362`). A blocking LLM call there freezes the whole api
   process — scale collection, SSE pushes, every HTTP endpoint.
2. The hardware watchdog closes the valve if unfed for `BREWCTL_WATCHDOG_TIMEOUT_SECONDS` (10s
   default). Heartbeats are only emitted inside `sleep_with_heartbeat` (`server.py:341`), so time
   spent inside `step()` is heartbeat-dead time. On a CPU-only N100, a 1-3B model can take several
   seconds per response and 30s+ on the first call while the model loads into RAM.

The Ollama host is an ODROID H2 (Intel N100, 4 cores, 32GB RAM, no usable GPU for inference — Ollama
does not use the Intel UHD iGPU). This must work with a small quantized instruct model and must
degrade gracefully when the model is slow, unreachable, or returns nonsense.

## Model selection

Measured Ollama tok/s on N100 at Q4 (see Sources at the end):

| Model | Params | tok/s |
|---|---|---|
| `tinyllama` | 1.1B | 15–25 |
| `gemma2:2b` | 2B | 8–18 |
| `llama3.2:3b` | 3B | 5–15 |
| `qwen2.5:3b` | 3B | 5–14 |
| `phi3:mini` | 3.8B | 4–12 |

7B+ crawls or OOMs in practice on this chip. 3B-class models need ~4GB, so the 32GB is not the
constraint — 4 cores and memory bandwidth are. Idle-to-inference power lands around 12–18W.

Our response is ~30–40 tokens, so decode is roughly 2–8s plus prefill. **Default to `llama3.2:3b`**
for decision quality, with `gemma2:2b` as the fast fallback if steps feel sluggish and `tinyllama`
only as a "watch it fail" teaching contrast — it is too weak for reliable instruction following.
Because `model` is a strategy param, students can swap between these from the UI per brew, which is
itself a good exercise.

**On using the iGPU.** Ollama is CPU-only here, and alternatives exist that would engage the UHD 24
EU part — Intel's IPEX-LLM patched Ollama, llama.cpp's SYCL or Vulkan `llama-server`, or OpenVINO
GenAI. Do **not** treat this as a prerequisite. Published measurements split by phase: iGPU offload
roughly doubles prompt processing but leaves token generation flat (34→76 tok/s prefill vs 10→10
tok/s decode on a comparable integrated part), because decode is memory-bandwidth-bound and the iGPU
shares the same DIMMs. The one clear win (~30% throughput at ~⅓ the power) was on an Arc Xe-LPG
**112 EU** with dual-channel DDR5 — ~4.7× the EUs of the N100. Our call is a ~400-token prompt and a
~40-token response, i.e. decode-dominated, which is the phase that does not speed up. Since the
strategy speaks generic OpenAI-compatible HTTP, all of these are a `BREWCTL_LLM_BASE_URL` change
with **zero code change** — benchmark them as a follow-up experiment. Expect the win to be power
draw, not latency. Also confirm what the 32GB is actually clocked at and in which channel config;
Intel specs Alder Lake-N at 16GB max, and bandwidth is the real ceiling.

**Constrained decoding.** Ollama's OpenAI-compatible endpoint supports
`response_format: {"type": "json_schema", …}`, which llama.cpp enforces with a GBNF grammar — the
model is mechanically unable to emit non-conforming tokens. Use this rather than
`{"type": "json_object"}`. Keep the schema **flat** with no `$defs`: sub-4B models comply well on
flat schemas and degrade badly on nested ones. Use `temperature: 0`. The JSON-parse fallback path
still stays in, both for older/other servers and because "the constraint can fail" is worth showing.

## Design decisions (settled)

- Concurrency: run `step()` in a thread while an asyncio ticker keeps the watchdog fed.
- Fallback: on any LLM failure, delegate to a `DefaultBrewStrategy` instance the AI strategy owns.
- Safety: the LLM **never** decides `STOP`. The target-weight check stays in Python, and the
  returned interval is clamped.
- Endpoint: OpenAI-compatible `POST {base_url}/v1/chat/completions` (Ollama serves this), so the
  demo is provider-agnostic and students can swap the backing service via one env var.
- Latency: because the heartbeat ticker keeps the watchdog fed during the call, the request timeout
  is no longer pinned under the 10s watchdog — use 15s, comfortably above worst-case N100 decode. A
  warm-up request is fired at strategy construction on a daemon thread so the first real step does
  not eat the 30s+ model-load cost.

## Changes

### 1. `backend/src/brewctl/api/server.py` — unblock `step()`

Add next to `sleep_with_heartbeat`:

```python
async def run_step_with_heartbeat(strategy, flow_rate, weight):
    """
    Run strategy.step() off the event loop, feeding the watchdog while it works.

    Most strategies return instantly, but an LLM-backed one can block for seconds.
    Without the ticker the watchdog would close the valve mid-step.
    """
    task = asyncio.create_task(asyncio.to_thread(strategy.step, flow_rate, weight))
    while True:
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_INTERVAL_SECONDS)
        if done:
            return task.result()
        try:
            await asyncio.to_thread(valve.heartbeat)
        except Exception as e:
            logger.warning(f"Valve heartbeat failed during strategy step: {e}")
```

In `brew_step_task`, replace the direct call

```python
(valve_command, interval) = strategy.step(current_flow_rate, current_weight)
```

with `(valve_command, interval) = await run_step_with_heartbeat(strategy, current_flow_rate, current_weight)`.

This routes every strategy through a thread. The existing strategies are pure arithmetic, so the
overhead is negligible and their behavior is unchanged. Exceptions still propagate to the existing
`except` block that sets `BrewState.ERROR`.

### 2. `backend/src/brewctl/core/model.py`

Add `AI = "ai"` to `BrewStrategyType`. Note `test_strategy_registry.py` iterates the enum, so this
value must be registered and must propagate base params or those tests fail.

### 3. `backend/src/brewctl/api/config.py`

Follow the existing `os.environ.get` + log-the-name pattern:

```python
BREWCTL_LLM_BASE_URL = os.environ.get("BREWCTL_LLM_BASE_URL", "http://localhost:11434")
BREWCTL_LLM_MODEL = os.environ.get("BREWCTL_LLM_MODEL", "llama3.2:3b")
BREWCTL_LLM_TIMEOUT_SECONDS = float(os.environ.get("BREWCTL_LLM_TIMEOUT_SECONDS", "15.0"))
BREWCTL_LLM_API_KEY = os.environ.get("BREWCTL_LLM_API_KEY", "")  # unused by Ollama
```

Log the URL and model; never log the key (mirrors how `BREWCTL_INFLUXDB_TOKEN` is handled). Strategy
modules do `from brewctl.api.config import *`, so these are visible automatically.

### 4. `backend/src/brewctl/api/strategies/AIBrewStrategy.py` (new)

Import `AbstractBrewStrategy`, `register_strategy` from `.DefaultBrewStrategy` (the registry lives
there; do not add to that file or you get a circular import). Decorate with
`@register_strategy(BrewStrategyType.AI)`.

**Param coercion.** The frontend sends every `strategy_param` as a **string**, and the shared
`_extract_float` returns its default for strings (`isinstance(value, (int, float))` fails). Add
local `_coerce_float` / `_coerce_str` helpers in this module that accept strings. Do not change the
shared `_extract_float` — the existing strategies' silent fallback-to-default is a pre-existing bug
outside this task's scope, but it is worth a follow-up.

**Constructor.** Takes the six base params plus `model`, `base_url`, `timeout_seconds`,
`temperature`, `history_points`, `min_interval`, `max_interval`. It:

- builds `self.fallback = DefaultBrewStrategy(...)` from the same base params,
- keeps `self.history: deque[dict]` (maxlen `history_points`, default 12) of
  `{elapsed_s, weight_g, flow_rate, action}` appended each step — self-contained, so no injection of
  `time_series` or the `WeightBuffer` is needed. The owned `DefaultBrewStrategy` has its own
  target-weight `STOP` check, redundant with step 1 below but harmless and correct — leave it,
- fires a warm-up request on a daemon thread (`threading.Thread(..., daemon=True).start()`) that
  POSTs a one-token prompt and discards the result, so model load overlaps the brew's first
  `scale_interval` rather than the first step. Bounded by the httpx timeout and `daemon=True`, so it
  cannot block interpreter shutdown; at most one short-lived thread per brew, and tests suppress it.

Must expose `valve_interval`, `target_flow_rate`, `target_weight`, `vessel_weight` as attributes —
`brew_step_task`'s error path reads `strategy.valve_interval`, and `test_base_params_propagated`
asserts the other three for every enum member.

**`step(flow_rate, current_weight)`:**

1. Target-weight check first, identical to every other strategy — if
   `current_weight - vessel_weight >= coffee_target`, return `(ValveCommand.STOP, 0)`. The LLM is
   never consulted and can never override this.
2. Build the prompt (system message states the role, target flow rate, allowed actions, and the
   required JSON shape; user message carries the current snapshot plus the history table).
3. `POST {base_url}/v1/chat/completions` via a short-lived `httpx.Client(timeout=...)`, mirroring
   `http_valve.py:_request`. `httpx` is already in `backend/requirements/api.txt` — **no new
   dependency**. Body: `model`, `messages`, `temperature: 0`, `stream: false`, and the flat
   `response_format: {"type": "json_schema", …}` described under Model selection. Send
   `Authorization: Bearer …` only if a key is set.
4. Parse `choices[0].message.content` as JSON, tolerating ```json fences. Expected shape:
   `{"action": "FORWARD"|"BACKWARD"|"NOOP", "interval_seconds": <number>, "reason": "<short>"}`.
   Order the schema fields with `action` first so the decision is grammar-committed early, and
   instruct a max ~12-word `reason` — every reason token is real latency at 5–15 tok/s.
5. Validate: action must map to a `ValveCommand` in that set (`STOP` from the model is rejected and
   treated as `NOOP`); interval clamped to `[min_interval, max_interval]`, defaults 5 and
   `valve_interval`. `logger.info` the action, interval, and the model's `reason` — the reason string
   is the payoff for the demo, it shows up in the logs next to real valve movement.
6. On **any** exception, malformed JSON, non-2xx, or invalid action: `logger.warning` and
   `return self.fallback.step(flow_rate, current_weight)`.
7. Append the resulting decision to `self.history` before returning.

**`get_params_schema`** returns entries for `model`, `base_url`, `temperature`, `timeout_seconds`,
`history_points`, `min_interval`, `max_interval`, matching the `{type, default, label, description}`
shape used by `PIDBrewStrategy`.

### 5. Registration exports

Add `AIBrewStrategy` to the imports and `__all__` of both
`backend/src/brewctl/api/strategies/__init__.py` and `backend/src/brewctl/api/brew_strategy.py` —
registration is purely an import side effect, and `server.py` only imports from the shim.

### 6. Frontend — `frontend/src/components/brew/constants.ts`

Add `"ai"` to the `StrategyType` union and an entry to `STRATEGIES`:

```ts
{ id: "ai", name: "AI (LLM-Guided)",
  description: "Asks a local language model what the valve should do next. Educational demo.",
  params: [ model, base_url, temperature, timeout_seconds, history_points, min_interval, max_interval ] }
```

Each is a `StrategyParam` (`name`/`label`/`placeholder`/`defaultValue`/`description`). Every field
renders as a plain text `<Input>` in `StartBrew.tsx`, which suits `model` and `base_url` directly.
Adding to the union is required or the TypeScript build fails.
`frontend/src/components/brew/constants.test.ts` uses `toContain`, not an exact-match assertion, so
it needs no edit — optionally add an `"ai"` case for symmetry. `types.ts` types `brew_strategy` as
`string`, so no change there.

### 7. Tests — `backend/tests/api/test_ai_strategy.py` (new)

Registry tests auto-cover the new enum value. Add behavior tests that patch `httpx.Client` where the
AI strategy constructs it (mirroring how `conftest.py` patches `HttpScale`/`HttpValve` as classes),
and suppress the warm-up thread:

- valid JSON response maps to the right `ValveCommand` and clamped interval
- `interval_seconds` out of range is clamped to `min_interval` / `max_interval`
- model returning `"STOP"` does **not** stop the brew
- malformed JSON, HTTP error, and timeout each fall back to `DefaultBrewStrategy` output
- target weight reached returns `(STOP, 0)` with **zero** HTTP calls made
- string-valued `strategy_params` (as the frontend sends) are coerced, not silently defaulted

Also a `server.py` test that `run_step_with_heartbeat` calls `valve.heartbeat` at least once when
`step` blocks longer than `HEARTBEAT_INTERVAL_SECONDS` (use a sleeping fake strategy).

### 8. Deployment config

Add `BREWCTL_LLM_BASE_URL` / `BREWCTL_LLM_MODEL` to the api service env in `docker-compose.yml`,
`.env`, and the NAS deployment under `deploy/nas/`. The api container must be able to reach the
Ollama host — verify network reachability from inside the container, not just from the NAS host.

## Verification

```bash
cd backend && pytest tests/api/test_ai_strategy.py tests/api/test_strategy_registry.py
cd backend && pytest tests            # full backend, catches brew_step_task regressions
cd frontend && npx vitest run src/components/brew/constants.test.ts
cd frontend && npm run lint && npm run build
```

End to end, against a real Ollama:

```bash
time curl "$BREWCTL_LLM_BASE_URL/v1/chat/completions" -H 'Content-Type: application/json' \
  -d '{"model":"llama3.2:3b","temperature":0,"stream":false,
       "messages":[{"role":"user","content":"reply with {\"ok\":true}"}],
       "response_format":{"type":"json_object"}}'
```

Run it twice — the first call includes model load, the second is the steady-state number to compare
against the 15s timeout.

Then `make dev` (hardware service in mock mode), pick **AI (LLM-Guided)** in the UI, start a brew,
and watch the api logs. Expect one LLM decision line per cycle including the model's `reason`, valve
position changing in the frontend, and — critically — no watchdog-close events in the hardware log
even when a response takes longer than 3s. Confirm the fallback path by stopping Ollama mid-brew:
the brew must keep running on `DefaultBrewStrategy` with warnings, not enter `BrewState.ERROR`.

Time a single step to sanity-check the model choice on the N100. If p95 approaches the 15s timeout,
drop `llama3.2:3b` → `gemma2:2b` rather than raising the timeout — a long step means a long stretch
where the only thing holding the valve is the heartbeat ticker.

## Sources

- [Running Ollama on Intel N100 & N150 Mini PC](https://bishalkshah.com.np/blog/ollama-n100-mini-pc-local-ai) — N100 tok/s table, RAM and power figures
- [Ollama: Structured outputs](https://ollama.com/blog/structured-outputs) and [docs](https://docs.ollama.com/capabilities/structured-outputs) — GBNF-enforced JSON schema
- [The Constraint Tax: Validity-Correctness Tradeoffs in Structured Outputs for Small Language Models](https://arxiv.org/pdf/2605.26128) — sub-4B schema-compliance degradation on nested schemas
- [Best CPU-only local LLMs in 2026](https://www.popularai.org/p/best-cpu-only-local-llm)
- [llama.cpp Benchmark: CPU vs iGPU](https://medium.com/@techhara/llama-cpp-benchmark-cpu-vs-igpu-93b3cc40ece5) — prefill 2× vs decode flat
- [Performance Analysis of Intel iGPUs in VLM and LLM applications](https://nikolasent.github.io/hardware/deeplearning/2025/02/09/iGPU-Benchmark-VLM.html) — IPEX-LLM on Arc Xe-LPG 112EU, ~30% and dual-channel requirement
- [intel/ipex-llm Ollama quickstart](https://github.com/intel/ipex-llm/blob/main/docs/mddocs/Quickstart/ollama_quickstart.md)
- [llama.cpp SYCL backend on Intel GPU](https://github.com/ggml-org/llama.cpp/discussions/23313)
