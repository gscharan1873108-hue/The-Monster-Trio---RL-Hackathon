"""Hard: replace an eval()-based calculator with a safe, exact expression evaluator."""
from .base import call_case, finalize, fill, raises_case, rng_for

ID, DIFFICULTY = "calc", "hard"

STARTING = '''MAX_EXPONENT = __MAXEXP__
MAX_LENGTH = 1000


def evaluate(expr):
    return eval(expr)
'''

REFERENCE = '''import math
import re

MAX_EXPONENT = __MAXEXP__
MAX_LENGTH = 1000
MAX_DEPTH = 100

_TOKEN = re.compile(r"\\s*(?:([0-9]+\\.[0-9]+|\\.[0-9]+|[0-9]+)|(\\*\\*|//|[-+*/%()]))")


def _tokenize(expr):
    tokens, pos, text = [], 0, expr.rstrip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise ValueError(f"unexpected character at position {pos}")
        number, op = match.groups()
        if number is not None:
            value = int(number) if number.isdigit() else float(number)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("number too large")
            tokens.append(value)
        else:
            tokens.append(op)
        pos = match.end()
    return tokens


def _power(base, exponent):
    if abs(exponent) > MAX_EXPONENT:
        raise ValueError("exponent too large")
    if base == 0 and exponent < 0:
        raise ValueError("division by zero")
    try:
        result = base ** exponent
    except OverflowError:
        raise ValueError("result too large") from None
    if isinstance(result, complex):
        raise ValueError("result is not a real number")
    return result


class _Parser:
    def __init__(self, tokens):
        self.tokens, self.i, self.depth = tokens, 0, 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.i += 1
        return token

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ValueError("expression nested too deeply")

    def parse(self):
        value = self.expr()
        if self.peek() is not None:
            raise ValueError(f"unexpected token {self.peek()!r}")
        return value

    def expr(self):
        value = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            rhs = self.term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def term(self):
        value = self.unary()
        while self.peek() in ("*", "/", "//", "%"):
            op = self.take()
            rhs = self.unary()
            if op == "*":
                value = value * rhs
            elif rhs == 0:
                raise ValueError("division by zero")
            elif op == "/":
                value = value / rhs
            elif op == "//":
                value = value // rhs
            else:
                value = value % rhs
        return value

    def unary(self):
        token = self.peek()
        if token in ("+", "-"):
            self.take()
            self.enter()
            value = self.unary()
            self.depth -= 1
            return -value if token == "-" else value
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() == "**":
            self.take()
            return _power(base, self.unary())
        return base

    def atom(self):
        token = self.take()
        if token is None:
            raise ValueError("unexpected end of expression")
        if isinstance(token, (int, float)):
            return token
        if token == "(":
            self.enter()
            value = self.expr()
            self.depth -= 1
            if self.take() != ")":
                raise ValueError("missing closing parenthesis")
            return value
        raise ValueError(f"unexpected token {token!r}")


def evaluate(expr):
    if not isinstance(expr, str):
        raise ValueError("expression must be a string")
    if len(expr) > MAX_LENGTH:
        raise ValueError("expression too long")
    tokens = _tokenize(expr)
    if not tokens:
        raise ValueError("empty expression")
    try:
        result = _Parser(tokens).parse()
    except (OverflowError, ZeroDivisionError, RecursionError) as exc:
        raise ValueError(f"cannot evaluate: {type(exc).__name__}") from None
    if isinstance(result, float) and not math.isfinite(result):
        raise ValueError("result is not finite")
    return result
'''

README = '''# calc

`evaluate(expr)` in `calc.py` evaluates an arithmetic expression string and returns an `int` or `float`.
It must never run arbitrary code: no names, calls, attributes, strings or other Python syntax.

Grammar (lowest to highest precedence):

- `+` `-` (left to right)
- `*` `/` `//` `%` (left to right; `/` is true division, `//` floors, `%` follows Python's sign rules)
- unary `+` `-`
- `**` (right to left, like Python: `-2 ** 2` is -4, `2 ** 3 ** 2` is 512, `2 ** -1` is 0.5)
- numbers and parenthesised expressions. A number is digits with an optional fraction: `7`, `007`, `3.25`,
  `.5`. Forms such as `5.`, `1e3`, `1_000` and `0x10` are invalid.

Results stay `int` where Python's would (`+ - * // % **` on ints with a non-negative exponent).

Everything invalid raises `ValueError` (and nothing else): empty or non-string input, unknown characters or
tokens, adjacent numbers (`2 3`), unbalanced parentheses, division / modulo / floor-division by zero, `0 **`
a negative power, a negative base raised to a fractional power (complex result), an exponent whose absolute
value is above `MAX_EXPONENT` (= __MAXEXP__), an expression longer than `MAX_LENGTH` characters, nesting deeper
than 100 levels, numbers or results that overflow to infinity or NaN. Whitespace between tokens is ignored.
'''

TESTS = '''import unittest

from calc import evaluate


class CalcTests(unittest.TestCase):
    def test_precedence(self):
        self.assertEqual(evaluate("1 + 2 * 3"), 7)

    def test_parentheses(self):
        self.assertEqual(evaluate("(1 + 2) * 3"), 9)

    def test_true_division(self):
        self.assertEqual(evaluate("10 / 4"), 2.5)

    def test_unary_and_power(self):
        self.assertEqual(evaluate("-2 ** 2"), -4)

    def test_rejects_code(self):
        with self.assertRaises(ValueError):
            evaluate("__import__('os').getcwd()")

    def test_division_by_zero_is_value_error(self):
        with self.assertRaises(ValueError):
            evaluate("1 / 0")


if __name__ == "__main__":
    unittest.main()
'''


