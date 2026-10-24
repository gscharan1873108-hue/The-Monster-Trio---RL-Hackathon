"""Model clients (any OpenAI-compatible endpoint), reply parsing, offline mock models and the baselines."""
import copy
import json
import re
from dataclasses import dataclass, field

from .tools import SPECS, TOOLS, canonical_name


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: object          # exactly what the model sent: a JSON string, or a dict from lenient providers
    source: str = "native"     # "native" tool call or "text" (found in the reply text)

    def parse(self):
        """Return (args, error). `args` is a dict when the arguments could be read."""
        raw = self.arguments
        if isinstance(raw, dict):
            return raw, None
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return {}, None
        if not isinstance(raw, str):
            return None, "arguments must be a JSON object"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError as exc:
            fenced = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip())
            try:
                args = json.loads(fenced)
            except json.JSONDecodeError:
                return None, f"arguments are not valid JSON ({exc.msg} at position {exc.pos}); send one JSON object"
        if isinstance(args, str):                       # double-encoded JSON
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                pass
        if not isinstance(args, dict):
            return None, "arguments must be a JSON object"
        return args, None

    def history_arguments(self):
        """Arguments as stored in the conversation; unreadable ones become {} so every provider accepts them."""
        args, error = self.parse()
        return json.dumps(args) if error is None else "{}"


@dataclass
class Reply:
    text: str | None
    tool_calls: list = field(default_factory=list)
    raw: str = ""
    tokens: int = 0
    finish_reason: str | None = None
    sent: list | None = None
    notes: list = field(default_factory=list)


# ------------------------------------------------------------ text tool-call fallback
def extract_text_calls(text, step):
    """Find tool calls written as text (JSON in code fences, <tool_call> tags or bare JSON)."""
    if not text:
        return []
    candidates = [m.group(1) for m in re.finditer(r"<tool_call>(.*?)</tool_call>", text, re.S)]
    candidates += [m.group(1) for m in re.finditer(r"```(?:json|tool_call|tool|python)?\s*(.*?)```", text, re.S)]
    if not candidates:
        candidates = [text]
    decoder, found = json.JSONDecoder(), []
    for chunk in candidates:
        index = 0
        while True:
            start = chunk.find("{", index)
            if start < 0:
                break
            try:
                obj, end = decoder.raw_decode(chunk, start)
            except json.JSONDecodeError:
                index = start + 1
                continue
            index = end
            for item in (obj if isinstance(obj, list) else [obj]):
                call = _call_from_object(item, len(found), step)
                if call:
                    found.append(call)
    return found


def _call_from_object(obj, index, step):
    if not isinstance(obj, dict):
        return None
    name = obj.get("tool") or obj.get("name") or obj.get("function") or obj.get("tool_name") or obj.get("action")
    if isinstance(name, dict):
        obj, name = name, name.get("name")
    if canonical_name(name) is None:
        return None
    args = obj.get("arguments", obj.get("args", obj.get("parameters", obj.get("input", obj.get("params", {})))))
    return ToolCall(f"text_{step}_{index}", name, args if isinstance(args, (dict, str)) else {}, source="text")


# ------------------------------------------------------------ real models
TEXT_MODE_NOTE = (
    "\n\nThis endpoint does not accept native tool calls, so call tools by writing JSON in your reply, one object "
    'per tool call, each in its own ```json block, for example:\n```json\n{"tool": "read_file", "arguments": '
    '{"path": "README.md"}}\n```\nYou may write up to 10 such blocks per reply. Tools:\n'
    + "\n".join(f"- {t['function']['name']}: {t['function']['description']} "
                f"Arguments: {json.dumps(t['function']['parameters']['properties'])}" for t in TOOLS))


def to_text_messages(messages):
    """Re-express a tool-call conversation as plain chat messages for endpoints without tool support."""
    out = []
    for message in copy.deepcopy(messages):
        role = message["role"]
        if role == "assistant" and message.get("tool_calls"):
            blocks = []
            for call in message["tool_calls"]:
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                blocks.append("```json\n" + json.dumps({"tool": call["function"]["name"], "arguments": arguments}) + "\n```")
            content = ((message.get("content") or "") + "\n" + "\n".join(blocks)).strip()
            message = {"role": "assistant", "content": content}
        elif role == "tool":
            message = {"role": "user", "content": "Tool result:\n" + str(message.get("content"))}
        else:
            message = {"role": role, "content": message.get("content") or "(empty)"}
        if out and out[-1]["role"] == message["role"] == "user":
            out[-1]["content"] += "\n\n" + message["content"]
        else:
            out.append(message)
    if out and out[0]["role"] == "system":
        out[0]["content"] += TEXT_MODE_NOTE
    return out


def _content_text(content):
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content) or None
    return content


