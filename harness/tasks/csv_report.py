"""Medium: fix a two-module CSV report (quoted-field parser + decimal-exact group statistics)."""
from decimal import ROUND_HALF_UP, Decimal

from .base import call_case, finalize, fill, raises_case, rng_for

ID, DIFFICULTY = "csv_report", "medium"

PARSE_STARTING = '''def parse_csv(text):
    lines = text.splitlines()
    if not lines:
        return []
    header = lines[0].split(",")
    return [dict(zip(header, line.split(","))) for line in lines[1:]]


def parse_amount(text):
    return float(text)
'''

AGG_STARTING = '''from csvparse import parse_amount


def group_stats(rows, key, value):
    groups = {}
    for row in rows:
        groups.setdefault(row[key], []).append(parse_amount(row[value]))
    out = []
    for name in sorted(groups):
        amounts = groups[name]
        out.append({"key": name, "count": len(amounts), "total": round(sum(amounts), 2),
                    "mean": round(sum(amounts) / len(amounts), 2), "min": min(amounts), "max": max(amounts)})
    return out
'''

PARSE_REFERENCE = '''import re
from decimal import Decimal

_NUMBER = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)?(?:\\.[0-9]+)?")


def _records(text):
    records, row, field = [], [], []
    in_quotes = quoted = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                field.append(ch)
        elif ch == '"':
            in_quotes = quoted = True
        elif ch == ",":
            row.append("".join(field))
            field = []
        elif ch == "\\r":
            pass
        elif ch == "\\n":
            row.append("".join(field))
            if not (len(row) == 1 and row[0].strip() == "" and not quoted):
                records.append(row)
            row, field, quoted = [], [], False
        else:
            field.append(ch)
        i += 1
    if in_quotes:
        raise ValueError("unterminated quoted field")
    if field or row or quoted:
        row.append("".join(field))
        if not (len(row) == 1 and row[0].strip() == "" and not quoted):
            records.append(row)
    return records


def parse_csv(text):
    records = _records(text)
    if not records:
        return []
    header = [name.strip() for name in records[0]]
    rows = []
    for number, record in enumerate(records[1:], start=1):
        if len(record) > len(header):
            raise ValueError(f"row {number} has too many fields")
        rows.append(dict(zip(header, record + [""] * (len(header) - len(record)))))
    return rows


def parse_decimal(text):
    s = text.strip()
    if s == "":
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    elif s.startswith("-"):
        negative, s = True, s[1:].strip()
    if s.startswith("$"):
        s = s[1:].strip()
    if s in ("", ".") or not _NUMBER.fullmatch(s):
        raise ValueError(f"not an amount: {text!r}")
    value = Decimal(s.replace(",", ""))
    return -value if negative else value


def parse_amount(text):
    value = parse_decimal(text)
    return None if value is None else float(value)
'''

AGG_REFERENCE = '''from decimal import ROUND_HALF_UP, Decimal

from csvparse import parse_decimal

CENT = Decimal("0.01")


def group_stats(rows, key, value):
    groups = {}
    for number, row in enumerate(rows, start=1):
        if key not in row or value not in row:
            raise ValueError(f"row {number}: missing column")
        try:
            amount = parse_decimal(row[value])
        except ValueError as exc:
            raise ValueError(f"row {number}: {exc}") from None
        if amount is None:
            continue
        groups.setdefault(row[key].strip() or "(none)", []).append(amount)
    out = []
    for name in sorted(groups):
        amounts = groups[name]
        total = sum(amounts, Decimal(0))
        out.append({"key": name, "count": len(amounts),
                    "total": float(total.quantize(CENT, rounding=ROUND_HALF_UP)),
                    "mean": float((total / len(amounts)).quantize(CENT, rounding=ROUND_HALF_UP)),
                    "min": float(min(amounts)), "max": float(max(amounts))})
    return out
'''

