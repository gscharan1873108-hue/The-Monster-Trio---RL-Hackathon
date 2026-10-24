"""Medium: repair a TTL + LRU cache (expiry boundary, recency, purge rules, stats)."""
from .base import REF, Case, finalize, fill, rng_for

ID, DIFFICULTY = "ttl_cache", "medium"

STARTING = '''import time
from collections import OrderedDict

DEFAULT_CAPACITY = __CAP__
DEFAULT_TTL = __TTL__


class TTLCache:
    def __init__(self, capacity=DEFAULT_CAPACITY, ttl=DEFAULT_TTL, clock=time.monotonic):
        self.capacity = capacity
        self.ttl = ttl
        self._clock = clock
        self._data = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def get(self, key, default=None):
        entry = self._data.get(key)
        if entry is None:
            self._misses += 1
            return default
        value, expires_at = entry
        if expires_at is not None and self._clock() > expires_at:
            del self._data[key]
            self._misses += 1
            return default
        self._hits += 1
        return value

    def put(self, key, value, ttl=None):
        ttl = self.ttl if ttl is None else ttl
        if key not in self._data and len(self._data) >= self.capacity:
            self._data.popitem(last=False)
            self._evictions += 1
        expires_at = None if ttl is None else self._clock() + ttl
        self._data[key] = (value, expires_at)

    def delete(self, key):
        return self._data.pop(key, None) is not None

    def __len__(self):
        return len(self._data)

    def keys(self):
        return list(self._data)

    def stats(self):
        return {"hits": self._hits, "misses": self._misses,
                "evictions": self._evictions, "expirations": self._expirations}
'''

REFERENCE = '''import time
from collections import OrderedDict

DEFAULT_CAPACITY = __CAP__
DEFAULT_TTL = __TTL__


class TTLCache:
    def __init__(self, capacity=DEFAULT_CAPACITY, ttl=DEFAULT_TTL, clock=time.monotonic):
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be an int >= 1")
        self._check_ttl(ttl)
        self.capacity = capacity
        self.ttl = ttl
        self._clock = clock
        self._data = OrderedDict()          # key -> (value, expires_at or None), oldest use first
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    @staticmethod
    def _check_ttl(ttl):
        if ttl is not None and ttl < 0:
            raise ValueError("ttl must be >= 0 or None")

    def _purge(self):
        now = self._clock()
        for key in [k for k, (_v, exp) in self._data.items() if exp is not None and now >= exp]:
            del self._data[key]
            self._expirations += 1

    def get(self, key, default=None):
        entry = self._data.get(key)
        if entry is not None and entry[1] is not None and self._clock() >= entry[1]:
            del self._data[key]
            self._expirations += 1
            entry = None
        if entry is None:
            self._misses += 1
            return default
        self._data.move_to_end(key)
        self._hits += 1
        return entry[0]

    def put(self, key, value, ttl=None):
        ttl = self.ttl if ttl is None else ttl
        self._check_ttl(ttl)
        self._purge()
        if key in self._data:
            del self._data[key]
        elif len(self._data) >= self.capacity:
            self._data.popitem(last=False)
            self._evictions += 1
        self._data[key] = (value, None if ttl is None else self._clock() + ttl)

    def delete(self, key):
        self._purge()
        return self._data.pop(key, _MISSING) is not _MISSING

    def __contains__(self, key):
        self._purge()
        return key in self._data

    def __len__(self):
        self._purge()
        return len(self._data)

    def keys(self):
        self._purge()
        return list(self._data)

    def stats(self):
        self._purge()
        return {"hits": self._hits, "misses": self._misses,
                "evictions": self._evictions, "expirations": self._expirations}


_MISSING = object()
'''

README = '''# ttl_cache

`TTLCache(capacity=DEFAULT_CAPACITY, ttl=DEFAULT_TTL, clock=time.monotonic)` in `ttl_cache.py`
(here `DEFAULT_CAPACITY = __CAP__`, `DEFAULT_TTL = __TTL__`). `clock` is any zero-argument callable
returning a number; tests inject a fake one.

- `capacity` must be an int >= 1, `ttl` must be `None` (never expires) or >= 0, otherwise `ValueError`.
- `put(key, value, ttl=None)`: `ttl=None` means "use the cache's default ttl"; a given `ttl` overrides it
  for this entry (negative -> `ValueError`). An entry stored at time `t` with ttl `n` is expired when
  `clock() >= t + n` (the boundary itself is expired). Updating an existing key replaces the value,
  restarts its ttl and makes it the most recently used.
- When a NEW key is inserted into a full cache, expired entries are dropped first; only if the cache is
  still full is the least recently used entry evicted (counted as an eviction).
- `get(key, default=None)`: a hit makes the entry the most recently used (its expiry does not change).
  If the entry is expired it is removed (one expiration) and counts as a miss. `get` only looks at its
  own key.
- `delete(key)` returns `True` if a live entry was removed, `False` otherwise (expired entries are gone).
- `key in cache`, `len(cache)`, `cache.keys()` (live keys, least recently used first), `delete`, `put`
  and `stats()` first remove ALL expired entries, each counted as one expiration. `in` does not change recency.
- `stats()` returns `{"hits": .., "misses": .., "evictions": .., "expirations": ..}`.
'''

