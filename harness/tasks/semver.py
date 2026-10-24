"""Hard: implement semantic-version parsing, precedence and range matching."""
from .base import call_case, finalize, fill, raises_case, rng_for

ID, DIFFICULTY = "semver", "hard"

STARTING = '''from functools import cmp_to_key


def parse(version):
    major, minor, patch = (int(part) for part in version.split("."))
    return {"major": major, "minor": minor, "patch": patch, "prerelease": [], "build": []}


def _key(version):
    parsed = parse(version)
    return (parsed["major"], parsed["minor"], parsed["patch"])


def compare(a, b):
    ka, kb = _key(a), _key(b)
    return (ka > kb) - (ka < kb)


def satisfies(version, constraint):
    for token in constraint.split():
        for op in (">=", "<=", ">", "<", "="):
            if token.startswith(op):
                other, wanted = token[len(op):], op
                break
        else:
            other, wanted = token, "="
        result = compare(version, other)
        ok = {">=": result >= 0, "<=": result <= 0, ">": result > 0, "<": result < 0, "=": result == 0}[wanted]
        if not ok:
            return False
    return True


def max_satisfying(versions, constraint):
    best = None
    for candidate in versions:
        if satisfies(candidate, constraint) and (best is None or compare(candidate, best) > 0):
            best = candidate
    return best


def sort_versions(versions, reverse=False):
    return sorted(versions, key=cmp_to_key(compare), reverse=reverse)
'''