README = '''# csv_report

Two modules. Sample data uses the columns `id`, `__KEY__`, `note`, `__VAL__`.

## csvparse.py

- `parse_csv(text)` returns a list of dicts keyed by the header names (names are stripped of
  whitespace). Rules: fields are separated by `,`; a field may be wrapped in `"` and then may contain
  commas, line breaks and `""` (an escaped quote); lines end with `\\n` or `\\r\\n`; completely blank lines
  are skipped; values are kept exactly as written (not stripped); a row with fewer fields than the header
  is padded with `""`; a row with more fields raises `ValueError("row N has too many fields")` (N counts
  data rows from 1); an unterminated quote raises `ValueError`; text with no rows gives `[]`.
- `parse_amount(text)` returns a `float` or `None`. Surrounding whitespace is ignored; blank text is `None`;
  a leading `-` or parentheses mean negative (`(12.50)` is -12.5, `-$5` is -5); an optional `$`; optional
  thousands separators in groups of three (`1,234.50`); an optional fraction needs digits after the dot
  (`.5` is fine, `5.` is not). Anything else (`abc`, `1e3`, `1_000`, `nan`, `1,23`) raises `ValueError`.

## aggregate.py

- `group_stats(rows, key, value)` groups `rows` (dicts) by `row[key].strip()` (an empty key becomes
  `"(none)"`; case-sensitive) and returns a list sorted by key of
  `{"key", "count", "total", "mean", "min", "max"}` over the parsed `row[value]` amounts. Rows whose amount is
  blank are skipped. Money is exact decimal arithmetic: `total` and `mean` are rounded **half up** to 2
  decimals (the mean is computed from the exact total). A missing column or an invalid amount raises
  `ValueError` whose message starts with `row N` (N counts rows from 1).
'''

TESTS = '''import unittest

from aggregate import group_stats
from csvparse import parse_amount, parse_csv


class ReportTests(unittest.TestCase):
    def test_plain_csv(self):
        self.assertEqual(parse_csv("a,b\\n1,2\\n"), [{"a": "1", "b": "2"}])

    def test_quoted_comma(self):
        rows = parse_csv('name,note\\n"Doe, Jane",ok\\n')
        self.assertEqual(rows, [{"name": "Doe, Jane", "note": "ok"}])

    def test_amount_with_currency(self):
        self.assertEqual(parse_amount("$1,234.50"), 1234.5)

    def test_group_stats(self):
        rows = [{"r": "A", "v": "10"}, {"r": "A", "v": "20"}, {"r": "B", "v": "5"}]
        stats = group_stats(rows, "r", "v")
        self.assertEqual([s["key"] for s in stats], ["A", "B"])
        self.assertEqual(stats[0]["mean"], 15.0)


if __name__ == "__main__":
    unittest.main()
'''

CENT = Decimal("0.01")
CATEGORIES = ["North", "South", "East", "West", " North", "South ", "", "Smith, John", 'Acme "Prime" Co', "Line1\nLine2"]
NOTES = ["ok", "late, again", 'said "no"', "two\nlines", "", "  padded  ", "plain text"]


def render_field(rng, text):
    if any(ch in text for ch in ',"\n\r') or rng.random() < 0.15:
        return '"' + text.replace('"', '""') + '"'
    return text


def amount_text(rng, d):
    style = rng.choice(["plain", "money", "paren", "padded"])
    if style == "paren" and d < 0:
        return "(" + format(abs(d), ",.2f") + ")"
    if style == "money":
        return ("-" if d < 0 else "") + "$" + format(abs(d), ",.2f")
    if style == "padded":
        return f" {d} "
    return format(d, "f")


