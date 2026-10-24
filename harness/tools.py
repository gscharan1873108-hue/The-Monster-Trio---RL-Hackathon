"""Tool schemas shown to the model, plus tolerant argument normalisation."""
import json
import re

INT, STR = "integer", "string"


def _tool(name, description, props, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "required": list(required), "properties": {
            key: {"type": kind, "description": text} for key, (kind, text) in props.items()}}}}


TOOLS = [
    _tool("list_files", "List the files in the project (recursively).",
          {"path": (STR, "Optional sub-directory, relative to the project root.")}),
    _tool("read_file", "Read a text file. Output is cut at 4000 characters; use start_line/end_line for long files.",
          {"path": (STR, "File path relative to the project root."),
           "start_line": (INT, "Optional first line to return (1-based)."),
           "end_line": (INT, "Optional last line to return (inclusive).")}, ["path"]),
    _tool("write_file", "Create or overwrite a text file with the full new content.",
          {"path": (STR, "File path relative to the project root."),
           "content": (STR, "The complete new file content.")}, ["path", "content"]),
    _tool("edit_file", "Replace one exact occurrence of `old` with `new` in a file. `old` must match exactly and be unique.",
          {"path": (STR, "File path relative to the project root."),
           "old": (STR, "Exact text to replace (must occur exactly once)."),
           "new": (STR, "Replacement text.")}, ["path", "old", "new"]),
    _tool("search_text", "Search the project's files for a regular expression (or plain text). Returns path:line: text.",
          {"pattern": (STR, "Regular expression or literal text."),
           "path": (STR, "Optional file or directory to search in.")}, ["pattern"]),
    _tool("run_python", "Run Python code in the project directory (20 s limit, no network) and return its output.",
          {"code": (STR, "Python source code to run.")}, ["code"]),
    _tool("run_tests", "Run the visible unittest tests in tests/. These are only a sample of the checks.",
          {"path": (STR, "Optional single test file, e.g. tests/test_x.py.")}),
    _tool("finish", "Call this once you believe the task is complete. It ends the episode.",
          {"summary": (STR, "Optional one-line summary of what you changed.")}),
]

SPECS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}
TOOL_NAMES = list(SPECS)

ALIASES = {
    "path": ["file_path", "filepath", "filename", "file", "relative_path", "directory", "dir", "test_file"],
    "content": ["contents", "text", "file_content", "data", "body", "source"],
    "old": ["old_str", "old_string", "old_text", "original", "find", "search", "target"],
    "new": ["new_str", "new_string", "new_text", "replacement", "replace", "with"],
    "code": ["script", "python", "python_code", "source", "src"],
    "pattern": ["query", "regex", "search", "text", "term", "keyword"],
    "start_line": ["start", "line_start", "from_line", "first_line", "offset"],
    "end_line": ["end", "line_end", "to_line", "last_line"],
    "summary": ["message", "result", "notes"],
}


def canonical_name(raw):
    """Map whatever the model called a tool ("functions.read_file", "Read-File") to a tool name, or None."""
    if not isinstance(raw, str):
        return None
    name = re.split(r"[<\s(]", raw.strip(), maxsplit=1)[0]
    name = re.split(r"[./:]", name)[-1].lower().replace("-", "_")
    return name if name in SPECS else None


def usage(name):
    spec = SPECS[name]
    parts = [f"{key}: {prop['type']}" + ("" if key in spec["required"] else "?")
             for key, prop in spec["properties"].items()]
    return f"{name}({', '.join(parts)})"


def _coerce(key, kind, value):
    if value is None:
        return None, None
    if kind == STR:
        if isinstance(value, str):
            return value, None
        if isinstance(value, (dict, list)):
            return json.dumps(value, indent=2), None
        if isinstance(value, (int, float, bool)):
            return str(value), None
        return None, f"argument '{key}' must be a string"
    if isinstance(value, bool):
        return None, f"argument '{key}' must be an integer"
    if isinstance(value, int):
        return value, None
    if isinstance(value, float) and value == int(value):
        return int(value), None
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value), None
    return None, f"argument '{key}' must be an integer"


def prepare_args(name, args):
    """Return (clean_args, problem, notes). Lenient about aliases, JSON types and extra arguments."""
    if not isinstance(args, dict):
        return None, "arguments must be a JSON object. Usage: " + usage(name), []
    spec, args = SPECS[name], dict(args)
    for canon, aliases in ALIASES.items():
        if canon in spec["properties"] and canon not in args:
            for alias in aliases:
                if alias in args and alias not in spec["properties"]:
                    args[canon] = args.pop(alias)
                    break
    clean, notes = {}, []
    for key, value in args.items():
        if key not in spec["properties"]:
            notes.append(f"ignored unexpected argument '{key}'")
            continue
        value, problem = _coerce(key, spec["properties"][key]["type"], value)
        if problem:
            return None, f"{problem}. Usage: {usage(name)}", notes
        if value is not None:
            clean[key] = value
    for key in spec["required"]:
        if key not in clean:
            return None, f"missing required argument '{key}'. Usage: {usage(name)}", notes
    return clean, None, notes
