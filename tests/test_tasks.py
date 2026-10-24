"""Offline self-checks for the task set (no Docker, no sandbox): python -m unittest discover -s tests -t ."""
import unittest

from harness.tasks import TASKS, build_task
from harness.tasks.base import run_locally, values_equal

SEEDS = range(8)


class TaskInvariants(unittest.TestCase):
    def test_reference_passes_every_hidden_case(self):
        for task_id in TASKS:
            for seed in SEEDS:
                task = build_task(task_id, seed)
                results = run_locally({**task.files, **task.reference}, [c.code for c in task.cases])
                bad = [c.name for c, r in zip(task.cases, results)
                       if not (r.get("ok") and values_equal(r["result"], c.expect, c.compare))]
                self.assertEqual(bad, [], f"{task_id} seed {seed}: reference fails {bad}")

    def test_starting_code_earns_nothing(self):
        for task_id in TASKS:
            for seed in SEEDS:
                task = build_task(task_id, seed)
                results = run_locally(task.files, [c.code for c in task.cases])
                passed = [c.name for c, r in zip(task.cases, results)
                          if c.group == "target" and r.get("ok") and values_equal(r["result"], c.expect, c.compare)]
                self.assertEqual(passed, [], f"{task_id} seed {seed}: target cases pass on the starting code")
                self.assertGreaterEqual(sum(c.group == "target" for c in task.cases), 8, f"{task_id} seed {seed}")

    def test_visible_tests_pass_with_reference(self):
        import os
        import subprocess
        import sys
        import tempfile
        for task_id in TASKS:
            task = build_task(task_id, 0)
            with tempfile.TemporaryDirectory() as tmp:
                for name, content in {**task.files, **task.reference}.items():
                    path = os.path.join(tmp, *name.split("/"))
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as handle:
                        handle.write(content.encode("utf-8"))
                done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                                      cwd=tmp, capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, f"{task_id}: {done.stderr[-600:]}")

    def test_same_seed_same_world(self):
        for task_id in TASKS:
            self.assertEqual(build_task(task_id, 3).files, build_task(task_id, 3).files)
            self.assertNotEqual(build_task(task_id, 1).files, build_task(task_id, 2).files, task_id)

    def test_task_count_and_levels(self):
        self.assertGreaterEqual(len(TASKS), 5)
        self.assertGreaterEqual(len({build_task(t, 0).difficulty for t in TASKS}), 2)


if __name__ == "__main__":
    unittest.main()
