"""Easy: fix interval merging (sorting, boundaries, input mutation, validation, coverage)."""
from .base import call_case, finalize, fill, raises_case, rng_for

ID, DIFFICULTY = "intervals", "easy"

STARTING = '''ADJACENT_GAP = __GAP__


def merge_intervals(intervals):
    merged = []
    for iv in intervals:
        if merged and iv[0] < merged[-1][1]:
            merged[-1][1] = iv[1]
        else:
            merged.append(iv)
    return merged


def total_covered(intervals):
    return sum(end - start for start, end in intervals)
'''

REFERENCE = '''ADJACENT_GAP = __GAP__


def merge_intervals(intervals):
    cleaned = []
    for iv in intervals:
        try:
            start, end = iv
        except (TypeError, ValueError):
            raise ValueError("each interval must be a (start, end) pair") from None
        if start > end:
            raise ValueError("start must not be greater than end")
        cleaned.append([start, end])
    cleaned.sort()
    merged = []
    for start, end in cleaned:
        if merged and start <= merged[-1][1] + ADJACENT_GAP:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def total_covered(intervals):
    return sum(end - start for start, end in merge_intervals(intervals))
'''

README = '''# intervals

Closed intervals `[start, end]` of numbers, in `intervals.py`.

- `merge_intervals(intervals)` returns a NEW sorted list of `[start, end]` lists in which overlapping
  intervals are merged. The input may be unsorted, may contain duplicates and nested intervals, and its
  items may be lists or tuples. The input (and the lists inside it) must never be modified.
  Two intervals merge when `next.start <= current.end + ADJACENT_GAP`; here `ADJACENT_GAP = __GAP__`
  (__GAP_TEXT__).
- An interval with `start > end`, or an item that is not a pair, raises `ValueError`.
- `total_covered(intervals)` is the sum of `end - start` over the merged intervals, so overlaps are
  counted once.
- `merge_intervals([])` is `[]` and `total_covered([])` is `0`.
'''

TESTS = '''import unittest

from intervals import merge_intervals, total_covered


class IntervalTests(unittest.TestCase):
    def test_sorted_overlap(self):
        self.assertEqual(merge_intervals([[1, 3], [2, 5]]), [[1, 5]])

    def test_disjoint(self):
        self.assertEqual(merge_intervals([[1, 2], [10, 12]]), [[1, 2], [10, 12]])

    def test_unsorted_input(self):
        self.assertEqual(merge_intervals([[8, 9], [1, 4], [3, 6]]), [[1, 6], [8, 9]])

    def test_input_is_not_modified(self):
        data = [[5, 6], [1, 3]]
        merge_intervals(data)
        self.assertEqual(data, [[5, 6], [1, 3]])

    def test_total_counts_overlap_once(self):
        self.assertEqual(total_covered([[0, 4], [2, 6]]), 6)


if __name__ == "__main__":
    unittest.main()
'''


def build(seed):
    rng = rng_for(ID, seed)
    gap = rng.choice([0, 1])
    values = dict(GAP=gap, GAP_TEXT="touching intervals such as [1, 3] and [3, 5] merge, but [1, 3] and [4, 5] do not"
                  if gap == 0 else "intervals that touch or are one unit apart, such as [1, 3] and [4, 5], merge")
    files = {"intervals.py": fill(STARTING, **values), "README.md": fill(README, **values),
             "tests/test_intervals.py": TESTS}
    reference = {"intervals.py": fill(REFERENCE, **values)}

    def random_set(n):
        out = []
        for _ in range(n):
            s = rng.randint(0, 60)
            out.append([s, s + rng.randint(0, 12)])
        rng.shuffle(out)
        return out

    t, r = "target", "regression"
    c = [
        call_case(t, "unsorted", ID, "m.merge_intervals([[8, 9], [1, 4], [3, 6]])", [[1, 6], [8, 9]]),
        call_case(t, "nested_keeps_outer_end", ID, "m.merge_intervals([[1, 10], [2, 3], [4, 5]])", [[1, 10]]),
        call_case(t, "touching_endpoints_merge", ID, "m.merge_intervals([[1, 3], [3, 5]])", [[1, 5]]),
        call_case(t, "duplicates_and_unsorted", ID, "m.merge_intervals([[2, 4], [2, 4], [1, 3]])", [[1, 4]]),
        call_case(t, "tuples_accepted", ID, "m.merge_intervals([(5, 7), (1, 2), (2, 3)])", [[1, 3], [5, 7]]),
        call_case(t, "input_not_mutated", ID,
                  "(lambda d: (m.merge_intervals(d), d))([[5, 6], [1, 3], [2, 4]])[1]", [[5, 6], [1, 3], [2, 4]]),
        call_case(t, "inner_lists_not_mutated", ID,
                  "(lambda d: (m.merge_intervals(d), d))([[1, 3], [2, 9]])[1]", [[1, 3], [2, 9]]),
        call_case(t, "result_not_aliased", ID,
                  "(lambda d: (m.merge_intervals(d)[0].append(99), d))([[1, 3]])[1]", [[1, 3]]),
        call_case(t, "total_merges_first", ID, "m.total_covered([[0, 4], [2, 6], [10, 11]])", 7),
        call_case(t, "floats", ID, "m.merge_intervals([[1.0, 2.5], [0.5, 1.5]])", [[0.5, 2.5]]),
        raises_case(t, "start_after_end", ID, "m.merge_intervals([[5, 1]])", "ValueError"),
        raises_case(t, "not_a_pair", ID, "m.merge_intervals([[1, 2, 3]])", "ValueError"),
        raises_case(t, "not_iterable_item", ID, "m.merge_intervals([5])", "ValueError"),
    ]
    adjacent_group = t if gap == 1 else r
    adjacent = [[1, 5]] if gap == 1 else [[1, 3], [4, 5]]
    c.append(call_case(adjacent_group, "adjacent_integers", ID, "m.merge_intervals([[4, 5], [1, 3]])" if gap == 1
                       else "m.merge_intervals([[1, 3], [4, 5]])", adjacent))
    for i in range(6):
        c.append(call_case("auto", f"generated_merge_{i}", ID, f"m.merge_intervals({random_set(rng.randint(5, 10))!r})"))
    for i in range(2):
        c.append(call_case("auto", f"generated_total_{i}", ID, f"m.total_covered({random_set(rng.randint(5, 10))!r})"))
    c += [
        call_case(r, "empty", ID, "m.merge_intervals([])", []),
        call_case(r, "single", ID, "m.merge_intervals([[3, 4]])", [[3, 4]]),
        call_case(r, "sorted_overlap", ID, "m.merge_intervals([[1, 3], [2, 5]])", [[1, 5]]),
        call_case(r, "sorted_disjoint", ID, "m.merge_intervals([[1, 2], [10, 12]])", [[1, 2], [10, 12]]),
        call_case(r, "total_empty", ID, "m.total_covered([])", 0),
        call_case(r, "total_disjoint", ID, "m.total_covered([[0, 2], [10, 15]])", 7),
    ]
    intro = ("Task: `intervals.py` merges intervals incorrectly. Make `merge_intervals` and `total_covered` "
             "follow README.md, including how touching intervals, input mutation and invalid items are handled.")
    return finalize(ID, DIFFICULTY, "Fix interval merging", intro, files, c, reference, seed)