def dataset(rng, key_col, val_col):
    eol = rng.choice(["\n", "\r\n"])
    header = ["id", key_col, "note", val_col]
    expected_rows, lines, amounts = [], [",".join(header)], []
    for i in range(1, rng.randint(9, 15)):
        category, note = rng.choice(CATEGORIES), rng.choice(NOTES)
        d = None if rng.random() < 0.15 else (Decimal(rng.randint(-5000, 90000)) / 100).quantize(CENT)
        text = "" if d is None else amount_text(rng, d)
        fields = [str(i), category, note, text]
        expected_rows.append(dict(zip(header, fields)))
        lines.append(",".join(render_field(rng, f) for f in fields))
        if rng.random() < 0.2:
            lines.append("")
        if d is not None:
            amounts.append((category.strip() or "(none)", d))
    text = eol.join(lines) + (eol if rng.random() < 0.7 else "")
    groups = {}
    for name, d in amounts:
        groups.setdefault(name, []).append(d)
    stats = []
    for name in sorted(groups):
        ds = groups[name]
        total = sum(ds, Decimal(0))
        stats.append({"key": name, "count": len(ds), "total": float(total.quantize(CENT, rounding=ROUND_HALF_UP)),
                      "mean": float((total / len(ds)).quantize(CENT, rounding=ROUND_HALF_UP)),
                      "min": float(min(ds)), "max": float(max(ds))})
    return text, expected_rows, stats


