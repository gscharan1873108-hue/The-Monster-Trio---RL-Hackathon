"""Medium: fix an order-reservation warehouse (atomicity, order lifecycle, validation, copies)."""
from .base import Case, REF, finalize, fill, rng_for

ID, DIFFICULTY = "ledger", "medium"

ERRORS = '''class WarehouseError(Exception):
    pass


class InsufficientStock(WarehouseError):
    def __init__(self, missing):
        super().__init__(f"insufficient stock: {missing}")
        self.missing = missing


class DuplicateOrder(WarehouseError):
    pass


class UnknownOrder(WarehouseError):
    pass


class OrderClosed(WarehouseError):
    pass


class InvalidQuantity(WarehouseError, ValueError):
    pass
'''

STARTING = ERRORS + '''

class Warehouse:
    def __init__(self, stock):
        self._stock = stock
        self._orders = {}

    def available(self, sku):
        return self._stock.get(sku, 0)

    def snapshot(self):
        return self._stock

    def status(self, order_id):
        return self._orders[order_id]["state"]

    def reserve(self, order_id, items):
        for sku, qty in items.items():
            if self._stock.get(sku, 0) < qty:
                raise InsufficientStock({sku: qty - self._stock.get(sku, 0)})
            self._stock[sku] -= qty
        self._orders[order_id] = {"items": dict(items), "state": "reserved"}

    def release(self, order_id):
        order = self._orders[order_id]
        for sku, qty in order["items"].items():
            self._stock[sku] = self._stock.get(sku, 0) + qty
        order["state"] = "released"

    def commit(self, order_id):
        self._orders[order_id]["state"] = "committed"
'''

REFERENCE = ERRORS + '''

def _is_count(value, minimum):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


class Warehouse:
    def __init__(self, stock):
        for sku, qty in stock.items():
            if not _is_count(qty, 0):
                raise InvalidQuantity(f"stock for {sku!r} must be an int >= 0")
        self._stock = dict(stock)
        self._orders = {}

    def available(self, sku):
        return self._stock.get(sku, 0)

    def snapshot(self):
        return dict(sorted(self._stock.items()))

    def _order(self, order_id):
        if order_id not in self._orders:
            raise UnknownOrder(order_id)
        return self._orders[order_id]

    def status(self, order_id):
        return self._order(order_id)["state"]

    def reserve(self, order_id, items):
        if order_id in self._orders:
            raise DuplicateOrder(order_id)
        if not items:
            raise InvalidQuantity("an order needs at least one item")
        for sku, qty in items.items():
            if not _is_count(qty, 1):
                raise InvalidQuantity(f"quantity for {sku!r} must be an int >= 1")
        missing = {sku: qty - self._stock.get(sku, 0) for sku, qty in items.items()
                   if qty > self._stock.get(sku, 0)}
        if missing:
            raise InsufficientStock(dict(sorted(missing.items())))
        for sku, qty in items.items():
            self._stock[sku] -= qty
        self._orders[order_id] = {"items": dict(items), "state": "reserved"}

    def release(self, order_id):
        order = self._order(order_id)
        if order["state"] != "reserved":
            raise OrderClosed(order_id)
        for sku, qty in order["items"].items():
            self._stock[sku] = self._stock.get(sku, 0) + qty
        order["state"] = "released"

    def commit(self, order_id):
        order = self._order(order_id)
        if order["state"] != "reserved":
            raise OrderClosed(order_id)
        order["state"] = "committed"
'''

README = '''# ledger

`Warehouse(stock)` in `ledger.py` reserves stock for orders. `stock` maps a SKU (for example
`"__A__"`, `"__B__"`) to an int >= 0; the constructor copies it (later changes to the dict you passed
in do not affect the warehouse) and raises `InvalidQuantity` for a bad count.

Exceptions (all in `ledger.py`): `WarehouseError` is the base; `InsufficientStock` (has `.missing`, a dict
SKU -> shortfall), `DuplicateOrder`, `UnknownOrder`, `OrderClosed`, and `InvalidQuantity`
(also a `ValueError`).

- `available(sku)` -> int (0 for an SKU the warehouse has never stocked).
- `snapshot()` -> a NEW dict of SKU -> available units, sorted by SKU; changing it never changes the warehouse.
- `reserve(order_id, items)`: `items` maps SKU -> quantity. Checks run in this order:
  1. `order_id` already used (in any state) -> `DuplicateOrder`.
  2. `items` empty, or any quantity that is not an int >= 1 (bools are not ints) -> `InvalidQuantity`.
  3. Not enough stock -> `InsufficientStock` whose `.missing` lists EVERY short SKU with its shortfall
     (an unknown SKU counts as stock 0).
  The reservation is all-or-nothing: if it fails, no stock changes at all. On success the units leave
  `available` and the order is `"reserved"`.
- `release(order_id)`: gives a reserved order's units back and sets it `"released"`.
- `commit(order_id)`: sets a reserved order to `"committed"`; its units stay deducted.
- `release`/`commit`/`status` on an unknown order -> `UnknownOrder`; `release`/`commit` on an order that is
  not `"reserved"` -> `OrderClosed`.
- `status(order_id)` -> `"reserved"`, `"committed"` or `"released"`.
'''