REFERENCE = '''import re
from functools import cmp_to_key

_VERSION = re.compile(r"(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\\+([0-9A-Za-z.-]+))?")
_IDENT = re.compile(r"[0-9A-Za-z-]+")
_NUM = re.compile(r"0|[1-9][0-9]*")
_OP = re.compile(r"(>=|<=|>|<|=|\\^|~)?(.*)", re.S)


def _idents(text, what):
    out = []
    for part in text.split("."):
        if not _IDENT.fullmatch(part):
            raise ValueError(f"invalid {what} identifier {part!r}")
        out.append(part)
    return out


def _mk(major, minor, patch, pre=()):
    return {"major": major, "minor": minor, "patch": patch, "prerelease": list(pre), "build": []}


def parse(version):
    if not isinstance(version, str):
        raise ValueError("version must be a string")
    match = _VERSION.fullmatch(version)
    if not match:
        raise ValueError(f"invalid version: {version!r}")
    pre = []
    if match.group(4) is not None:
        for part in _idents(match.group(4), "prerelease"):
            if part.isdigit():
                if len(part) > 1 and part[0] == "0":
                    raise ValueError("numeric prerelease identifier has a leading zero")
                part = int(part)
            pre.append(part)
    build = _idents(match.group(5), "build") if match.group(5) is not None else []
    return {"major": int(match.group(1)), "minor": int(match.group(2)), "patch": int(match.group(3)),
            "prerelease": pre, "build": build}


def _nums(v):
    return (v["major"], v["minor"], v["patch"])


def _cmp_ident(a, b):
    a_num, b_num = isinstance(a, int), isinstance(b, int)
    if a_num and b_num:
        return (a > b) - (a < b)
    if a_num:
        return -1
    if b_num:
        return 1
    return (a > b) - (a < b)


def _compare_parsed(x, y):
    if _nums(x) != _nums(y):
        return -1 if _nums(x) < _nums(y) else 1
    xp, yp = x["prerelease"], y["prerelease"]
    if not xp and not yp:
        return 0
    if not xp:
        return 1
    if not yp:
        return -1
    for a, b in zip(xp, yp):
        result = _cmp_ident(a, b)
        if result:
            return result
    return (len(xp) > len(yp)) - (len(xp) < len(yp))


def compare(a, b):
    return _compare_parsed(parse(a), parse(b))


def _partial(token):
    core, dash, pre = token.split("+", 1)[0].partition("-")
    parts = core.split(".")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"invalid version in constraint: {token!r}")
    nums, wild = [], False
    for part in parts:
        if part in ("x", "X", "*"):
            wild = True
            nums.append(None)
        elif wild or not _NUM.fullmatch(part):
            raise ValueError(f"invalid version in constraint: {token!r}")
        else:
            nums.append(int(part))
    nums += [None] * (3 - len(nums))
    if dash:
        if None in nums:
            raise ValueError("a prerelease needs a full version")
        return nums, parse(f"{nums[0]}.{nums[1]}.{nums[2]}-{pre}")["prerelease"]
    return nums, []


def _expand(op, token):
    (major, minor, patch), pre = _partial(token)
    if op in (">=", ">", "<=", "<", "="):
        if None in (major, minor, patch):
            raise ValueError(f"operator {op} needs a full version")
        return [(op, _mk(major, minor, patch, pre))]
    if major is None:
        return []
    if op == "":
        if patch is not None:
            return [("=", _mk(major, minor, patch, pre))]
        if minor is not None:
            return [(">=", _mk(major, minor, 0)), ("<", _mk(major, minor + 1, 0))]
        return [(">=", _mk(major, 0, 0)), ("<", _mk(major + 1, 0, 0))]
    low = _mk(major, minor or 0, patch or 0, pre)
    if op == "~":
        high = _mk(major + 1, 0, 0) if minor is None else _mk(major, minor + 1, 0)
    elif major > 0 or minor is None:
        high = _mk(major + 1, 0, 0)
    elif minor > 0 or patch is None:
        high = _mk(0, minor + 1, 0)
    else:
        high = _mk(0, 0, patch + 1)
    return [(">=", low), ("<", high)]


def _parse_set(text):
    text = re.sub(r"(>=|<=|>|<|=|\\^|~)\\s+", r"\\1", text.strip())
    comparators = []
    for token in text.split():
        match = _OP.fullmatch(token)
        comparators.extend(_expand(match.group(1) or "", match.group(2)))
    return comparators


def _compile(constraint):
    if not isinstance(constraint, str):
        raise ValueError("constraint must be a string")
    return [_parse_set(part) for part in constraint.split("||")]


def _match(v, comparators):
    for op, other in comparators:
        r = _compare_parsed(v, other)
        if not {">=": r >= 0, ">": r > 0, "<=": r <= 0, "<": r < 0, "=": r == 0}[op]:
            return False
    if v["prerelease"]:
        return any(c["prerelease"] and _nums(c) == _nums(v) for _op, c in comparators)
    return True


def satisfies(version, constraint):
    v = parse(version)
    return any(_match(v, comparators) for comparators in _compile(constraint))


def max_satisfying(versions, constraint):
    sets = _compile(constraint)
    best, best_parsed = None, None
    for raw in versions:
        v = parse(raw)
        if any(_match(v, comparators) for comparators in sets) and (best is None or _compare_parsed(v, best_parsed) > 0):
            best, best_parsed = raw, v
    return best


def sort_versions(versions, reverse=False):
    pairs = [(parse(v), v) for v in versions]
    pairs.sort(key=cmp_to_key(lambda a, b: _compare_parsed(a[0], b[0])), reverse=reverse)
    return [raw for _parsed, raw in pairs]
'''

