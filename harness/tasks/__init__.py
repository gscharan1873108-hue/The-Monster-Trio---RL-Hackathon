"""Task registry. Each task builds from (task_id, seed): starting files, hidden checks, reference solution."""
from functools import lru_cache

from . import calc, csv_report, intervals, ledger, pricing, scheduler, semver, slugify, ttl_cache

_MODULES = [slugify, pricing, intervals, ttl_cache, csv_report, ledger, semver, scheduler, calc]
TASKS = {m.ID: m for m in _MODULES}
DIFFICULTY = {m.ID: m.DIFFICULTY for m in _MODULES}
DEMO_TASK = "slugify"


@lru_cache(maxsize=64)
def build_task(task_id, seed=0):
    """The same (task_id, seed) always yields the same starting files and hidden checks."""
    if task_id not in TASKS:
        raise KeyError(f"unknown task '{task_id}'. Available: {', '.join(TASKS)}")
    return TASKS[task_id].build(int(seed))