TESTS = '''import unittest

from ledger import InsufficientStock, Warehouse


class WarehouseTests(unittest.TestCase):
    def test_reserve_and_release(self):
        w = Warehouse({"__A__": 5})
        w.reserve("o1", {"__A__": 2})
        self.assertEqual(w.available("__A__"), 3)
        w.release("o1")
        self.assertEqual(w.available("__A__"), 5)

    def test_insufficient_stock(self):
        w = Warehouse({"__A__": 1})
        with self.assertRaises(InsufficientStock):
            w.reserve("o1", {"__A__": 2})

    def test_failed_reservation_changes_nothing(self):
        w = Warehouse({"__A__": 5, "__B__": 1})
        with self.assertRaises(InsufficientStock):
            w.reserve("o1", {"__A__": 2, "__B__": 3})
        self.assertEqual(w.snapshot(), {"__A__": 5, "__B__": 1})


if __name__ == "__main__":
    unittest.main()
'''

SKUS = ["bolt", "nut", "gear", "belt", "valve", "pump", "seal", "chip", "wire", "cell", "fuse", "lens"]

HELPER = '''import ledger
from ledger import Warehouse
def run(fn, *args):
    try:
        out = fn(*args)
        return ["ok", out]
    except ledger.InsufficientStock as e:
        return ["InsufficientStock", e.missing]
    except Exception as e:
        return [type(e).__name__, None]
'''


def script(group, name, body, expect=REF):
    return Case(name, group, HELPER + body, expect)


def trace_body(rng, skus):
    stock = {s: rng.randint(0, 6) for s in skus}
    lines = [f"w = Warehouse({stock!r})", "log = []"]
    ids = [f"o{i}" for i in range(5)]
    for _ in range(40):
        op = rng.choice(["reserve", "reserve", "reserve", "release", "commit", "avail", "snap", "status"])
        oid = rng.choice(ids)
        if op == "reserve":
            items = {rng.choice(skus + ["ghost"]): rng.choice([1, 1, 2, 3, 4, 0, -1]) for _ in range(rng.randint(0, 3))}
            lines.append(f"log.append(run(w.reserve, {oid!r}, {items!r}))")
        elif op == "release":
            lines.append(f"log.append(run(w.release, {oid!r}))")
        elif op == "commit":
            lines.append(f"log.append(run(w.commit, {oid!r}))")
        elif op == "avail":
            lines.append(f"log.append(w.available({rng.choice(skus)!r}))")
        elif op == "status":
            lines.append(f"log.append(run(w.status, {oid!r}))")
        else:
            lines.append("log.append(w.snapshot())")
    lines += ["log.append(w.snapshot())", "result = log"]
    return "\n".join(lines) + "\n"


