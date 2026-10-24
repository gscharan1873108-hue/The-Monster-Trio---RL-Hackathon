"""Task container, the seeded RNG, and expected-value derivation shared by every task module."""
import json
import os
import random
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any

REF = object()   # expected value is derived from the reference solution when the task is built

RULES = ("The tests in tests/ are only a sample: hidden checks exercise the full behaviour described in "
         "README.md on inputs you have not seen, so do not special-case the examples. "
         "Do not modify existing files under tests/. Call `finish` when you are done.")


@dataclass
class Case:
    name: str
    group: str                 # "target" (fails on the starting code), "regression" (passes on it), or "auto"
    code: str                  # runs in the sandbox and must assign `result`
    expect: Any = REF
    compare: str = "exact"     # "exact" or "unordered" (compare lists as multisets)


@dataclass
class Task:
    id: str
    difficulty: str
    title: str
    instructions: str
    files: dict                # starting project, path -> text
    cases: list                # hidden checks (never sent to the agent)
    reference: dict            # files that solve the task, path -> text
    seed: int = 0
    protected: tuple = field(default=())   # existing visible tests: changing them is an integrity violation


def rng_for(task_id, seed):
    return random.Random(f"{task_id}|{seed}")


def fill(text, **values):
    for key, value in values.items():
        text = text.replace(f"__{key}__", str(value))
    return text


def call_case(group, name, module, expr, expect=REF, compare="exact", setup=""):
    code = f"{setup}\nimport {module} as m\nresult = {expr}\n"
    return Case(name, group, code, expect, compare)


def raises_case(group, name, module, expr, error="ValueError", setup=""):
    code = (f"{setup}\nimport {module} as m\n"
            f"try:\n    {expr}\n    result = 'no error'\n"
            f"except {error}:\n    result = {error!r}\n"
            f"except Exception as _e:\n    result = 'wrong error: ' + type(_e).__name__\n")
    return Case(name, group, code, error)


def values_equal(a, b, mode="exact"):
    """Meaningful comparison: numbers by value, tuples as lists, optional order-insensitive lists."""
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, int) and isinstance(b, int):
            return a == b
        return a == b or abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(values_equal(a[k], b[k], mode) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False
        if mode == "unordered":
            key = lambda item: json.dumps(item, sort_keys=True, default=repr)
            a, b = sorted(a, key=key), sorted(b, key=key)
        return all(values_equal(x, y, mode) for x, y in zip(a, b))
    return a == b


_DRIVER = r'''
import json, os, sys
sys.path.append(os.getcwd())
codes = json.loads(sys.stdin.buffer.read().decode("utf-8"))
root = os.getcwd()
base = set(sys.modules)
def _default(o):
    return sorted(o) if isinstance(o, (set, frozenset)) else repr(o)
out = []
for code in codes:
    ns = {"__name__": "__derive__"}
    try:
        exec(compile(code, "<case>", "exec"), ns)
        out.append({"ok": True, "result": ns.get("result")})
    except BaseException as exc:
        out.append({"ok": False, "exc": type(exc).__name__, "msg": str(exc)[:200]})
    for name in set(sys.modules) - base:
        mod = sys.modules.get(name)
        if str(getattr(mod, "__file__", "") or "").startswith(root):
            del sys.modules[name]
sys.stdout.write("\n@@DERIVED@@" + json.dumps(out, default=_default))
'''


def run_locally(project, codes):
    """Run check codes against a project (path -> text) in a trusted local subprocess."""
    with tempfile.TemporaryDirectory(prefix="derive-") as tmp:
        for name, content in project.items():
            path = os.path.join(tmp, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(content.encode("utf-8"))
        done = subprocess.run([sys.executable, "-P", "-s", "-c", _DRIVER], cwd=tmp, capture_output=True,
                              input=json.dumps(codes).encode("utf-8"), timeout=120,
                              env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"})
    out = done.stdout.decode("utf-8", errors="replace")
    if "@@DERIVED@@" not in out:
        raise RuntimeError("local check run failed: " + done.stderr.decode("utf-8", errors="replace")[-500:])
    return json.loads(out.rsplit("@@DERIVED@@", 1)[1])


def resolve_cases(files, reference, cases):
    """Derive REF expectations from the reference, then settle "auto" groups using the starting code."""
    pending = [c for c in cases if c.expect is REF]
    if pending:
        results = run_locally({**files, **reference}, [c.code for c in pending])
        for case, result in zip(pending, results):
            if not result.get("ok"):
                raise RuntimeError(f"reference solution fails case '{case.name}': {result.get('exc')}: {result.get('msg')}")
            case.expect = result["result"]
    # Every case is checked against the starting code, so a "target" can never pay out for doing nothing.
    results = run_locally(files, [c.code for c in cases])
    for case, result in zip(cases, results):
        passes = bool(result.get("ok")) and values_equal(result["result"], case.expect, case.compare)
        if case.group == "regression" and not passes:
            raise RuntimeError(f"regression case '{case.name}' fails on the starting code")
        case.group = "regression" if passes else "target"


def finalize(task_id, difficulty, title, intro, files, cases, reference, seed):
    files = dict(files)
    files.setdefault("tests/__init__.py", "")
    if "README.md" in files:
        files["README.md"] += f"\n(Project variant: seed {seed})\n"
    resolve_cases(files, reference, cases)
    protected = tuple(sorted(p for p in files if p.startswith("tests/")))
    return Task(id=task_id, difficulty=difficulty, title=title, instructions=f"{intro}\n\n{RULES}",
                files=files, cases=cases, reference=reference, seed=seed, protected=protected)
