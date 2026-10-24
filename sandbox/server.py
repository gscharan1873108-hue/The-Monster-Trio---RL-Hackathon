"""Sandbox service: runs the agent's tools inside an isolated workspace.

The container sits on an internal Docker network (no internet) and holds only the
agent's workspace. Hidden checks and expected answers never live here: the harness
sends check *code* at scoring time and compares the returned values itself.
Every tool process is demoted to an unprivileged uid with resource limits, so the
agent cannot read, signal or modify this server.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace")).resolve()
VERIFY_ROOT = Path(os.environ.get("VERIFY_DIR", tempfile.gettempdir())) / "rl-verify"
PORT = int(os.environ.get("PORT", "8000"))
AGENT_UID = int(os.environ.get("AGENT_UID", "1001"))
AGENT_GID = int(os.environ.get("AGENT_GID", "1001"))

POSIX = os.name == "posix"
DEMOTE = POSIX and os.geteuid() == 0      # drop to AGENT_UID only when started as root

MAX_OUTPUT = 4000          # characters returned to the agent per tool call
RUN_TIMEOUT = 20           # seconds for one run_python call
TEST_TIMEOUT = 30          # seconds for one run_tests call
CASE_TIMEOUT = 4           # seconds for one hidden check
VERIFY_BUDGET = 90         # seconds for a whole scoring request
VERIFY_WORKERS = 4
MAX_FILE_BYTES = 200_000
MAX_FILES = 300
MAX_BODY = 8_000_000
IGNORED_DIRS = {"__pycache__", ".pytest_cache"}

RLIMITS = [("CPU", 30), ("AS", 768 << 20), ("FSIZE", 10 << 20), ("NPROC", 128), ("NOFILE", 256), ("CORE", 0)]
LAUNCHER = (
    "import os, sys\n"
    "import resource\n"
    f"for _n, _v in {RLIMITS!r}:\n"
    "    resource.setrlimit(getattr(resource, 'RLIMIT_' + _n), (_v, _v))\n"
    "os.execv(sys.executable, [sys.executable] + sys.argv[1:])\n"
)

# Runs one hidden check: the check code assigns `result`; the value is printed between
# a one-time marker so output printed by the code under test cannot be mistaken for it.
CHECK_WRAPPER = r'''
import json, os, sys
_req = json.loads(sys.stdin.read())
_nonce, _code = _req["nonce"], _req["code"]
del _req
sys.path.append(os.getcwd())
_ns = {"__name__": "__check__"}
try:
    exec(compile(_code, "<check>", "exec"), _ns)
    _out = {"ok": True, "result": _ns.get("result"), "has_result": "result" in _ns}
except BaseException as _exc:
    _out = {"ok": False, "exc": type(_exc).__name__, "msg": str(_exc)[:200]}
def _default(o):
    return sorted(o) if isinstance(o, (set, frozenset)) else repr(o)
try:
    _text = json.dumps(_out, default=_default)
except Exception:
    _text = json.dumps({"ok": False, "exc": "Unserializable"})
sys.stdout.write("\n@@" + _nonce + "@@" + _text + "@@" + _nonce + "@@\n")
sys.stdout.flush()
'''

LOCK = threading.Lock()


# ----------------------------------------------------------------------------- helpers
def safe_path(relative) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("path must be a non-empty string")
    path = (WORKSPACE / relative.strip()).resolve()
    if path != WORKSPACE and WORKSPACE not in path.parents:
        raise ValueError("path must stay inside the project directory")
    return path


def rel(path: Path) -> str:
    return path.relative_to(WORKSPACE).as_posix()


def clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n[... {len(text) - limit} characters omitted ...]\n" + text[-half:]


def all_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not IGNORED_DIRS.intersection(path.parts):
            yield path


def chown_tree(root: Path):
    if not DEMOTE:
        return
    os.chown(root, AGENT_UID, AGENT_GID, follow_symlinks=False)
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            os.chown(os.path.join(dirpath, name), AGENT_UID, AGENT_GID, follow_symlinks=False)


def kill_agent_processes():
    """Kill everything the agent left running (same-uid processes other than this server)."""
    if not DEMOTE:
        return
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == os.getpid():
            continue
        try:
            if os.stat(f"/proc/{entry}").st_uid == AGENT_UID:
                os.kill(int(entry), 9)
        except OSError:
            pass


def child_env():
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "PYTHONUTF8": "1",
           "PYTHONIOENCODING": "utf-8", "HOME": str(WORKSPACE), "LANG": "C.UTF-8"}
    for key in ("SYSTEMROOT", "TEMP", "TMP"):      # needed by Python on Windows (local tests)
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def kill_group(proc):
    try:
        if POSIX:
            os.killpg(proc.pid, 9)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def run_child(args, cwd, timeout, stdin_data=None):
    """Run python with `args` as the agent's account. Returns (output, returncode, timed_out)."""
    argv = [sys.executable] + list(args)
    extra = {}
    if POSIX:
        argv = [sys.executable, "-c", LAUNCHER] + list(args)
        extra["start_new_session"] = True
        if DEMOTE:
            extra.update(user=AGENT_UID, group=AGENT_GID, extra_groups=[])
    with tempfile.TemporaryFile() as sink:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=child_env(), stdout=sink, stderr=subprocess.STDOUT,
                                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL, **extra)
        timed_out = False
        try:
            proc.communicate(stdin_data, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_group(proc)
            proc.wait()
        except OSError:
            pass
        kill_group(proc)                      # background children never outlive the call
        sink.seek(0)
        text = sink.read().decode("utf-8", errors="replace")
    return text, proc.returncode, timed_out


# ----------------------------------------------------------------------------- tools
def tool_list_files(args):
    root = safe_path(args.get("path") or ".")
    if not root.exists():
        raise FileNotFoundError(f"no such path: {args.get('path')}")
    files = [rel(p) for p in all_files(root)] if root.is_dir() else [rel(root)]
    if not files:
        return "(no files)"
    extra = f"\n[{len(files) - 300} more files not shown]" if len(files) > 300 else ""
    return "\n".join(files[:300]) + extra


def tool_read_file(args):
    path = safe_path(args["path"])
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {args['path']}")
    if path.stat().st_size > 1_000_000:
        raise ValueError("file is larger than 1 MB")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    start, end = args.get("start_line"), args.get("end_line")
    if start or end:
        first = max(1, start or 1)
        last = min(len(lines), end or len(lines))
        if first > last:
            raise ValueError(f"empty range: file has {len(lines)} lines")
        body = "".join(lines[first - 1:last])
        header = f"[lines {first}-{last} of {len(lines)}]\n"
    else:
        body, header = text, ""
    if len(body) > MAX_OUTPUT:
        body = body[:MAX_OUTPUT] + f"\n[cut at {MAX_OUTPUT} characters; file has {len(lines)} lines, use start_line/end_line to read more]"
    return header + body


def _writable(path: Path):
    if IGNORED_DIRS.intersection(path.parts):
        raise ValueError("cache directories are not writable")
    if path.is_dir():
        raise ValueError("path is a directory")


def tool_write_file(args):
    path, content = safe_path(args["path"]), args["content"]
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    _writable(path)
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(f"file is larger than {MAX_FILE_BYTES} bytes")
    if not path.exists() and sum(1 for _ in all_files(WORKSPACE)) >= MAX_FILES:
        raise ValueError(f"project already has {MAX_FILES} files")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))
    chown_tree(WORKSPACE)
    return f"wrote {len(content)} characters to {rel(path)}"