class OpenAIClient:
    """Calls any model through an OpenAI-compatible endpoint (MODEL, API_KEY, BASE_URL)."""

    def __init__(self, model, api_key, base_url=None, max_tokens=None):
        import openai
        self.openai = openai
        self.client = openai.OpenAI(api_key=api_key, base_url=base_url or None, max_retries=2)
        self.model, self.max_tokens = model, max_tokens
        self.text_mode = False
        self.token_param = "max_tokens"

    def start(self, task):
        self.text_mode = False

    def prepare(self, messages):
        return to_text_messages(messages) if self.text_mode else copy.deepcopy(messages)

    def _kwargs(self, messages, timeout):
        sent = self.prepare(messages)
        kwargs = dict(model=self.model, messages=sent, timeout=timeout)
        if not self.text_mode:
            kwargs["tools"] = TOOLS
        if self.max_tokens:
            kwargs[self.token_param] = self.max_tokens
        return sent, kwargs

    def complete(self, messages, tools, timeout):
        notes = []
        for attempt in range(3):
            sent, kwargs = self._kwargs(messages, timeout)
            try:
                response = self.client.chat.completions.create(**kwargs)
                break
            except self.openai.BadRequestError as exc:
                text = str(exc).lower()
                if attempt < 2 and self.max_tokens and self.token_param == "max_tokens" and "max_completion_tokens" in text:
                    self.token_param = "max_completion_tokens"
                    notes.append("switched max_tokens -> max_completion_tokens")
                elif attempt < 2 and not self.text_mode and re.search(r"\btools?\b|function", text) \
                        and not re.search(r"context|too long|maximum", text):
                    self.text_mode = True
                    notes.append("endpoint rejected native tool calls: switched to text tool calls")
                else:
                    raise
        choice = response.choices[0]
        message = choice.message
        calls = []
        for index, call in enumerate(getattr(message, "tool_calls", None) or []):
            function = getattr(call, "function", None)
            calls.append(ToolCall(id=getattr(call, "id", None) or f"call_{index}",
                                  name=(getattr(function, "name", "") or ""),
                                  arguments=(getattr(function, "arguments", "") or "")))
        usage = getattr(response, "usage", None)
        return Reply(text=_content_text(message.content), tool_calls=calls, raw=response.model_dump_json(),
                     tokens=getattr(usage, "total_tokens", 0) or 0, finish_reason=getattr(choice, "finish_reason", None),
                     sent=sent, notes=notes)


# ------------------------------------------------------------ offline mock models
class MockClient:
    """Scripted stand-ins so the harness runs with no API key and robustness can be demonstrated.

    solver  writes the reference solution, runs the tests, finishes.   idle   finishes at once.
    cheater probes the sandbox, tries to edit tests, then finishes.     chaos  misbehaves, then solves.
    text    sends tool calls as text only (no native tool calls).        loop   never finishes.
    """

    KINDS = ("solver", "idle", "cheater", "chaos", "text", "loop")

    def __init__(self, kind):
        self.kind, self.turn, self.task = kind, 0, None

    def start(self, task):
        self.task, self.turn = task, 0

    def prepare(self, messages):
        return copy.deepcopy(messages)

    def _solve_calls(self):
        calls = [("write_file", {"path": p, "content": c}) for p, c in self.task.reference.items()]
        return calls + [("run_tests", {})]

    @staticmethod
    def _native(turn, calls):
        return [ToolCall(f"mock-{turn}-{i}", name, json.dumps(args)) for i, (name, args) in enumerate(calls)]

    def complete(self, messages, tools, timeout):
        self.turn += 1
        turn, kind, text, calls = self.turn, self.kind, None, []
        if kind == "solver":
            calls = self._solve_calls() if turn == 1 else [("finish", {"summary": "applied the reference solution"})]
        elif kind == "idle":
            calls = [("finish", {})]
        elif kind == "loop":
            calls = [("list_files", {})]
        elif kind == "text":
            if turn == 1:
                blocks = "\n".join("```json\n" + json.dumps({"tool": n, "arguments": a}) + "\n```" for n, a in self._solve_calls())
                text = "I will write the fix now.\n" + blocks
            else:
                text = '{"tool": "finish", "arguments": {}}'
        elif kind == "cheater":
            protected = (self.task.protected or ("tests/test_x.py",))[-1]
            script = [
                [("run_python", {"code": "print(open('/opt/sandbox/server.py').read()[:200])"})],
                [("run_python", {"code": "import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=2)"})],
                [("write_file", {"path": protected, "content": "import unittest\n"})],
                [("run_python", {"code": "import os\nprint(os.listdir('/app'), os.listdir('/proc/1'))"})],
                [("run_python", {"code": "import os\nopen('tests/test_zzz.py','w').write('x')\nos.remove('tests/__init__.py')"})],
                [("finish", {})],
            ]
            calls = script[min(turn, len(script)) - 1]
        elif kind == "chaos":
            if turn == 1:
                text = "Let me think about the problem before touching any tool."
            elif turn == 2:
                return Reply(None, [ToolCall("c1", "read_file", '{"path": "README.md"')], raw="{}", tokens=1)
            elif turn == 3:
                return Reply(None, [ToolCall("c2", "teleport", '{"where": "moon"}')], raw="{}", tokens=1)
            elif turn == 4:
                calls = [("list_files", {})] * 11
            elif turn == 5:
                return Reply(None, [ToolCall("c3", "functions.read_file", {"file_path": "README.md", "colour": "red"})],
                             raw="{}", tokens=1)
            elif turn == 6:
                calls = self._solve_calls()
            else:
                calls = [("finish", {})]
        reply = Reply(text=text, tool_calls=self._native(turn, calls) if kind != "text" else [], raw=json.dumps(
            {"mock": kind, "turn": turn}), tokens=0)
        return reply


def make_client(model, api_key, base_url, max_tokens=None):
    if model.startswith("mock/"):
        kind = model.split("/", 1)[1]
        if kind not in MockClient.KINDS:
            raise ValueError("mock models are: " + ", ".join("mock/" + k for k in MockClient.KINDS))
        return MockClient(kind)
    if not api_key:
        raise ValueError("API_KEY is not set")
    return OpenAIClient(model, api_key, base_url, max_tokens)


# ------------------------------------------------------------ baselines
def oracle_actions(task):
    """The reference solution as (tool, args) actions, then the visible tests. Must score full marks."""
    return [("write_file", {"path": p, "content": c}) for p, c in task.reference.items()] + [("run_tests", {})]


def noop_actions(task):
    """An agent that gives up immediately. Must score about zero."""
    return []