def build(seed):
    rng = rng_for(ID, seed)
    key_col, val_col = rng.choice(["region", "dept", "store"]), rng.choice(["amount", "revenue", "cost"])
    values = dict(KEY=key_col, VAL=val_col)
    files = {"csvparse.py": PARSE_STARTING, "aggregate.py": AGG_STARTING, "README.md": fill(README, **values),
             "tests/test_report.py": TESTS}
    reference = {"csvparse.py": PARSE_REFERENCE, "aggregate.py": AGG_REFERENCE}
    t, r = "target", "regression"
    P, A = "csvparse", "aggregate"
    parse = lambda g, n, text, exp: call_case(g, n, P, f"m.parse_csv({text!r})", exp)
    amount = lambda g, n, text, exp: call_case(g, n, P, f"m.parse_amount({text!r})", exp)
    stats = lambda g, n, rows, exp, k="r", v="v": call_case(g, n, A, f"m.group_stats({rows!r}, {k!r}, {v!r})", exp)
    row = lambda k, v: {"r": k, "v": v}
    c = [
        parse(r, "simple", "a,b\n1,2\n", [{"a": "1", "b": "2"}]),
        parse(r, "crlf", "a,b\r\n1,2\r\n3,4\r\n", [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]),
        parse(r, "no_trailing_newline", "a,b\n1,2", [{"a": "1", "b": "2"}]),
        parse(r, "empty_text", "", []),
        parse(r, "unquoted_spaces_kept", "a,b\n x , y \n", [{"a": " x ", "b": " y "}]),
        parse(t, "quoted_comma_and_quote", 'name,notes\n"Doe, Jane","said ""hi"""\n',
              [{"name": "Doe, Jane", "notes": 'said "hi"'}]),
        parse(t, "multiline_field", 'id,text\n1,"line one\nline two"\n2,plain\n',
              [{"id": "1", "text": "line one\nline two"}, {"id": "2", "text": "plain"}]),
        parse(t, "blank_lines_skipped", "a,b\n\n1,2\n\n\n3,4\n", [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]),
        parse(t, "short_row_padded", "a,b,c\n1,2\n", [{"a": "1", "b": "2", "c": ""}]),
        parse(t, "header_stripped", " a , b \n1,2\n", [{"a": "1", "b": "2"}]),
        parse(t, "whitespace_only_is_empty", "   \n\n", []),
        parse(t, "quoted_empty_field", 'a,b\n"",x\n', [{"a": "", "b": "x"}]),
        raises_case(t, "too_many_fields", P, "m.parse_csv('a,b\\n1,2,3\\n')", "ValueError"),
        raises_case(t, "unterminated_quote", P, "m.parse_csv('a,b\\n\"1,2\\n')", "ValueError"),
        amount(r, "plain", "12.5", 12.5),
        amount(r, "padded", " 7 ", 7),
        amount(r, "leading_dot", ".5", 0.5),
        amount(t, "currency_and_thousands", "$1,234.50", 1234.5),
        amount(t, "parentheses_negative", "(12.50)", -12.5),
        amount(t, "minus_dollar", "-$5", -5),
        amount(t, "blank_is_none", "", None),
        amount(t, "spaces_is_none", "   ", None),
        amount(t, "thousands_only", "1,234", 1234),
        raises_case(t, "trailing_dot", P, "m.parse_amount('5.')", "ValueError"),
        raises_case(t, "underscore_digits", P, "m.parse_amount('1_000')", "ValueError"),
        raises_case(t, "scientific", P, "m.parse_amount('1e3')", "ValueError"),
        raises_case(t, "nan", P, "m.parse_amount('nan')", "ValueError"),
        raises_case(r, "text", P, "m.parse_amount('abc')", "ValueError"),
        raises_case(r, "bad_grouping", P, "m.parse_amount('1,23')", "ValueError"),
        stats(r, "basic", [row("A", "10"), row("A", "20"), row("B", "5")],
              [{"key": "A", "count": 2, "total": 30, "mean": 15, "min": 10, "max": 20},
               {"key": "B", "count": 1, "total": 5, "mean": 5, "min": 5, "max": 5}]),
        stats(r, "sorted_case_sensitive", [row("b", "1"), row("A", "1"), row("a", "1")],
              [{"key": k, "count": 1, "total": 1, "mean": 1, "min": 1, "max": 1} for k in ("A", "a", "b")]),
        stats(r, "no_rows", [], []),
        stats(t, "mean_rounds_half_up", [row("A", "2.50"), row("A", "2.51")],
              [{"key": "A", "count": 2, "total": 5.01, "mean": 2.51, "min": 2.5, "max": 2.51}]),
        stats(t, "key_is_stripped", [row(" A ", "1"), row("A", "2")],
              [{"key": "A", "count": 2, "total": 3, "mean": 1.5, "min": 1, "max": 2}]),
        stats(t, "empty_key_group", [row("", "4"), row("  ", "6")],
              [{"key": "(none)", "count": 2, "total": 10, "mean": 5, "min": 4, "max": 6}]),
        stats(t, "blank_amounts_skipped", [row("A", ""), row("A", "3"), row("B", " ")],
              [{"key": "A", "count": 1, "total": 3, "mean": 3, "min": 3, "max": 3}]),
        stats(t, "money_formats", [row("A", "$1,000.00"), row("A", "(250.00)"), row("A", "1,000")],
              [{"key": "A", "count": 3, "total": 1750, "mean": 583.33, "min": -250, "max": 1000}]),
    ]
    c.append(call_case(t, "bad_amount_names_the_row", A, "_probe([{'r': 'A', 'v': '1'}, {'r': 'A', 'v': 'x'}])", True,
                       setup="def _probe(rows):\n    import aggregate\n    try:\n        aggregate.group_stats(rows, 'r', 'v')\n"
                             "    except ValueError as e:\n        return str(e).startswith('row 2')\n    return False\n"))
    c.append(raises_case(t, "unknown_column", A, "m.group_stats([{'r': 'A'}], 'r', 'v')", "ValueError"))
    for i in range(3):
        text, rows, expected_stats = dataset(rng, key_col, val_col)
        c.append(parse("auto", f"generated_parse_{i}", text, rows))
        c.append(call_case("auto", f"generated_report_{i}", A,
                           f"m.group_stats(csvparse.parse_csv({text!r}), {key_col!r}, {val_col!r})",
                           expected_stats, setup="import csvparse"))
    intro = ("Task: the CSV report in `csvparse.py` and `aggregate.py` is broken (quoted fields, blank lines, "
             "amount formats, grouping and rounding). Fix both modules so they follow README.md.")
    return finalize(ID, DIFFICULTY, "Fix the CSV report", intro, files, c, reference, seed)