TESTS = '''import unittest

from ttl_cache import TTLCache


class Clock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


class TTLCacheTests(unittest.TestCase):
    def test_put_get(self):
        cache = TTLCache(capacity=2, ttl=None, clock=Clock())
        cache.put("a", 1)
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("zzz", "dflt"), "dflt")

    def test_get_refreshes_recency(self):
        cache = TTLCache(capacity=2, ttl=None, clock=Clock())
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")
        cache.put("c", 3)
        self.assertEqual(cache.keys(), ["a", "c"])

    def test_entry_expires_at_ttl(self):
        clock = Clock()
        cache = TTLCache(capacity=2, ttl=5, clock=clock)
        cache.put("a", 1)
        clock.t = 5
        self.assertIsNone(cache.get("a"))


if __name__ == "__main__":
    unittest.main()
'''

CLOCK = ("class Clock:\n    def __init__(self):\n        self.t = 0\n    def __call__(self):\n        return self.t\n"
         "clk = Clock()\nfrom ttl_cache import TTLCache\n")


def script(group, name, body, expect=None, derived=False):
    return Case(name, group, CLOCK + body, REF if derived else expect)


def trace_body(rng, capacity, ttl):
    lines = [f"c = TTLCache(capacity={capacity}, ttl={ttl}, clock=clk)", "log = []"]
    keys = ["a", "b", "c", "d", "e", "f"]
    for i in range(45):
        op = rng.choice(["put", "put", "put", "get", "get", "delete", "tick", "tick", "len", "keys", "in"])
        key = rng.choice(keys)
        if op == "put":
            extra = f", ttl={rng.choice([2, 3, 5, 8])}" if rng.random() < 0.3 else ""
            lines.append(f"c.put({key!r}, {i}{extra})")
        elif op == "get":
            lines.append(f"log.append(c.get({key!r}, 'miss'))")
        elif op == "delete":
            lines.append(f"log.append(c.delete({key!r}))")
        elif op == "tick":
            lines.append(f"clk.t += {rng.randint(1, 6)}")
        elif op == "len":
            lines.append("log.append(len(c))")
        elif op == "keys":
            lines.append("log.append(c.keys())")
        else:
            lines.append(f"log.append({key!r} in c)")
    lines += ["log.append(c.stats())", "result = log"]
    return "\n".join(lines) + "\n"