def tool_edit_file(args):
    path, old, new = safe_path(args["path"]), args["old"], args["new"]
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {args['path']}")
    if not old:
        raise ValueError("old must not be empty")
    text = path.read_text(encoding="utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        raise ValueError("old text not found; it must match the file exactly, including whitespace")
    if count > 1:
        raise ValueError(f"old text occurs {count} times; include more surrounding lines so it is unique")
    updated = text.replace(old, new, 1)
    if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(f"file would be larger than {MAX_FILE_BYTES} bytes")
    path.write_bytes(updated.encode("utf-8"))
    chown_tree(WORKSPACE)
    return f"edited {rel(path)}"


def tool_search_text(args):
    pattern = args["pattern"]
    try:
        regex = re.compile(pattern)
    except re.error:
        regex = re.compile(re.escape(pattern))
    root = safe_path(args.get("path") or ".")
    hits = []
    for path in ([root] if root.is_file() else all_files(root)):
        if path.stat().st_size > 1_000_000:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if regex.search(line):
                hits.append(f"{rel(path)}:{number}: {line.strip()[:200]}")
                if len(hits) >= 40:
                    return "\n".join(hits) + "\n[stopped after 40 matches]"
    return "\n".join(hits) if hits else "(no matches)"


def _summarise(text, code, timed_out, limit):
    if timed_out:
        return clip(text.strip() + f"\n[timed out after {limit}s and was stopped]")
    return clip((text.strip() or "(no output)") + f"\n[exit code {code}]")


def tool_run_python(args):
    code = args["code"]
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be a non-empty string")
    if len(code) > 100_000:
        raise ValueError("code is longer than 100000 characters")
    text, code_, timed_out = run_child(["-c", code], WORKSPACE, RUN_TIMEOUT)
    return _summarise(text, code_, timed_out, RUN_TIMEOUT)


def tool_run_tests(args):
    target = args.get("path")
    if target:
        path = safe_path(target)
        if not path.is_file() or path.suffix != ".py":
            raise FileNotFoundError(f"no such test file: {target}")
        argv = ["-m", "unittest", rel(path)[:-3].replace("/", ".")]
    else:
        argv = ["-m", "unittest", "discover", "-s", "tests", "-t", "."]
    text, code, timed_out = run_child(argv, WORKSPACE, TEST_TIMEOUT)
    return _summarise(text, code, timed_out, TEST_TIMEOUT)


TOOLS = {"list_files": tool_list_files, "read_file": tool_read_file, "write_file": tool_write_file,
         "edit_file": tool_edit_file, "search_text": tool_search_text, "run_python": tool_run_python,
         "run_tests": tool_run_tests}


# ----------------------------------------------------------------------------- endpoints
def do_reset(body):
    kill_agent_processes()
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    for child in WORKSPACE.iterdir():
        shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    for name, content in body["files"].items():
        path = safe_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
    chown_tree(WORKSPACE)
    if DEMOTE:                                    # clear what the agent left in /tmp
        tmp = Path(tempfile.gettempdir())
        for child in tmp.iterdir():
            try:
                if child.lstat().st_uid == AGENT_UID:
                    shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
            except OSError:
                pass
    return {"ok": True}


def do_tool(body):
    name, args = body["name"], body.get("args") or {}
    if name not in TOOLS:
        return {"output": f"error: unknown tool '{name}'", "is_error": True}
    try:
        return {"output": TOOLS[name](args), "is_error": False}
    except Exception as exc:                      # tool-level problems go back to the agent
        return {"output": f"error: {exc}", "is_error": True}


def run_case(index, code, scratch, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return {"ok": False, "exc": "VerifyBudget"}
    case_dir = scratch / f"c{index}"
    shutil.copytree(WORKSPACE, case_dir, symlinks=True, ignore=shutil.ignore_patterns(*IGNORED_DIRS))
    chown_tree(case_dir)
    nonce = secrets.token_hex(12)
    payload = json.dumps({"nonce": nonce, "code": code}).encode("utf-8")
    text, _rc, timed_out = run_child(["-P", "-s", "-c", CHECK_WRAPPER], case_dir, min(CASE_TIMEOUT, remaining), payload)
    if timed_out:
        return {"ok": False, "exc": "Timeout"}
    marker = re.escape(f"@@{nonce}@@")
    found = re.findall(marker + "(.*?)" + marker, text, re.S)
    if len(found) != 1:
        return {"ok": False, "exc": "Tamper" if found else "NoResult", "tamper": bool(found)}
    try:
        return json.loads(found[0])
    except ValueError:
        return {"ok": False, "exc": "BadResult", "tamper": True}


def do_verify(body):
    """Run each check against a throwaway copy of the workspace; return raw values only."""
    codes = [case["code"] for case in body["cases"]]
    if body.get("final"):
        kill_agent_processes()                    # nothing may keep running while the final score is taken
    VERIFY_ROOT.mkdir(parents=True, exist_ok=True)
    if POSIX:
        os.chmod(VERIFY_ROOT, 0o711)
    scratch = Path(tempfile.mkdtemp(prefix="v-", dir=VERIFY_ROOT))
    if POSIX:
        os.chmod(scratch, 0o711)
    deadline = time.monotonic() + VERIFY_BUDGET
    try:
        with ThreadPoolExecutor(VERIFY_WORKERS) as pool:
            results = list(pool.map(lambda item: run_case(item[0], item[1], scratch, deadline), enumerate(codes)))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"results": results}


def do_state(_body=None):
    files = {rel(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in all_files(WORKSPACE)}
    return {"files": files}


ROUTES_POST = {"/reset": do_reset, "/tool": do_tool, "/verify": do_verify}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True})
        elif self.path == "/state":
            with LOCK:
                self._send(200, do_state())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        handler = ROUTES_POST.get(self.path)
        if handler is None:
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                return self._send(413, {"error": "request too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            with LOCK:
                result = handler(body)
            self._send(200, result)
        except Exception as exc:
            self._send(400, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    chown_tree(WORKSPACE)
    print(f"sandbox listening on :{PORT}, workspace {WORKSPACE}, demote={DEMOTE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
