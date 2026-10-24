"""Hard: dependency scheduling (deterministic topological order, cycles, critical path, worker schedule)."""
from .base import REF, Case, finalize, fill, rng_for

ID, DIFFICULTY = "scheduler", "hard"

STARTING = '''class CycleError(ValueError):
    def __init__(self, stuck):
        super().__init__("dependency cycle among: " + ", ".join(stuck))
        self.stuck = stuck


def topo_order(deps):
    order, seen = [], set()

    def visit(name):
        if name in seen:
            return
        seen.add(name)
        for dep in deps[name]:
            visit(dep)
        order.append(name)

    for name in deps:
        visit(name)
    return order


def critical_path(tasks):
    order = topo_order({name: task.get("deps", []) for name, task in tasks.items()})
    best = {}
    for name in order:
        base = max((best[d] for d in tasks[name].get("deps", [])), key=lambda b: b[0], default=(0, []))
        best[name] = (base[0] + tasks[name]["duration"], base[1] + [name])
    if not best:
        return {"duration": 0, "path": []}
    total, path = max(best.values(), key=lambda b: b[0])
    return {"duration": total, "path": path}


def schedule(tasks, workers):
    raise NotImplementedError
'''

REFERENCE = '''import heapq


class CycleError(ValueError):
    def __init__(self, stuck):
        super().__init__("dependency cycle among: " + ", ".join(stuck))
        self.stuck = stuck


def _deps_of(tasks):
    deps = {}
    for name, task in tasks.items():
        duration = task.get("duration")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise ValueError(f"task {name!r}: duration must be an int >= 0")
        deps[name] = list(task.get("deps", []))
    return deps


def topo_order(deps):
    remaining = {name: set(ds) for name, ds in deps.items()}
    dependents = {name: [] for name in deps}
    for name, ds in remaining.items():
        for dep in ds:
            if dep not in deps:
                raise ValueError(f"unknown dependency {dep!r} for {name!r}")
            dependents[dep].append(name)
    ready = [name for name, ds in remaining.items() if not ds]
    heapq.heapify(ready)
    order = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for other in dependents[name]:
            remaining[other].discard(name)
            if not remaining[other]:
                heapq.heappush(ready, other)
    if len(order) != len(deps):
        done = set(order)
        raise CycleError(sorted(name for name in deps if name not in done))
    return order


def critical_path(tasks):
    deps = _deps_of(tasks)
    best = {}
    for name in topo_order(deps):
        candidates = [(best[d][0] + tasks[name]["duration"], best[d][1] + [name]) for d in set(deps[name])]
        if not candidates:
            candidates = [(tasks[name]["duration"], [name])]
        best[name] = min(candidates, key=lambda c: (-c[0], c[1]))
    if not best:
        return {"duration": 0, "path": []}
    total, path = min(best.values(), key=lambda c: (-c[0], c[1]))
    return {"duration": total, "path": path}


def schedule(tasks, workers):
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be an int >= 1")
    deps = _deps_of(tasks)
    topo_order(deps)
    waiting = {name: set(ds) for name, ds in deps.items()}
    done, running, start, end = set(), [], {}, {}
    now = 0
    while waiting or running:
        ready = sorted(name for name, ds in waiting.items() if ds <= done)
        for name in ready[:workers - len(running)]:
            del waiting[name]
            start[name] = now
            end[name] = now + tasks[name]["duration"]
            running.append((end[name], name))
        now = min(finish for finish, _ in running)
        finished = [name for finish, name in running if finish == now]
        running = [(finish, name) for finish, name in running if finish != now]
        done.update(finished)
    return {"start": start, "makespan": max(end.values(), default=0)}
'''

