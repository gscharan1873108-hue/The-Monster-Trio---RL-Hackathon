"""Easy: fix order pricing (tier boundaries, half-up rounding, free-shipping rule, validation)."""
from .base import call_case, finalize, fill, raises_case, rng_for

ID, DIFFICULTY = "pricing", "easy"

HEADER = '''TIERS = [(__T1__, __R1__), (__T2__, __R2__)]   # (minimum quantity, percent off the whole line)
SHIPPING_FEE = __FEE__                           # cents
FREE_SHIPPING_AT = __FREE__                      # cents
'''

STARTING = HEADER + '''

def discount_percent(qty):
    pct = 0
    for min_qty, percent in TIERS:
        if qty > min_qty:
            pct = percent
    return pct


def line_total(unit_cents, qty):
    return round(unit_cents * qty * (100 - discount_percent(qty)) / 100)


def order_total(lines):
    gross = sum(unit * qty for unit, qty in lines)
    subtotal = sum(line_total(unit, qty) for unit, qty in lines)
    shipping = 0 if gross >= FREE_SHIPPING_AT else SHIPPING_FEE
    return {"subtotal": subtotal, "shipping": shipping, "total": subtotal + shipping}
'''

REFERENCE = HEADER + '''

def _check(unit_cents, qty):
    for value in (unit_cents, qty):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("unit_cents and qty must be ints")
    if unit_cents < 0 or qty < 1:
        raise ValueError("unit_cents must be >= 0 and qty >= 1")


def discount_percent(qty):
    pct = 0
    for min_qty, percent in TIERS:
        if qty >= min_qty:
            pct = percent
    return pct


def line_total(unit_cents, qty):
    _check(unit_cents, qty)
    return (unit_cents * qty * (100 - discount_percent(qty)) + 50) // 100


def order_total(lines):
    subtotal = sum(line_total(unit, qty) for unit, qty in lines)
    shipping = 0 if (not lines or subtotal >= FREE_SHIPPING_AT) else SHIPPING_FEE
    return {"subtotal": subtotal, "shipping": shipping, "total": subtotal + shipping}
'''

README = '''# pricing

All money is an integer number of cents. Public API in `pricing.py`:

- `discount_percent(qty)`: percent off for a quantity. Tiers (`TIERS`) are `(min_qty, percent)`:
  __TIERS_TEXT__. The highest tier whose `min_qty` is **at or below** `qty` applies.
- `line_total(unit_cents, qty)`: `unit_cents * qty` reduced by `discount_percent(qty)`, rounded
  **half up** to a whole cent (2.5 -> 3, never banker's rounding). `qty` must be an int >= 1 and
  `unit_cents` an int >= 0, otherwise raise `ValueError` (bools are not ints here).
- `order_total(lines)`: `lines` is a list of `(unit_cents, qty)`. Returns
  `{"subtotal": ..., "shipping": ..., "total": ...}` where `subtotal` is the sum of the (already
  discounted) line totals. Shipping is `SHIPPING_FEE` = __FEE__ unless `subtotal >= FREE_SHIPPING_AT`
  (= __FREE__), judged on the discounted subtotal. An empty order costs nothing: all three are 0.
'''

TESTS = '''import unittest

from pricing import TIERS, discount_percent, line_total, order_total


class PricingTests(unittest.TestCase):
    def test_no_discount_below_first_tier(self):
        self.assertEqual(discount_percent(1), 0)

    def test_first_tier_applies_at_its_minimum(self):
        min_qty, percent = TIERS[0]
        self.assertEqual(discount_percent(min_qty), percent)

    def test_line_total_without_discount(self):
        self.assertEqual(line_total(250, 2), 500)

    def test_order_with_shipping(self):
        result = order_total([(1000, 2)])
        self.assertEqual(result["subtotal"], 2000)
        self.assertEqual(result["total"], 2000 + result["shipping"])


if __name__ == "__main__":
    unittest.main()
'''


def half_up(n):
    return (n + 50) // 100


