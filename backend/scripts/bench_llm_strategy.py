#!/usr/bin/env python3
"""
Benchmark LLM models for AIBrewStrategy: correctness first, then latency.

Deliberately drives the *shipped* strategy -- it builds a real AIBrewStrategy and
calls its own _build_messages/_post, so what is measured is exactly what a brew
would send. A copy of the prompt would drift from the real one and quietly
benchmark the wrong thing.

Grading is against the rule the prompt itself states:

    flow < target - epsilon  -> FORWARD
    flow > target + epsilon  -> BACKWARD
    otherwise                -> NOOP        (including unknown flow)

Usage:
    cd backend
    PYTHONPATH=src python scripts/bench_llm_strategy.py \
        --host http://localhost:11434 \
        --models qwen2.5:3b,granite4:3b --reps 3
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from brewctl.api.strategies.AIBrewStrategy import AIBrewStrategy  # noqa: E402

TARGET_FLOW = 0.05
EPSILON = 0.008
VESSEL = 229.0
TARGET_WEIGHT = 1337.0


def expected_action(flow):
    """The correct answer, per the rule the system prompt states."""
    if flow is None:
        return "NOOP"
    if flow < TARGET_FLOW - EPSILON:
        return "FORWARD"
    if flow > TARGET_FLOW + EPSILON:
        return "BACKWARD"
    return "NOOP"


# (name, flow_rate, current_weight). Weight stays well under target so the Python
# stop check never fires and every case actually reaches the model.
CASES = [
    ("far too slow",           0.0180, 500.0),
    ("far too fast",           0.0900, 500.0),
    ("exactly on target",      0.0500, 500.0),
    ("just inside low edge",   0.0425, 500.0),
    ("just inside high edge",  0.0575, 500.0),
    ("just outside low edge",  0.0410, 500.0),
    ("just outside high edge", 0.0590, 500.0),
    ("unknown flow",           None,   500.0),
    ("unknown weight",         0.0200, None),
    ("absurd flow",            5.0000, 500.0),
]


# Trajectory cases for the predictive variant. Each carries two expected answers:
# what the instantaneous rule says, and what a dead-time-aware controller should
# say. The cases where they differ are the whole point -- a valve step takes ~2min
# to reach the flow, so acting on the current reading stacks corrections that have
# not landed and the loop oscillates.
#
# history entries are (elapsed_s, weight_g, flow_rate, action), oldest first.
TRAJECTORY_CASES = [
    (
        "below band, rising after FORWARD",
        [(120, 200, 0.0300, "FORWARD"), (210, 230, 0.0340, "NOOP"), (300, 265, 0.0380, "NOOP")],
        0.0410, 500.0, "FORWARD", "NOOP",
    ),
    (
        "below band, flat despite FORWARD",
        [(120, 200, 0.0300, "FORWARD"), (210, 227, 0.0301, "FORWARD"), (300, 254, 0.0299, "FORWARD")],
        0.0300, 500.0, "FORWARD", "FORWARD",
    ),
    (
        "above band, falling after BACKWARD",
        [(120, 200, 0.0750, "BACKWARD"), (210, 267, 0.0700, "NOOP"), (300, 330, 0.0640, "NOOP")],
        0.0600, 500.0, "BACKWARD", "NOOP",
    ),
    (
        "above band, flat",
        [(120, 200, 0.0700, "NOOP"), (210, 263, 0.0702, "NOOP"), (300, 326, 0.0699, "NOOP")],
        0.0700, 500.0, "BACKWARD", "BACKWARD",
    ),
    (
        "in band, declining toward low edge",
        [(120, 200, 0.0550, "NOOP"), (210, 250, 0.0500, "NOOP"), (300, 295, 0.0455, "NOOP")],
        0.0430, 500.0, "NOOP", "FORWARD",
    ),
    (
        "in band, stable",
        [(120, 200, 0.0500, "NOOP"), (210, 245, 0.0501, "NOOP"), (300, 290, 0.0499, "NOOP")],
        0.0500, 500.0, "NOOP", "NOOP",
    ),
    (
        "below band, declining (bed compaction)",
        [(120, 200, 0.0450, "NOOP"), (210, 240, 0.0420, "NOOP"), (300, 278, 0.0390, "NOOP")],
        0.0360, 500.0, "FORWARD", "FORWARD",
    ),
    (
        "above band, rising",
        [(120, 200, 0.0620, "NOOP"), (210, 256, 0.0660, "NOOP"), (300, 315, 0.0700, "NOOP")],
        0.0740, 500.0, "BACKWARD", "BACKWARD",
    ),
]


def synth_history(n):
    """n plausible prior steps, oldest first: a brew climbing toward target."""
    out, weight, flow = [], 150.0, 0.0180
    for i in range(n):
        elapsed = 90.0 * (i + 1)
        out.append({"elapsed_s": elapsed, "weight_g": round(weight, 1),
                    "flow_rate": round(flow, 4), "action": "FORWARD"})
        weight += flow * 90.0
        flow = min(flow + 0.0015, 0.0420)
    return out


def build(host, model, timeout, predictive=False, history_points=12):
    return AIBrewStrategy(
        target_flow_rate=TARGET_FLOW,
        scale_interval=0.5,
        valve_interval=90,
        target_weight=TARGET_WEIGHT,
        vessel_weight=VESSEL,
        epsilon=EPSILON,
        model=model,
        base_url=host,
        timeout_seconds=timeout,
        predictive=predictive,
        history_points=max(1, history_points),
        warmup=False,
    )


def _ask(strategy, flow, weight):
    """One call. Returns (action, reason, predicted, seconds)."""
    t0 = time.time()
    try:
        body = strategy._post(strategy._build_messages(flow, weight))
        decision = strategy._parse_content(body["choices"][0]["message"]["content"])
        got = str(decision.get("action", "?")).strip().upper()
        reason = str(decision.get("reason", ""))[:38]
        pred = decision.get("predicted_flow_rate")
    except Exception as e:
        got, reason, pred = f"ERR:{type(e).__name__}", "", None
    return got, reason, pred, time.time() - t0


def run_static(host, model, reps, timeout, history_points, predictive):
    """The ten fixed cases. Grades against the instantaneous rule."""
    strategy = build(host, model, timeout, predictive, history_points or 12)
    for point in synth_history(history_points):
        strategy.history.append(point)

    label = f"{model} [history={history_points}, {'predictive' if predictive else 'rule'}]"
    print(f"\n=== {label} ===")
    t0 = time.time()
    try:
        strategy._post([{"role": "user", "content": "ok"}], max_tokens=1)
        print(f"  warm-up {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"  warm-up FAILED ({type(e).__name__}: {e})")
        return None

    times, hits, total, inconsistent = [], 0, 0, 0
    for name, flow, weight in CASES:
        want = expected_action(flow)
        got_actions, reason = [], ""
        for _ in range(reps):
            got, reason, _pred, dt = _ask(strategy, flow, weight)
            times.append(dt)
            got_actions.append(got)
            total += 1
            hits += got == want
        ok = all(g == want for g in got_actions)
        consistent = len(set(got_actions)) == 1
        inconsistent += not consistent
        print(f"  {'ok  ' if ok else 'MISS'} {name:22} want={want:8} got={','.join(got_actions):26}"
              f" {'' if consistent else '(INCONSISTENT) '}\"{reason}\"")
    pct = 100.0 * hits / total if total else 0.0
    print(f"  --> correct {hits}/{total} ({pct:.0f}%)  inconsistent_cases={inconsistent}  "
          f"median={statistics.median(times):.1f}s max={max(times):.1f}s")
    return {"label": label, "model": model, "history": history_points,
            "predictive": predictive, "cases": "static",
            "correct": hits, "total": total, "pct": pct,
            "inconsistent": inconsistent,
            "median_s": statistics.median(times), "max_s": max(times)}


def run_trajectory(host, model, reps, timeout, predictive):
    """Cases with a trend. Scores against BOTH rubrics, and the subset where they differ."""
    label = f"{model} [{'predictive' if predictive else 'rule'}]"
    print(f"\n=== {label} on trajectory cases ===")
    strategy = build(host, model, timeout, predictive, 8)
    t0 = time.time()
    try:
        strategy._post([{"role": "user", "content": "ok"}], max_tokens=1)
        print(f"  warm-up {time.time() - t0:.1f}s")
    except Exception as e:
        print(f"  warm-up FAILED ({type(e).__name__}: {e})")
        return None

    times, inst_hits, pred_hits, total = [], 0, 0, 0
    dis_pred_hits, dis_total = 0, 0
    for name, hist, flow, weight, want_inst, want_pred in TRAJECTORY_CASES:
        strategy.history.clear()
        for elapsed, w, f, a in hist:
            strategy.history.append({"elapsed_s": float(elapsed), "weight_g": float(w),
                                     "flow_rate": f, "action": a})
        got_actions, preds, reason = [], [], ""
        for _ in range(reps):
            got, reason, pred, dt = _ask(strategy, flow, weight)
            times.append(dt)
            got_actions.append(got)
            if pred is not None:
                preds.append(pred)
            total += 1
            inst_hits += got == want_inst
            pred_hits += got == want_pred
            if want_inst != want_pred:
                dis_total += 1
                dis_pred_hits += got == want_pred
        disagree = " *" if want_inst != want_pred else "  "
        pred_str = f" pred={','.join(f'{p:.4f}' for p in preds[:3])}" if preds else ""
        print(f"  {disagree}{name:34} inst={want_inst:8} deadtime={want_pred:8} "
              f"got={','.join(got_actions):26}{pred_str} \"{reason}\"")
    print(f"  --> instantaneous rubric {inst_hits}/{total}   dead-time rubric {pred_hits}/{total}")
    if dis_total:
        print(f"  --> on the {dis_total // reps} cases where the rubrics disagree (*): "
              f"chose dead-time answer {dis_pred_hits}/{dis_total}")
    print(f"  --> median={statistics.median(times):.1f}s max={max(times):.1f}s")
    return {"label": label, "model": model, "predictive": predictive, "cases": "trajectory",
            "instant": inst_hits, "deadtime": pred_hits, "total": total,
            "disagree_deadtime": dis_pred_hits, "disagree_total": dis_total,
            "median_s": statistics.median(times), "max_s": max(times)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--models", required=True, help="comma-separated Ollama tags")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=180.0,
                    help="generous by design -- we want the real number, not a timeout")
    ap.add_argument("--history", default="12",
                    help="comma-separated seeded-history sizes to sweep, e.g. 0,3,12,24")
    ap.add_argument("--variant", default="rule", choices=["rule", "predictive", "both"])
    ap.add_argument("--cases", default="static", choices=["static", "trajectory", "both"])
    ap.add_argument("--json", type=Path, help="also write results here")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    histories = [int(h) for h in args.history.split(",") if h.strip() != ""]
    variants = [False, True] if args.variant == "both" else [args.variant == "predictive"]

    results = []
    for model in models:
        for predictive in variants:
            if args.cases in ("static", "both"):
                for h in histories:
                    r = run_static(args.host, model, args.reps, args.timeout, h, predictive)
                    if r:
                        results.append(r)
            if args.cases in ("trajectory", "both"):
                r = run_trajectory(args.host, model, args.reps, args.timeout, predictive)
                if r:
                    results.append(r)

    static = [r for r in results if r["cases"] == "static"]
    if static:
        print("\n" + "=" * 82)
        print(f"{'config':44} {'correct':>10} {'inconsist':>10} {'median':>8}")
        for r in sorted(static, key=lambda r: (-r["pct"], r["median_s"])):
            print(f"{r['label']:44} {r['correct']:>4}/{r['total']:<4} {r['pct']:>3.0f}% "
                  f"{r['inconsistent']:>7} {r['median_s']:>7.1f}s")
        print("Ranked by correctness: a fast wrong answer drives the valve the wrong way.")

    traj = [r for r in results if r["cases"] == "trajectory"]
    if traj:
        print("\n" + "=" * 82)
        print(f"{'config':30} {'instant':>10} {'dead-time':>11} {'on disagreements':>18} {'median':>8}")
        for r in traj:
            d = f"{r['disagree_deadtime']}/{r['disagree_total']}" if r["disagree_total"] else "-"
            print(f"{r['label']:30} {r['instant']:>4}/{r['total']:<5} {r['deadtime']:>4}/{r['total']:<6} "
                  f"{d:>18} {r['median_s']:>7.1f}s")

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