README = '''# scheduler

`scheduler.py` plans work from a dependency graph. Task names are strings. `deps` maps a name to the list of
names it depends on (duplicates are ignored); `tasks` maps a name to `{"deps": [..], "duration": int >= 0}`
(`deps` is optional). Sample task names in this project look like `__EXAMPLE__`.

- `CycleError(ValueError)` has `.stuck`: the sorted names that could not be ordered (members of a cycle and
  everything that depends on one).
- `topo_order(deps)`: a topological order in which every task comes after all its dependencies. Whenever
  several tasks are ready the **alphabetically smallest** goes first. A dependency on an unknown name raises
  `ValueError`; a cycle (including a task that depends on itself) raises `CycleError`.
- `critical_path(tasks)`: returns `{"duration": total, "path": [names]}` for the dependency chain with the
  largest total duration (sum over the tasks on the chain, in dependency order). If several chains tie, pick
  the one whose list of names is smallest when compared as Python lists. No tasks gives
  `{"duration": 0, "path": []}`. A bad duration raises `ValueError`.
- `schedule(tasks, workers)`: simulate `workers` identical workers (an int >= 1, else `ValueError`).
  At time 0 and each time one or more tasks finish, all tasks whose dependencies are finished are "ready";
  they are started in alphabetical order on free workers until none is free. A task that finishes at time `t`
  frees its worker and unlocks its dependents at time `t`. Returns
  `{"start": {name: start_time}, "makespan": time_when_everything_is_finished}`; no tasks gives makespan 0.
  Cycles and unknown dependencies raise as in `topo_order`.
'''

TESTS = '''import unittest

from scheduler import CycleError, critical_path, topo_order


class SchedulerTests(unittest.TestCase):
    def test_chain(self):
        self.assertEqual(topo_order({"c": ["b"], "b": ["a"], "a": []}), ["a", "b", "c"])

    def test_alphabetical_tie_break(self):
        self.assertEqual(topo_order({"z": [], "a": [], "m": ["z"]}), ["a", "z", "m"])

    def test_cycle(self):
        with self.assertRaises(CycleError):
            topo_order({"a": ["b"], "b": ["a"]})

    def test_critical_path(self):
        tasks = {"a": {"duration": 2}, "b": {"deps": ["a"], "duration": 3}, "c": {"deps": ["a"], "duration": 1}}
        self.assertEqual(critical_path(tasks), {"duration": 5, "path": ["a", "b"]})


if __name__ == "__main__":
    unittest.main()
'''

PREFIXES = ["build", "task", "job", "step", "unit"]


def random_dag(rng, prefix, n, max_dur, edge_p):
    names = [f"{prefix}{i:02d}" for i in range(n)]
    labels = names[:]
    rng.shuffle(labels)                       # names are not in topological order
    tasks = {}
    for i, label in enumerate(labels):
        deps = [labels[j] for j in range(i) if rng.random() < edge_p]
        tasks[label] = {"deps": deps, "duration": rng.randint(1, max_dur)}
    items = list(tasks.items())
    rng.shuffle(items)
    return dict(items)


def deps_only(tasks):
    return {name: task["deps"] for name, task in tasks.items()}


def case(group, name, code, expect=REF):
    return Case(name, group, "import scheduler as m\n" + code, expect)


def err_code(call):
    return (f"try:\n    {call}\n    result = ['no error']\nexcept Exception as e:\n"
            "    result = [type(e).__name__, isinstance(e, ValueError), getattr(e, 'stuck', None)]\n")