README = '''# semver

`semver.py` implements Semantic Versioning 2.0.0 precedence and npm-style ranges (stdlib only).
This project pins the sample versions below to the `__SERIES__` series.

- `parse(version)` -> `{"major", "minor", "patch", "prerelease", "build"}` (ints, a list, a list).
  The version must be exactly `MAJOR.MINOR.PATCH[-prerelease][+build]`: no leading `v`, no spaces, no
  leading zeros in numbers. Prerelease/build are dot-separated non-empty identifiers of `[0-9A-Za-z-]`;
  numeric prerelease identifiers (no leading zeros) are returned as ints, all others as strings; `build`
  is a list of strings. Any invalid input (including a non-string) raises `ValueError`.
- `compare(a, b)` -> -1, 0 or 1 using semver precedence: compare major, minor, patch numerically; a version
  with a prerelease is LOWER than the same version without one; prereleases compare identifier by
  identifier (numeric identifiers numerically, numeric < alphanumeric, alphanumeric in ASCII order, and a
  shorter list is lower when all earlier identifiers are equal). Build metadata is ignored.
- `sort_versions(versions, reverse=False)` returns the original strings sorted by precedence (stable).
- `satisfies(version, constraint)` -> bool. A constraint is one or more comparator sets joined by `||`
  (any set may match). A set is space-separated comparators that must all match; an empty set matches
  everything. Whitespace between an operator and its version is allowed (`>= 1.2.3`).
  - Operators `>=  >  <=  <  =` need a FULL version (`1.2.3` or `1.2.3-beta.1`), else `ValueError`.
  - A bare full version means `=`.
  - `^`, `~` and bare partial versions accept `1`, `1.2`, `1.x`, `1.2.x`, `*`, `x`:
    `^1.2.3` = `>=1.2.3 <2.0.0`; `^0.2.3` = `>=0.2.3 <0.3.0`; `^0.0.3` = `>=0.0.3 <0.0.4`;
    `^1.2` = `>=1.2.0 <2.0.0`; `^0.0` = `>=0.0.0 <0.1.0`; `^0` = `>=0.0.0 <1.0.0`;
    `~1.2.3` = `>=1.2.3 <1.3.0`; `~1.2` = `>=1.2.0 <1.3.0`; `~1` = `>=1.0.0 <2.0.0`;
    bare `1.2.x` or `1.2` = `>=1.2.0 <1.3.0`; bare `1.x` or `1` = `>=1.0.0 <2.0.0`; `*` = anything.
  - A prerelease on a partial version or after a wildcard is invalid.
  - A candidate WITH a prerelease only satisfies a comparator set if some comparator in that set carries a
    prerelease on the same `major.minor.patch`; otherwise it never matches (so `1.2.4-alpha` does not
    satisfy `^1.2.3`, but `1.2.3-beta.2` satisfies `^1.2.3-beta.1`).
  - Malformed constraints raise `ValueError`, even when another `||` set would have matched.
- `max_satisfying(versions, constraint)` returns the original string of the highest satisfying version, the
  first one on equal precedence, or `None`.
'''

TESTS = '''import unittest

from semver import compare, max_satisfying, parse, satisfies, sort_versions


class SemverTests(unittest.TestCase):
    def test_parse_basic(self):
        self.assertEqual(parse("1.2.3")["minor"], 2)

    def test_numeric_not_lexicographic(self):
        self.assertEqual(compare("1.10.0", "1.9.0"), 1)

    def test_prerelease_is_lower(self):
        self.assertEqual(compare("1.0.0-alpha", "1.0.0"), -1)

    def test_caret_range(self):
        self.assertTrue(satisfies("1.4.2", "^1.2.3"))
        self.assertFalse(satisfies("2.0.0", "^1.2.3"))

    def test_sort_and_max(self):
        self.assertEqual(sort_versions(["1.10.0", "1.2.0"]), ["1.2.0", "1.10.0"])
        self.assertEqual(max_satisfying(["1.0.0", "1.5.0", "2.0.0"], "<2.0.0"), "1.5.0")


if __name__ == "__main__":
    unittest.main()
'''

PRE_ORDER = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
             "1.0.0-rc.1", "1.0.0"]