def render(rng, node):
    """node: ('n', int) | ('u', op, node) | ('b', op, left, right) | ('p', node); returns text."""
    kind = node[0]
    sp = lambda: rng.choice(["", " ", "  "])
    if kind == "n":
        return str(node[1])
    if kind == "u":
        return node[1] + sp() + render(rng, node[2])
    if kind == "p":
        return "(" + sp() + render(rng, node[1]) + sp() + ")"
    return render(rng, node[2]) + sp() + node[1] + sp() + render(rng, node[3])


def random_node(rng, depth):
    if depth == 0 or rng.random() < 0.25:
        return ("n", rng.randint(0, 20))
    roll = rng.random()
    if roll < 0.15:
        return ("u", rng.choice(["-", "+"]), random_node(rng, depth - 1))
    if roll < 0.3:
        return ("p", random_node(rng, depth - 1))
    op = rng.choice(["+", "-", "*", "/", "//", "%", "**", "+", "-", "*"])
    left = random_node(rng, depth - 1)
    right = ("n", rng.randint(0, 3)) if op == "**" else random_node(rng, depth - 1)
    return ("b", op, left, right)


def random_expression(rng):
    """A valid expression and its Python-computed value (skips division by zero and huge/complex results)."""
    while True:
        text = render(rng, random_node(rng, rng.randint(2, 5)))
        try:
            value = eval(text, {"__builtins__": {}}, {})       # trusted: generated here from digits and operators
        except (ZeroDivisionError, OverflowError):
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < 10 ** 40:
            return text, value


def build(seed):
    rng = rng_for(ID, seed)
    max_exp = rng.choice([16, 32, 64])
    values = dict(MAXEXP=max_exp)
    files = {"calc.py": fill(STARTING, **values), "README.md": fill(README, **values), "tests/test_calc.py": TESTS}
    reference = {"calc.py": fill(REFERENCE, **values)}
    t, r, M = "target", "regression", "calc"
    ev = lambda g, n, text, exp: call_case(g, n, M, f"m.evaluate({text!r})", exp)
    bad = lambda g, n, text: raises_case(g, n, M, f"m.evaluate({text!r})", "ValueError")
    c = [
        ev(r, "precedence", "1 + 2 * 3", 7),
        ev(r, "parentheses", "(1 + 2) * 3", 9),
        ev(r, "true_division", "10 / 4", 2.5),
        ev(r, "unary_minus_binds_looser_than_power", "-2 ** 2", -4),
        ev(r, "power_is_right_associative", "2 ** 3 ** 2", 512),
        ev(r, "negative_exponent", "2 ** -1", 0.5),
        ev(r, "floor_division_negative", "-7 // 2", -4),
        ev(r, "modulo_sign_follows_divisor", "-7 % 3", 2),
        ev(r, "float_literals", ".5 + 1.25", 1.75),
        ev(r, "double_unary", "--3", 3),
        ev(r, "whitespace_ignored", "  4*(  2+3 ) ", 20),
        ev(t, "leading_zeros_allowed", "007 + 1", 8),
        ev("auto", "int_result_stays_int_exact", f"3 ** {max_exp}", 3 ** max_exp),
        ev("auto", "max_exponent_allowed", f"2 ** {max_exp}", 2 ** max_exp),
        ev("auto", "negative_max_exponent_allowed", f"1 ** -{max_exp}", 1.0),
        bad(t, "code_injection", "__import__('os').getcwd()"),
        bad(t, "attribute_access", "().__class__"),
        bad(t, "names", "abc + 1"),
        bad(t, "strings", "'a' * 3"),
        bad(t, "conditional_expression", "1 if 1 else 2"),
        bad(t, "list_literal", "[1, 2]"),
        bad(t, "keyword_constants", "True + 1"),
        bad(t, "division_by_zero", "1 / 0"),
        bad(t, "floor_division_by_zero", "5 // 0"),
        bad(t, "modulo_by_zero", "5 % 0"),
        bad(t, "zero_to_negative_power", "0 ** -1"),
        bad(t, "complex_result", "(-8) ** (1 / 3)"),
        bad(t, "exponent_over_limit", f"2 ** {max_exp + 1}"),
        bad(t, "negative_exponent_over_limit", f"2 ** -{max_exp + 1}"),
        bad(t, "scientific_notation", "1e3"),
        bad(t, "trailing_dot", "5."),
        bad(t, "digit_underscore", "1_000"),
        bad(t, "hex_literal", "0x10"),
        bad(t, "adjacent_numbers", "2 3"),
        bad(t, "unclosed_paren", "(1 + 2"),
        bad(t, "extra_close_paren", "1 + 2)"),
        bad(t, "empty", ""),
        bad(t, "blank", "   "),
        bad(t, "dangling_operator", "1 +"),
        bad(t, "leading_binary_operator", "* 2"),
        bad(t, "too_long", "1+" * 600 + "1"),
        bad(t, "nested_too_deep", "(" * 150 + "1" + ")" * 150),
        bad(t, "overflow_literal", "9" * 400 + ".0"),
        bad(t, "float_overflow", "1.5 * " + "9" * 300 + ".0 * " + "9" * 300 + ".0"),
        raises_case(t, "non_string_input", M, "m.evaluate(42)", "ValueError"),
    ]
    for i in range(14):
        text, value = random_expression(rng)
        c.append(ev("auto", f"generated_{i}", text, value))
    intro = ("Task: `calc.py` evaluates expressions with Python's `eval`, which is unsafe and does not follow "
             "the spec. Rewrite `evaluate` as a proper parser that follows README.md, raising `ValueError` "
             "(and only that) for every invalid or unsafe input.")
    return finalize(ID, DIFFICULTY, "Write a safe expression evaluator", intro, files, c, reference, seed)