def build(seed):
    rng = rng_for(ID, seed)
    prefix = rng.choice(PREFIXES)
    files = {"scheduler.py": STARTING, "README.md": fill(README, EXAMPLE=f"{prefix}01"),
             "tests/test_scheduler.py": TESTS}
    reference = {"scheduler.py": REFERENCE}
    t, r = "target", "regression"
    a, b, cc, d = (f"{prefix}{x}" for x in "abcd")
    diamond = {a: {"deps": [], "duration": 2}, b: {"deps": [a], "duration": 3},
               cc: {"deps": [a], "duration": 3}, d: {"deps": [b, cc], "duration": 1}}
    cases = [
        case(r, "chain_order", f"result = m.topo_order({{{cc!r}: [{b!r}], {b!r}: [{a!r}], {a!r}: []}})", [a, b, cc]),
        case(r, "empty_graph", "result = m.topo_order({})", []),
        case(r, "critical_path_unique_chain", "result = m.critical_path({'x': {'duration': 4}, "
             "'y': {'deps': ['x'], 'duration': 2}, 'z': {'duration': 1}})", {"duration": 6, "path": ["x", "y"]}),
        case(r, "critical_path_empty", "result = m.critical_path({})", {"duration": 0, "path": []}),
        case(t, "alphabetical_ready_order", f"result = m.topo_order({{'z': [], 'a': [], 'm': ['z'], 'b': ['a']}})",
             ["a", "b", "z", "m"]),
        case(t, "insertion_order_must_not_matter", "result = m.topo_order({'d': ['a', 'b'], 'b': [], 'a': [], 'c': ['b']})",
             ["a", "b", "c", "d"]),
        case("auto", "duplicate_deps_ignored", "result = m.topo_order({'b': ['a', 'a'], 'a': []})", ["a", "b"]),
        case(t, "cycle_reports_stuck_nodes", err_code("m.topo_order({'a': ['b'], 'b': ['a'], 'c': ['a'], 'd': []})"),
             ["CycleError", True, ["a", "b", "c"]]),
        case(t, "self_dependency_is_cycle", err_code("m.topo_order({'a': ['a']})"), ["CycleError", True, ["a"]]),
        case(t, "unknown_dependency", err_code("m.topo_order({'a': ['ghost']})"), ["ValueError", True, None]),
        case("auto", "critical_path_tie_breaks_alphabetically", f"result = m.critical_path({diamond!r})",
             {"duration": 6, "path": [a, b, d]}),
        case("auto", "critical_path_prefers_longer_duration", "result = m.critical_path({'a': {'duration': 1}, "
             "'b': {'deps': ['a'], 'duration': 1}, 'c': {'deps': ['b'], 'duration': 1}, 'x': {'duration': 5}})",
             {"duration": 5, "path": ["x"]}),
        case(t, "critical_path_tie_between_chains", "result = m.critical_path({'q': {'duration': 3}, 'a': {'duration': 1}, "
             "'b': {'deps': ['a'], 'duration': 2}})", {"duration": 3, "path": ["a", "b"]}),
        case(t, "critical_path_bad_duration", err_code("m.critical_path({'a': {'duration': -1}})"), ["ValueError", True, None]),
        case(t, "critical_path_cycle", err_code("m.critical_path({'a': {'deps': ['a'], 'duration': 1}})"),
             ["CycleError", True, ["a"]]),
        case(t, "schedule_diamond_two_workers", f"result = m.schedule({diamond!r}, 2)",
             {"start": {a: 0, b: 2, cc: 2, d: 5}, "makespan": 6}),
        case(t, "schedule_diamond_one_worker", f"result = m.schedule({diamond!r}, 1)",
             {"start": {a: 0, b: 2, cc: 5, d: 8}, "makespan": 9}),
        case(t, "schedule_zero_duration", "result = m.schedule({'a': {'duration': 0}, 'b': {'deps': ['a'], 'duration': 2}}, 1)",
             {"start": {"a": 0, "b": 0}, "makespan": 2}),
        case(t, "schedule_empty", "result = m.schedule({}, 3)", {"start": {}, "makespan": 0}),
        case(t, "schedule_bad_workers", err_code("m.schedule({'a': {'duration': 1}}, 0)"), ["ValueError", True, None]),
        case(t, "schedule_cycle", err_code("m.schedule({'a': {'deps': ['b'], 'duration': 1}, 'b': {'deps': ['a'], 'duration': 1}}, 2)"),
             ["CycleError", True, ["a", "b"]]),
    ]
    for i in range(6):
        tasks = random_dag(rng, prefix, rng.randint(6, 12), rng.choice([2, 3, 9]), rng.choice([0.2, 0.35]))
        cases.append(case("auto", f"generated_topo_{i}", f"result = m.topo_order({deps_only(tasks)!r})"))
        cases.append(case("auto", f"generated_critical_path_{i}", f"result = m.critical_path({tasks!r})"))
        cases.append(case(t, f"generated_schedule_{i}", f"result = m.schedule({tasks!r}, {rng.randint(1, 4)})"))
    intro = ("Task: `scheduler.py` has a topological sort that ignores cycles and ordering rules, a critical-path "
             "finder with wrong tie-breaking, and an unimplemented `schedule`. Implement everything exactly as "
             "README.md describes.")
    return finalize(ID, DIFFICULTY, "Build the dependency scheduler", intro, files, cases, reference, seed)
