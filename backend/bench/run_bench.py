"""Run our agent against browser-use's BU_Bench_V1 (100 hard browser tasks) and score it with the
same gemini-2.5-flash judge, so the number is comparable to their leaderboard.

    uv run python -m bench.run_bench --indices 0,1,2          # validate the pipeline on a few
    uv run python -m bench.run_bench --count 100 --out bench/results/full.json   # the full run (~hours)

Uses the agent model from settings (you set google/gemini-3.5-flash) and a headful+stealth
LocalCDPSession (our production anti-bot config). NOTE: the official leaderboard uses cloud anti-bot
browsers; a local headful run will lose some tasks to bot-walls that a residential/cloud browser
wouldn't — so treat this as a lower bound relative to the leaderboard.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.agent.run import run
from app.config.container import build_default_app
from app.config.settings import get_settings
from app.events.sink import BufferSink
from bench.judge import judge
from bench.recorder import RecordingSession
from bench.tasks import load_tasks


def format_steps(events) -> str:
    lines: list[str] = []
    for e in events:
        d = e.data
        if e.event == "evaluation":
            lines.append(f"[assess] {d.get('text', '')}")
        elif e.event == "reasoning":
            lines.append(f"[reason] {str(d.get('text', ''))[:400]}")
        elif e.event == "tool_call":
            lines.append(f"[action] {d.get('name')}({json.dumps(d.get('args', {}))[:300]})")
        elif e.event == "observation":
            lines.append(f"[page] {d.get('url', '')} ({d.get('elements', 0)} elements)")
        elif e.event == "error":
            lines.append(f"[error] {str(d.get('message', ''))[:200]}")
    return "\n".join(lines)


async def run_one(task: dict, *, headless: bool, max_steps: int, timeout: float) -> dict:
    from app.browser.local_cdp import LocalCDPSession

    prompt = task["confirmed_task"]
    tid = task["task_id"]
    settings = get_settings()
    settings.max_steps = max_steps  # bound cost/time per task

    inner = LocalCDPSession(headless=headless, stealth=True, draw_som_overlay=settings.use_vision)
    rec = RecordingSession(inner)
    sink = BufferSink()
    started = time.monotonic()
    err: str | None = None
    final_result = ""
    try:
        await rec.start()
        graph, emitter, store, sink, memory = build_default_app(session=rec, sink=sink)
        final = await asyncio.wait_for(
            run(graph, task=prompt, thread_id=tid, emitter=emitter, memory=memory), timeout=timeout
        )
        final_result = final.reason or f"(no explicit answer; status={final.status}, steps={final.step})"
    except asyncio.TimeoutError:
        final_result, err = "(agent timed out before finishing)", "timeout"
    except Exception as exc:  # a single task's crash must not kill the batch
        final_result, err = f"(agent error: {exc})", str(exc)[:200]
    finally:
        try:
            await rec.stop()
        except Exception:
            pass

    duration = round(time.monotonic() - started, 1)
    steps_text = format_steps(sink.events)
    verdict = await judge(prompt, final_result, steps_text, rec.shots)
    # Dump the full trajectory for inspection (gitignored) — the result JSON only keeps a summary.
    trace_dir = Path("bench/runs")
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / f"{task.get('category', 'x')}_{tid[:8]}.txt").write_text(
        f"TASK: {prompt}\n\nVERDICT: {verdict.get('verdict')}  ({verdict.get('failure_reason')})\n\n"
        f"FINAL_RESULT: {final_result}\n\n=== TRAJECTORY ({len(sink.events)} events) ===\n{steps_text}\n"
    )
    return {
        "task_id": tid,
        "category": task.get("category"),
        "task": prompt[:200],
        "score": 1 if verdict.get("verdict") else 0,
        "verdict": bool(verdict.get("verdict")),
        "failure_reason": verdict.get("failure_reason"),
        "reached_captcha": bool(verdict.get("reached_captcha")),
        "final_result": final_result[:1200],
        "duration": duration,
        "n_screens": len(rec.shots),
        "error": err,
    }


def _indices(total: int, args) -> list[int]:
    if args.indices:
        return [int(x) for x in args.indices.split(",") if x.strip()]
    return list(range(args.start, min(args.start + (args.count if args.count else total), total)))


async def main() -> None:
    ap = argparse.ArgumentParser(description="Run our agent against BU_Bench_V1")
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--indices", default="")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--headless", action="store_true", help="run headless (default: headful+stealth)")
    ap.add_argument("--out", default="bench/results/run.json")
    args = ap.parse_args()

    tasks = load_tasks()
    indices = _indices(len(tasks), args)
    print(f"model={get_settings().agent_model}  tasks={len(indices)}  "
          f"headless={args.headless}  max_steps={args.max_steps}  timeout={args.timeout}s\n")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for i in indices:
        r = await run_one(tasks[i], headless=args.headless, max_steps=args.max_steps, timeout=args.timeout)
        results.append({"index": i, **r})
        mark = "✓" if r["score"] else "✗"
        why = ""
        if not r["score"]:
            tag = "captcha" if r["reached_captcha"] else ("maxsteps" if r["n_screens"] >= args.max_steps - 1 else "miss")
            why = f"  [{tag}] {str(r['failure_reason'])[:80]}"
        passed = sum(x["score"] for x in results)
        print(f"[{i:>2}] {mark} {r['category']:<16} {r['task'][:52]}  ({r['duration']}s)  "
              f"running {passed}/{len(results)}{why}", flush=True)
        # Write incrementally so a mid-run crash keeps completed results.
        pct = 100 * passed / len(results)
        out.write_text(json.dumps({"model": get_settings().agent_model, "passed": passed,
                                   "total": len(results), "pct": round(pct, 1), "results": results}, indent=2))

    passed = sum(r["score"] for r in results)
    pct = 100 * passed / len(results) if results else 0.0
    print(f"\n=== {passed}/{len(results)} passed ({pct:.1f}%) — model {get_settings().agent_model} ===", flush=True)
    print(f"results → {out}")


if __name__ == "__main__":
    asyncio.run(main())