def build(seed):
    rng = rng_for(ID, seed)
    cap, ttl = rng.choice([3, 4, 5]), rng.choice([10, 30, 60])
    values = dict(CAP=cap, TTL=ttl)
    files = {"ttl_cache.py": fill(STARTING, **values), "README.md": fill(README, **values),
             "tests/test_ttl_cache.py": TESTS}
    reference = {"ttl_cache.py": fill(REFERENCE, **values)}
    t, r = "target", "regression"
    c = [
        script(t, "lru_refresh_on_get", "c = TTLCache(capacity=3, ttl=None, clock=clk)\n"
               "for k in 'abc':\n    c.put(k, 1)\nc.get('a')\nc.put('d', 1)\nresult = c.keys()\n", ["c", "a", "d"]),
        script(t, "expiry_boundary_is_expired", "c = TTLCache(capacity=3, ttl=10, clock=clk)\nc.put('k', 'v')\n"
               "clk.t = 9\nfirst = c.get('k')\nclk.t = 10\nresult = [first, c.get('k')]\n", ["v", None]),
        script(t, "default_ttl_boundary", f"c = TTLCache(clock=clk)\nc.put('k', 'v')\nclk.t = {ttl - 1}\nfirst = c.get('k')\n"
               f"clk.t = {ttl}\nresult = [first, c.get('k')]\n", ["v", None]),
        script(t, "purge_before_evict", "c = TTLCache(capacity=2, ttl=5, clock=clk)\nc.put('a', 1)\nclk.t = 3\n"
               "c.put('b', 2)\nclk.t = 6\nc.put('c', 3)\nresult = [c.keys(), c.stats()]\n",
               [["b", "c"], {"hits": 0, "misses": 0, "evictions": 0, "expirations": 1}]),
        script(t, "len_keys_contains_skip_expired", "c = TTLCache(capacity=5, ttl=10, clock=clk)\n"
               "c.put('a', 1, ttl=2)\nc.put('b', 2)\nclk.t = 2\nresult = [len(c), c.keys(), 'a' in c, 'b' in c]\n",
               [1, ["b"], False, True]),
        script(t, "update_refreshes_recency", "c = TTLCache(capacity=2, ttl=None, clock=clk)\nc.put('a', 1)\n"
               "c.put('b', 2)\nc.put('a', 3)\nc.put('c', 4)\nresult = [c.keys(), c.get('a')]\n", [["a", "c"], 3]),
        script(t, "stats_count_expiration", "c = TTLCache(capacity=3, ttl=100, clock=clk)\nc.put('a', 1, ttl=5)\n"
               "c.put('b', 2)\nclk.t = 5\nr1 = c.get('a')\nr2 = c.get('b')\nresult = [r1, r2, c.stats()]\n",
               [None, 2, {"hits": 1, "misses": 1, "evictions": 0, "expirations": 1}]),
        script(t, "delete_expired_is_false", "c = TTLCache(capacity=3, ttl=None, clock=clk)\nc.put('a', 1, ttl=3)\n"
               "clk.t = 3\nresult = [c.delete('a'), c.delete('zzz'), len(c)]\n", [False, False, 0]),
        script(t, "bad_capacity", "try:\n    TTLCache(capacity=0, clock=clk)\n    result = 'no error'\n"
               "except ValueError:\n    result = 'ValueError'\n", "ValueError"),
        script(t, "bad_entry_ttl", "c = TTLCache(capacity=2, ttl=None, clock=clk)\ntry:\n    c.put('a', 1, ttl=-1)\n"
               "    result = 'no error'\nexcept ValueError:\n    result = 'ValueError'\n", "ValueError"),
    ]
    for i in range(4):
        c.append(script("auto", f"random_trace_{i}", trace_body(rng, rng.choice([2, 3, 4]), rng.choice(["None", 6, 12])), derived=True))
    c += [
        script(r, "update_restarts_ttl", "c = TTLCache(capacity=2, ttl=5, clock=clk)\nc.put('a', 1)\nclk.t = 4\n"
               "c.put('a', 2)\nclk.t = 8\nresult = c.get('a')\n", 2),
        script(r, "basic_put_get", "c = TTLCache(capacity=3, ttl=None, clock=clk)\nc.put('a', 1)\nc.put('b', 2)\n"
               "result = [c.get('a'), c.get('zz', 'dflt'), len(c)]\n", [1, "dflt", 2]),
        script(r, "fifo_eviction_without_reads", "c = TTLCache(capacity=2, ttl=None, clock=clk)\nc.put('a', 1)\n"
               "c.put('b', 2)\nc.put('c', 3)\nresult = c.keys()\n", ["b", "c"]),
        script(r, "delete_live_entry", "c = TTLCache(capacity=3, ttl=None, clock=clk)\nc.put('a', 1)\nc.put('b', 2)\n"
               "result = [c.delete('a'), c.delete('a'), len(c)]\n", [True, False, 1]),
        script(r, "simple_hit_miss_stats", "c = TTLCache(capacity=2, ttl=None, clock=clk)\nc.put('a', 1)\nc.get('a')\n"
               "c.get('b')\nresult = c.stats()\n", {"hits": 1, "misses": 1, "evictions": 0, "expirations": 0}),
        script(r, "long_expired_entry_is_gone", "c = TTLCache(capacity=2, ttl=5, clock=clk)\nc.put('a', 1)\n"
               "clk.t = 100\nresult = [c.get('a'), len(c)]\n", [None, 0]),
        script(r, "none_ttl_never_expires", "c = TTLCache(capacity=2, ttl=None, clock=clk)\nc.put('a', 'v')\n"
               "clk.t = 10 ** 9\nresult = c.get('a')\n", "v"),
        script(r, "default_capacity_fifo", f"c = TTLCache(ttl=None, clock=clk)\nfor i in range({cap + 1}):\n"
               "    c.put(str(i), i)\nresult = c.keys()\n", [str(i) for i in range(1, cap + 1)]),
    ]
    intro = ("Task: `ttl_cache.py` implements a TTL + LRU cache with several bugs (expiry boundary, recency, "
             "purging, statistics, validation). Make `TTLCache` behave exactly as README.md specifies.")
    return finalize(ID, DIFFICULTY, "Repair the TTL/LRU cache", intro, files, c, reference, seed)