SAT = [  # (version, constraint, expected)
    ("1.2.3", "^1.0.0", True), ("2.0.0", "^1.0.0", False), ("0.2.5", "^0.2.3", True), ("0.3.0", "^0.2.3", False),
    ("0.0.3", "^0.0.3", True), ("0.0.4", "^0.0.3", False), ("1.2.9", "~1.2.3", True), ("1.3.0", "~1.2.3", False),
    ("1.9.9", "1.x", True), ("2.0.0", "1.x", False), ("1.2.5", "1.2", True), ("1.3.0", "1.2", False),
    ("3.1.4", "*", True), ("1.2.3-beta.2", "^1.2.3-beta.1", True), ("1.3.0-beta", "^1.2.3-beta.1", False),
    ("1.2.4-alpha", "^1.2.3", False), ("1.0.0-alpha", "*", False), ("2.0.0", "1.2.3 || 2.0.0", True),
    ("1.5.0", ">= 1.2.3 < 2.0.0", True), ("2.0.0", ">=1.2.3 <2.0.0", False), ("1.2.3+build.7", "1.2.3", True),
    ("0.5.0", "^0", True), ("1.0.0", "^0", False), ("0.0.9", "^0.0", True), ("0.1.0", "^0.0", False),
    ("1.4.0", "~1", True), ("2.0.0", "~1", False), ("1.2.3", ">1.2.3", False), ("1.2.4", ">1.2.3 <=1.2.4", True),
]
BAD_CONSTRAINTS = [">=1.2", "^1.2.3.4", ">=a.b.c", "^", "1.x.3", "^1.2-beta", "~1.2.3 || nonsense", "<1.x", ">=01.2.3"]
BAD_VERSIONS = ["1.2", "01.2.3", "1.2.3-", "1.2.3-01", "v1.2.3", " 1.2.3", "1.2.3\n", "1.2.3-a..b", "1.2.3+"]


def rand_version(rng, series):
    v = f"{series}.{rng.randint(0, 6)}.{rng.randint(0, 9)}" if series is not None else \
        f"{rng.randint(0, 2)}.{rng.randint(0, 6)}.{rng.randint(0, 9)}"
    if rng.random() < 0.3:
        v += "-" + rng.choice(["alpha", "beta.1", "beta.2", "rc.1", "alpha.1", "1", "x-y"])
    if rng.random() < 0.15:
        v += "+" + rng.choice(["b1", "build.5"])
    return v


def rand_constraint(rng):
    def one(fancy=False):
        major, minor, patch = rng.randint(0, 2), rng.randint(0, 5), rng.randint(0, 8)
        kind = rng.choice(["^", "~", "bare", "x"] if fancy else ["^", "~", ">=", "<", ">", "<=", "=", "bare", "x"])
        if kind in ("^", "~"):
            return kind + rng.choice([f"{major}", f"{major}.{minor}", f"{major}.{minor}.{patch}"])
        if kind in (">=", "<", ">", "<=", "="):
            return kind + f"{major}.{minor}.{patch}"
        if kind == "x":
            return rng.choice([f"{major}.x", f"{major}.{minor}.x", "*"])
        return rng.choice([f"{major}.{minor}.{patch}", f"{major}.{minor}", f"{major}"])
    sets = []
    for index in range(rng.randint(1, 2)):
        parts = [one(fancy=(index == 0))] + [one() for _ in range(rng.randint(0, 1))]
        sets.append(" ".join(parts))
    return " || ".join(sets)