def build(seed):
    rng = rng_for(ID, seed)
    a, b, z = rng.sample(SKUS, 3)
    values = dict(A=a, B=b)
    files = {"ledger.py": STARTING, "README.md": fill(README, **values), "tests/test_ledger.py": fill(TESTS, **values)}
    reference = {"ledger.py": REFERENCE}
    t, r = "target", "regression"
    s0 = f"w = Warehouse({{{a!r}: 5, {b!r}: 1}})\n"
    c = [
        script(t, "reservation_is_atomic", s0 + f"res = run(w.reserve, 'o1', {{{a!r}: 2, {b!r}: 3}})\n"
               "result = [res[0], res[1], w.snapshot()]\n", ["InsufficientStock", {b: 2}, {a: 5, b: 1}]),
        script(t, "missing_lists_every_short_sku", s0 + f"result = run(w.reserve, 'o1', {{{a!r}: 9, {b!r}: 3, {z!r}: 1}})\n",
               ["InsufficientStock", {a: 4, b: 2, z: 1}]),
        script(t, "double_release_rejected", s0 + f"w.reserve('o1', {{{a!r}: 2}})\nw.release('o1')\n"
               f"second = run(w.release, 'o1')\nresult = [second[0], w.available({a!r}), w.status('o1')]\n",
               ["OrderClosed", 5, "released"]),
        script(t, "duplicate_order_id", s0 + f"w.reserve('o1', {{{a!r}: 2}})\nres = run(w.reserve, 'o1', {{{a!r}: 1}})\n"
               f"result = [res[0], w.available({a!r})]\n", ["DuplicateOrder", 3]),
        script(t, "duplicate_id_after_release", s0 + f"w.reserve('o1', {{{a!r}: 1}})\nw.release('o1')\n"
               f"result = run(w.reserve, 'o1', {{{a!r}: 1}})[0]\n", "DuplicateOrder"),
        script(t, "release_after_commit_rejected", s0 + f"w.reserve('o1', {{{a!r}: 2}})\nw.commit('o1')\n"
               f"res = run(w.release, 'o1')\nresult = [res[0], w.available({a!r}), w.status('o1')]\n",
               ["OrderClosed", 3, "committed"]),
        script(t, "commit_twice_rejected", s0 + f"w.reserve('o1', {{{a!r}: 1}})\nw.commit('o1')\n"
               "result = run(w.commit, 'o1')[0]\n", "OrderClosed"),
        script(t, "unknown_order_errors", s0 + "result = [run(w.release, 'nope')[0], run(w.commit, 'nope')[0], "
               "run(w.status, 'nope')[0]]\n", ["UnknownOrder"] * 3),
        script(t, "invalid_quantities", s0 + f"result = [run(w.reserve, 'o%d' % i, {{{a!r}: q}})[0] "
               "for i, q in enumerate([0, -1, 1.5, True, '2'])]\n", ["InvalidQuantity"] * 5),
        script(t, "invalid_quantity_is_value_error", s0 + f"try:\n    w.reserve('o1', {{{a!r}: 0}})\n    result = 'no error'\n"
               "except ValueError:\n    result = 'ValueError'\n", "ValueError"),
        script(t, "empty_order_rejected", s0 + "result = run(w.reserve, 'o1', {})[0]\n", "InvalidQuantity"),
        script(t, "failed_reserve_does_not_burn_order_id", s0 + f"run(w.reserve, 'o1', {{{a!r}: 1, {b!r}: 99}})\n"
               f"res = run(w.reserve, 'o1', {{{a!r}: 1}})\nresult = [res[0], w.status('o1'), w.available({a!r})]\n",
               ["ok", "reserved", 4]),
        script(t, "snapshot_is_a_copy", s0 + f"snap = w.snapshot()\nsnap[{a!r}] = 0\nresult = w.available({a!r})\n", 5),
        script(t, "constructor_copies_stock", f"src = {{{a!r}: 5}}\nw = Warehouse(src)\nsrc[{a!r}] = 0\n"
               f"result = w.available({a!r})\n", 5),
        script(t, "invalid_initial_stock", f"result = run(Warehouse, {{{a!r}: -1}})[0]\n", "InvalidQuantity"),
    ]
    skus = rng.sample(SKUS, 4)
    for i in range(4):
        c.append(script("auto", f"random_trace_{i}", trace_body(rng, skus)))
    c += [
        script(r, "reserve_and_release_round_trip", s0 + f"w.reserve('o1', {{{a!r}: 2}})\nmid = w.available({a!r})\n"
               f"w.release('o1')\nresult = [mid, w.available({a!r}), w.status('o1')]\n", [3, 5, "released"]),
        script(r, "commit_keeps_deduction", s0 + f"w.reserve('o1', {{{a!r}: 2}})\nw.commit('o1')\n"
               f"result = [w.available({a!r}), w.status('o1')]\n", [3, "committed"]),
        script(r, "reserve_exact_stock", s0 + f"w.reserve('o1', {{{a!r}: 5, {b!r}: 1}})\nresult = w.snapshot()\n", {a: 0, b: 0}),
        script(r, "single_sku_shortfall", f"w = Warehouse({{{a!r}: 1}})\nres = run(w.reserve, 'o1', {{{a!r}: 2}})\n"
               f"result = [res, w.snapshot()]\n", [["InsufficientStock", {a: 1}], {a: 1}]),
        script(r, "unknown_sku_available", s0 + "result = w.available('ghost')\n", 0),
    ]
    intro = ("Task: `ledger.py` reserves warehouse stock for orders but breaks its guarantees (atomic reservations, "
             "order lifecycle, validation, defensive copies). Fix `Warehouse` to follow README.md.")
    return finalize(ID, DIFFICULTY, "Fix the stock reservation ledger", intro, files, c, reference, seed)