def build(seed):
    rng = rng_for(ID, seed)
    t1 = rng.choice([5, 10, 12])
    t2 = t1 * rng.choice([2, 3, 4])
    r1 = rng.choice([5, 10])
    r2 = rng.choice([10, 15]) if r1 == 5 else 15      # 100 - pct must not be a multiple of 4 or half-cent cases cannot exist
    fee, free = rng.choice([499, 599, 799]), rng.choice([5000, 7500, 10000])
    tiers = [(t1, r1), (t2, r2)]

    def pct(q):
        return max([p for m, p in tiers if q >= m], default=0)

    def line(u, q):
        return half_up(u * q * (100 - pct(q)))

    def order(lines):
        sub = sum(line(u, q) for u, q in lines)
        ship = 0 if (not lines or sub >= free) else fee
        return {"subtotal": sub, "shipping": ship, "total": sub + ship}

    values = dict(T1=t1, R1=r1, T2=t2, R2=r2, FEE=fee, FREE=free,
                  TIERS_TEXT=f"{r1}% from {t1} units, {r2}% from {t2} units")
    files = {"pricing.py": fill(STARTING, **values), "README.md": fill(README, **values),
             "tests/test_pricing.py": TESTS}
    reference = {"pricing.py": fill(REFERENCE, **values)}

    def half_cent_case(low, high, p):
        for _ in range(200000):
            u, q = rng.randint(1, 999), rng.randint(low, high)
            n = u * q * (100 - p)
            if n % 100 == 50 and (n // 100) % 2 == 0:
                return u, q
        raise RuntimeError("no half-cent example for these tiers")

    c = []
    t, r = "target", "regression"
    c += [
        call_case(t, "tier1_boundary", ID, "m.discount_percent(%d)" % t1, r1),
        call_case(t, "tier2_boundary", ID, "m.discount_percent(%d)" % t2, r2),
        call_case(t, "line_at_tier1_boundary", ID, "m.line_total(1000, %d)" % t1, line(1000, t1)),
    ]
    for i, (low, high, p) in enumerate([(t1 + 1, t2 - 1, r1), (t2 + 1, t2 + 9, r2), (t1 + 1, t2 - 1, r1)]):
        u, q = half_cent_case(low, high, p)
        c.append(call_case(t, f"half_up_rounding_{i}", ID, f"m.line_total({u}, {q})", line(u, q)))
    q = t1 + 1
    u = -(-free // q)                                  # gross reaches the threshold, discounted subtotal does not
    c.append(call_case(t, "free_shipping_uses_discounted_subtotal", ID, f"m.order_total([({u}, {q})])", order([(u, q)])))
    c.append(call_case(t, "empty_order", ID, "m.order_total([])", {"subtotal": 0, "shipping": 0, "total": 0}))
    for name, expr in [("zero_qty", "m.line_total(100, 0)"), ("negative_price", "m.line_total(-1, 2)"),
                       ("float_qty", "m.line_total(10, 1.5)"), ("bool_price", "m.line_total(True, 2)"),
                       ("order_zero_qty", "m.order_total([(100, 0)])")]:
        c.append(raises_case(t, name, ID, expr, "ValueError"))
    for i in range(3):
        lines = [(rng.randint(50, 900), t1)] + [(rng.randint(50, 900), rng.randint(1, t2 + 5)) for _ in range(rng.randint(1, 3))]
        rng.shuffle(lines)
        c.append(call_case(t, f"generated_order_{i}", ID, f"m.order_total({lines!r})", order(lines)))
    c += [
        call_case(r, "below_tier1", ID, f"m.discount_percent({t1 - 1})", 0),
        call_case(r, "inside_tier1", ID, f"m.discount_percent({t1 + 1})", r1),
        call_case(r, "above_tier2", ID, f"m.discount_percent({t2 + 1})", r2),
        call_case(r, "single_unit", ID, "m.line_total(250, 1)", 250),
        call_case(r, "undiscounted_line", ID, f"m.line_total(100, {t1 - 1})", 100 * (t1 - 1)),
        call_case(r, "small_order_pays_shipping", ID, "m.order_total([(1000, 2)])",
                  {"subtotal": 2000, "shipping": fee, "total": 2000 + fee}),
        call_case(r, "threshold_is_free", ID, f"m.order_total([({free}, 1)])",
                  {"subtotal": free, "shipping": 0, "total": free}),
        call_case(r, "just_below_threshold", ID, f"m.order_total([({free - 1}, 1)])",
                  {"subtotal": free - 1, "shipping": fee, "total": free - 1 + fee}),
    ]
    intro = ("Task: `pricing.py` has bugs in tier boundaries, rounding, the free-shipping rule and input "
             "validation. Make it match README.md exactly.")
    return finalize(ID, DIFFICULTY, "Fix the order pricing", intro, files, c, reference, seed)