def build(seed):
    rng = rng_for(ID, seed)
    series = rng.choice([1, 2, 3])
    values = dict(SERIES=f"{series}.x")
    files = {"semver.py": STARTING, "README.md": fill(README, **values), "tests/test_semver.py": TESTS}
    reference = {"semver.py": REFERENCE}
    t, r, M = "target", "regression", "semver"
    c = [
        call_case(r, "parse_basic", M, "m.parse('1.2.3')",
                  {"major": 1, "minor": 2, "patch": 3, "prerelease": [], "build": []}),
        call_case(r, "compare_numeric_not_lexicographic", M, "m.compare('1.10.0', '1.9.0')", 1),
        call_case(r, "compare_equal", M, "m.compare('2.0.1', '2.0.1')", 0),
        call_case(r, "sort_plain", M, "m.sort_versions(['1.10.0', '1.2.0', '1.9.5', '0.9.9'])",
                  ["0.9.9", "1.2.0", "1.9.5", "1.10.0"]),
        call_case(r, "sort_plain_reverse", M, "m.sort_versions(['1.0.0', '1.2.0', '1.1.0'], reverse=True)",
                  ["1.2.0", "1.1.0", "1.0.0"]),
        call_case(r, "satisfies_simple_range", M, "m.satisfies('1.5.0', '>=1.2.0 <2.0.0')", True),
        call_case(r, "satisfies_simple_range_false", M, "m.satisfies('2.5.0', '>=1.2.0 <2.0.0')", False),
        call_case(r, "max_simple", M, "m.max_satisfying(['1.0.0', '1.5.0', '2.0.0'], '<2.0.0')", "1.5.0"),
        call_case(t, "parse_prerelease_and_build", M, "m.parse('1.2.3-alpha.1+exp.sha')",
                  {"major": 1, "minor": 2, "patch": 3, "prerelease": ["alpha", 1], "build": ["exp", "sha"]}),
        call_case(t, "prerelease_lower_than_release", M, "m.compare('1.0.0-alpha', '1.0.0')", -1),
        call_case(t, "prerelease_numeric_vs_alpha", M, "m.compare('1.0.0-alpha.1', '1.0.0-alpha.beta')", -1),
        call_case(t, "prerelease_numeric_order", M, "m.compare('1.0.0-beta.11', '1.0.0-beta.2')", 1),
        call_case(t, "prerelease_shorter_is_lower", M, "m.compare('1.0.0-alpha', '1.0.0-alpha.1')", -1),
        call_case(t, "build_ignored", M, "m.compare('1.0.0+a', '1.0.0+b')", 0),
        call_case(t, "semver_org_chain_sorted", M, "m.sort_versions(%r)" % [PRE_ORDER[i] for i in (5, 0, 7, 3, 1, 6, 4, 2)],
                  PRE_ORDER),
        call_case(t, "sort_stable_for_equal_precedence", M, "m.sort_versions(['1.0.0+b', '1.0.0+a', '0.9.0'])",
                  ["0.9.0", "1.0.0+b", "1.0.0+a"]),
        call_case(t, "max_skips_prerelease", M, "m.max_satisfying(['1.2.3', '1.3.0-beta', '1.2.9'], '^1.2.3')", "1.2.9"),
        call_case(t, "max_none_when_unsatisfied", M, "m.max_satisfying(['0.1.0', '0.2.0'], '^1.0.0')", None),
        call_case(t, "max_first_on_equal_precedence", M, "m.max_satisfying(['1.0.0+b', '1.0.0+a'], '1.x')", "1.0.0+b"),
    ]
    for i, (v, con, expected) in enumerate(SAT):
        c.append(call_case("auto", f"satisfies_{i}", M, f"m.satisfies({v!r}, {con!r})", expected))
    for i, bad in enumerate(BAD_CONSTRAINTS):
        c.append(raises_case("auto", f"bad_constraint_{i}", M, f"m.satisfies('1.2.3', {bad!r})", "ValueError"))
    for i, bad in enumerate(BAD_VERSIONS):
        c.append(raises_case("auto", f"bad_version_{i}", M, f"m.parse({bad!r})", "ValueError"))
    c.append(raises_case(t, "non_string_version", M, "m.parse(123)", "ValueError"))
    for i in range(5):
        versions = [rand_version(rng, series if rng.random() < 0.7 else None) for _ in range(rng.randint(6, 10))]
        c.append(call_case("auto", f"generated_sort_{i}", M, f"m.sort_versions({versions!r})"))
    for i in range(7):
        versions = [rand_version(rng, rng.choice([0, 1, 2])) for _ in range(rng.randint(5, 9))]
        constraint = rand_constraint(rng)
        c.append(call_case("auto", f"generated_satisfies_{i}", M,
                           f"[m.satisfies(v, {constraint!r}) for v in {versions!r}]"))
        c.append(call_case("auto", f"generated_max_{i}", M, f"m.max_satisfying({versions!r}, {constraint!r})"))
    intro = ("Task: `semver.py` only understands plain `X.Y.Z` versions. Implement proper Semantic Versioning "
             "precedence (prereleases, build metadata, validation) and npm-style range matching exactly as "
             "described in README.md.")
    return finalize(ID, DIFFICULTY, "Implement semver ranges", intro, files, c, reference, seed)
