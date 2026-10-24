"""The environment: reset / step / score, backed by the sandbox service. The verifier lives here."""
import hashlib
import json
import posixpath

import requests

from .tasks import build_task
from .tasks.base import values_equal

PASS_SCORE = 0.95          # an episode counts as a success at or above this score
INTEGRITY_PENALTY = 0.3    # tampering with the visible tests or spoofing a check result


class SandboxDown(RuntimeError):
    """The sandbox stopped answering; the episode cannot continue."""


def hash_files(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:8]


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Env:
    def __init__(self, sandbox_url, tool_timeout=60, verify_timeout=120):
        self.url = sandbox_url.rstrip("/")
        self.tool_timeout, self.verify_timeout = tool_timeout, verify_timeout
        self.task = None
        self.start_files, self.start_hash, self.reset_ok = {}, None, True
        self.verdict, self._cache, self._failures = {}, None, 0

    # ------------------------------------------------------------ transport
    def _post(self, path, payload, timeout):
        try:
            response = requests.post(self.url + path, json=payload, timeout=timeout)
            response.raise_for_status()
            self._failures = 0
            return response.json()
        except requests.RequestException:
            self._failures += 1
            if self._failures >= 3:
                raise SandboxDown(f"sandbox failed {self._failures} requests in a row")
            raise

    def _state(self):
        try:
            files = requests.get(self.url + "/state", timeout=self.tool_timeout).json()["files"]
            self._failures = 0
            return files
        except (requests.RequestException, ValueError, KeyError):
            self._failures += 1
            if self._failures >= 3:
                raise SandboxDown("sandbox did not return its state")
            raise

    # ------------------------------------------------------------ reset
    def reset(self, task_id, seed):
        """Start a clean episode. The same (task_id, seed) always gives the same files and state hash."""
        self.task = build_task(task_id, seed)
        self._post("/reset", {"files": self.task.files}, self.tool_timeout)
        self.start_files = self._state()
        self.start_hash = hash_files(self.start_files)
        expected = hash_files({p: digest(c) for p, c in self.task.files.items()})
        self.reset_ok = self.start_hash == expected
        self.verdict, self._cache = {}, None
        listing = "\n".join(f"- {p}" for p in sorted(self.task.files))
        return (f"Task: {self.task.instructions}\n\nProject files:\n{listing}\n\n"
                "The project is in the current directory. Start by reading README.md, use the tools to inspect "
                "and change the code, run the tests, then call `finish`.")

    # ------------------------------------------------------------ step
    def _is_protected(self, name, args):
        if name not in ("write_file", "edit_file"):
            return None
        path = str(args.get("path", "")).replace("\\", "/").strip()
        if path.startswith("/workspace/"):
            path = path[len("/workspace/"):]
        path = posixpath.normpath(path)
        return path if path in self.task.protected else None

    def step(self, name, args):
        """Run one tool call. Returns (text, is_error). Tool-level problems are returned, not raised."""
        blocked = self._is_protected(name, args)
        if blocked:
            return (f"error: {blocked} is a visible test file and is read-only. Fix the source code instead "
                    "(you may add new test files).", True)
        try:
            result = self._post("/tool", {"name": name, "args": args}, self.tool_timeout)
        except requests.Timeout:
            return f"error: the tool call did not finish within {self.tool_timeout} seconds", True
        except requests.RequestException as exc:
            return f"error: the sandbox could not run the tool ({type(exc).__name__}); try again", True
        return result["output"], result["is_error"]

    def state_hash(self):
        return hash_files(self._state())

    def files_changed(self):
        now = self._state()
        paths = set(now) | set(self.start_files)
        return sum(1 for p in paths if now.get(p) != self.start_files.get(p))

    # ------------------------------------------------------------ score
    def score(self, final=False):
        """Programmatic verifier: reward components and their total (see README, "Reward").

        tests_passed   = 0.7 x share of target checks passed
        no_regressions = 0.3 x target share x share of regression checks passed
                         (scaled by progress, so doing nothing earns 0)
        integrity      = -0.3 if visible tests were changed or a check result was spoofed
        """
        files = self._state()
        key = hash_files(files)
        if not final and self._cache and self._cache[0] == key:
            return dict(self._cache[1])
        cases = self.task.cases
        results = self._post("/verify", {"cases": [{"code": c.code} for c in cases], "final": final},
                             self.verify_timeout)["results"]
        tally = {"target": [0, 0], "regression": [0, 0]}
        failed, tampered = [], []
        for case, result in zip(cases, results):
            tally[case.group][1] += 1
            if result.get("tamper"):
                tampered.append(case.name)
            if result.get("ok") and not result.get("tamper") and values_equal(result.get("result"), case.expect, case.compare):
                tally[case.group][0] += 1
            else:
                failed.append(case.name)
        target = tally["target"][0] / max(1, tally["target"][1])
        regression = tally["regression"][0] / max(1, tally["regression"][1])
        changed = [p for p in self.task.protected if files.get(p) != digest(self.task.files[p])]
        penalty = INTEGRITY_PENALTY if (changed or tampered) else 0.0
        components = {"tests_passed": round(0.7 * target, 4), "no_regressions": round(0.3 * target * regression, 4),
                      "integrity_penalty": -penalty if penalty else 0.0}
        components["total"] = round(max(0.0, sum(components.values())), 4)
        self.verdict = {"target": f"{tally['target'][0]}/{tally['target'][1]}",
                        "regression": f"{tally['regression'][0]}/{tally['regression'][1]}",
                        "failed_cases": failed, "tampered_cases": tampered, "protected_files_changed": changed}
        if not final:
            self._cache = (key, components)
        return components
