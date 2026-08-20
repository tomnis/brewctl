# Feature plans

Drafted 2026-08-10 on the `device_mode` branch, during the api/hardware microservice split.
Nothing here is implemented. Each file is a standalone spec: motivation, design, the concrete
file-level edits required, and open questions.

These were written against the tree at commit `af083be`. If the api/hardware split moves further
before any of these are picked up, re-check the "Files touched" section of the relevant spec first.

## Index

| # | Spec | Summary | Rough size |
|---|------|---------|-----------|
| 1 | [brew-history-and-recipes.md](brew-history-and-recipes.md) | Persist brews to SQLite; named recipes/presets; history UI | L |
| 2 | [strategy-replay-simulator.md](strategy-replay-simulator.md) | Run strategies headless against recorded or modelled plant data | M |
| 3 | [valve-calibration-curve.md](valve-calibration-curve.md) | Map valve position to steady-state flow rate; feedforward control | M |
| 4 | [notifications.md](notifications.md) | Push notification on brew complete, error, watchdog trip | S |
| 5 | [hardware-resilience.md](hardware-resilience.md) | Staleness-aware `HttpScale`/`HttpValve`, safe degradation | M |
| 6 | [multi-device-registry.md](multi-device-registry.md) | Multiple hardware nodes, brew state keyed by device | L |
| 7 | [auth.md](auth.md) | Shared-token auth on both services | S |
| 8 | [small-wins.md](small-wins.md) | Auto-tare, Prometheus metrics, accelerated dry-run, live strategy switch, env prefix cleanup | S each |
| 9 | [ai-brew-strategy-plan.md](ai-brew-strategy-plan.md) | LLM-guided strategy against a local Ollama host; teaching demo for AI/API students | M |

## Suggested order

1. **Brew history (#1)** first. It introduces the relational storage layer that #2, #3, and #6 all
   want, and it is the feature with the most standalone user value.
2. **Valve calibration (#3)** second. It is the only change that improves all six existing
   strategies at once, rather than adding a seventh.
3. **Hardware resilience (#5)** and **auth (#7)** are correctness/safety work that should land
   before the system is exposed beyond a trusted LAN.
4. **Multi-device (#6)** last of the large items — it is a rewrite of the global-state model in
   `api/server.py` and is much easier once brews are already persisted.
