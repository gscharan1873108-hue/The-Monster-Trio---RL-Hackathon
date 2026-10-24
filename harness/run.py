"""Entry point. One command runs everything:

    docker compose up --build --abort-on-container-exit --exit-code-from harness

Order of events:
    1. build the images and start the sandbox          (docker compose)
    2. oracle check   the reference solution must score at least 0.95
    3. no-op check    an agent that gives up must score at most 0.05
    4. model run      only if both checks passed

MODE=full runs TASK_ID; MODE=all runs every task in turn; MODE=baselines stops after the checks.
Exit codes: 0 finished, 1 crash, 2 a baseline check failed, 3 bad configuration.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

from .agents import make_client, noop_actions, oracle_actions
from .env import PASS_SCORE, Env
from .runner import JsonlLog, Limits, now, run_episode, run_scripted
from .tasks import DEMO_TASK, DIFFICULTY, TASKS, build_task

ORACLE_MIN = PASS_SCORE      # reference solution must reach this
NOOP_MAX = 0.05              # no-op agent must stay at or below this
MODES = ("full", "all", "baselines")
GATE_BUDGET_SECONDS = 120    # oracle + no-op for one task; the build gets 3 more minutes
INPUTS = Path("inputs")


def setting(name, default=""):
    return os.environ.get(name, default) or default


def wait_for_sandbox(url, seconds=60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if requests.get(url + "/health", timeout=2).ok:
                return
        except requests.RequestException:
            time.sleep(1)
    raise RuntimeError(f"sandbox at {url} did not become ready")


def run_gate(env, task_ids, seed, log_path):
    """Oracle first, then no-op, for each task. Returns (passed, rows)."""
    log = JsonlLog(log_path)
    rows = []
    print("\n== Checks before the model run ==", flush=True)
    for task_id in task_ids:
        started = time.monotonic()
        row = {"task": task_id, "difficulty": DIFFICULTY[task_id]}
        try:
            oracle, outputs = run_scripted(env, task_id, seed, oracle_actions(build_task(task_id, seed)), "oracle", log)
            visible_ok = bool(outputs) and outputs[-1].rstrip().endswith("[exit code 0]")
            oracle_verdict = dict(env.verdict)
            noop, _ = run_scripted(env, task_id, seed, noop_actions(build_task(task_id, seed)), "noop", log)
            noop_verdict = dict(env.verdict)
            first = env.start_hash
            env.reset(task_id, seed)
            deterministic = env.start_hash == first and env.reset_ok
            row.update(oracle=oracle["total"], noop=noop["total"], oracle_ok=oracle["total"] >= ORACLE_MIN,
                       noop_ok=noop["total"] <= NOOP_MAX, visible_tests_pass_with_reference=visible_ok,
                       deterministic_reset=deterministic, start_hash=first,
                       oracle_verifier=oracle_verdict, noop_verifier=noop_verdict)
        except Exception as exc:                     # a broken task must fail its check, not crash the harness
            row.update(oracle=None, noop=None, oracle_ok=False, noop_ok=False, error=f"{type(exc).__name__}: {exc}")
        row["seconds"] = round(time.monotonic() - started, 2)
        rows.append(row)
        oracle_text = "-" if row["oracle"] is None else f"{row['oracle']:.2f}"
        noop_text = "-" if row["noop"] is None else f"{row['noop']:.2f}"
        print(f"{task_id:<12} oracle {oracle_text} {'PASS' if row['oracle_ok'] else 'FAIL'}   "
              f"no-op {noop_text} {'PASS' if row['noop_ok'] else 'FAIL'}   "
              f"reset {'deterministic' if row.get('deterministic_reset') else 'NOT deterministic'}   "
              f"({row['seconds']}s)" + (f"  ERROR {row['error']}" if row.get("error") else ""), flush=True)
        log.write({"timestamp": now(), "event": "gate_row", **row})
    log.close()
    return all(r["oracle_ok"] and r["noop_ok"] for r in rows), rows


def load_append(name):
    """Return (text, info) for the extra system-prompt instructions, or raise ValueError.

    APPEND_FILE names a file inside inputs/. When it is unset, inputs/append.txt is used if present. A file
    that is named but missing, empty or unreadable is an error rather than a silent no-op: a run that quietly
    went ahead without its instructions would look valid when it wasn't. The text is used exactly as written.
    """
    explicit = bool(name)
    name = name or "append.txt"
    for prefix in ("./inputs/", "inputs/", ".\\inputs\\", "inputs\\"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    path = (INPUTS / name).resolve()
    if INPUTS.resolve() not in path.parents:
        raise ValueError(f"APPEND_FILE must be a file inside inputs/, got '{name}'")
    if not path.is_file():
        if explicit:
            raise ValueError(f"APPEND_FILE inputs/{name} not found; put the file in the inputs/ folder")
        return "", None
    try:
        text = path.read_bytes().decode("utf-8-sig")        # drops a BOM added by Windows editors
    except UnicodeDecodeError as exc:
        raise ValueError(f"APPEND_FILE inputs/{name} is not UTF-8 text ({exc.reason})")
    if not text.strip():
        if explicit:
            raise ValueError(f"APPEND_FILE inputs/{name} is empty")
        return "", None
    info = {"file": f"inputs/{name}", "chars": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return text, info


def run_model(env, task_id, seed, client, model, append_text, limits, log_path):
    print(f"\n== Model run: {model}  task={task_id}  seed={seed} ==", flush=True)
    log = JsonlLog(log_path)
    try:
        result = run_episode(env, task_id, seed, client, append_text, limits, log)
    finally:
        log.close()
    print(f"\ntermination: {result['termination']}   reward: {result['reward']}   steps: {result['steps']}", flush=True)
    if result["flags"]:
        print(f"suspicious behaviour flagged: {result['flags']}", flush=True)
    return result


def main():
    url = setting("SANDBOX_URL", "http://sandbox:8000")
    model, api_key, base_url = setting("MODEL", "mock/solver"), setting("API_KEY"), setting("BASE_URL") or None
    task_id, mode = setting("TASK_ID", DEMO_TASK), setting("MODE", "full")
    try:
        seed = int(setting("SEED", "0"))
        limits = Limits(max_steps=int(setting("MAX_STEPS", "40")), max_seconds=int(setting("MAX_SECONDS", "600")))
        max_tokens = int(setting("MAX_TOKENS", "0")) or None
    except ValueError as exc:
        print(f"configuration error: {exc}")
        return 3
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out = Path("logs") / run_id
    out.mkdir(parents=True, exist_ok=True)

    if mode not in MODES:
        print(f"unknown MODE '{mode}'. Available: {', '.join(MODES)}")
        return 3
    if mode == "full" and task_id not in TASKS:
        print(f"unknown TASK_ID '{task_id}'. Available: {', '.join(TASKS)}")
        return 3
    try:
        client = None if mode == "baselines" else make_client(model, api_key, base_url, max_tokens)
        append_text, append_info = ("", None) if mode == "baselines" else load_append(setting("APPEND_FILE"))
    except ValueError as exc:
        print(f"configuration error: {exc}")
        return 3
    if append_info:
        (out / "append.txt").write_bytes(append_text.encode("utf-8"))
        print(f"extra instructions: {append_info['file']}  {append_info['chars']} chars  "
              f"sha256 {append_info['sha256'][:12]}  (added to the system prompt, copy in {out}/append.txt)", flush=True)
    elif mode != "baselines":
        print("extra instructions: none", flush=True)

    try:
        wait_for_sandbox(url)
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 1
    env = Env(url)
    task_ids = [task_id] if mode == "full" else list(TASKS)
    gate_started = time.monotonic()
    passed, rows = run_gate(env, task_ids, seed, out / "gate.jsonl")
    gate_seconds = round(time.monotonic() - gate_started, 2)
    print(f"checks took {gate_seconds}s", flush=True)
    if mode == "full" and gate_seconds > GATE_BUDGET_SECONDS:
        print(f"WARNING: checks exceeded the {GATE_BUDGET_SECONDS}s budget for the live run", flush=True)
    (out / "gate.json").write_text(json.dumps(
        {"seed": seed, "passed": passed, "gate_seconds": gate_seconds, "tasks": rows}, indent=2))

    if mode == "baselines":
        print(f"\nbaseline results: {'all checks passed' if passed else 'SOME CHECKS FAILED'}  ->  {out}/gate.json")
        return 0 if passed else 2
    if not passed:
        summary = {"run_id": run_id, "status": "gate_failed", "mode": mode, "tasks": task_ids, "seed": seed,
                   "model_called": False}
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        print("\nA baseline check failed, so the model was not called. See gate.json.")
        return 2

    if mode == "full":
        result = run_model(env, task_id, seed, client, model, append_text, limits, out / "episode.jsonl")
        summary = {"run_id": run_id, "status": "completed", "task": task_id, "seed": seed, "model": model,
                   "model_called": True, "append": append_info, "finished_at": now(), **result}
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        print(f"logs: {out}", flush=True)
        return 1 if result["termination"] == "crash" else 0

    results = {}                                     # mode == "all": every task in turn, each with its own limits
    for tid in task_ids:
        try:
            results[tid] = run_model(env, tid, seed, client, model, append_text, limits, out / f"episode-{tid}.jsonl")
        except Exception as exc:                     # one broken task must not stop the others
            print(f"task {tid} crashed: {type(exc).__name__}: {exc}", flush=True)
            results[tid] = {"termination": "crash", "steps": 0, "reward": {"total": None},
                            "error": f"{type(exc).__name__}: {exc}"}
    totals = [r["reward"].get("total") or 0 for r in results.values()]
    summary = {"run_id": run_id, "status": "completed", "mode": "all", "seed": seed, "model": model,
               "model_called": True, "append": append_info, "finished_at": now(),
               "solved": sum(r["termination"] == "success" for r in results.values()),
               "mean_reward": round(sum(totals) / len(totals), 3), "tasks": results}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n== All tasks ==", flush=True)
    for tid, r in results.items():
        total = r["reward"].get("total")
        print(f"{tid:<12} {r['termination']:<9} reward {total if total is not None else '-':<6} steps {r['steps']}", flush=True)
    print(f"solved {summary['solved']}/{len(results)}   mean reward {summary['mean_reward']}   logs: {out}", flush=True)
    return 1 if any(r["termination"] == "crash" for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
