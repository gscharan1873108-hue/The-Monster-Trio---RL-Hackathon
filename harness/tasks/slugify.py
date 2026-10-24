"""Easy: fix a text-to-slug helper (accents, separators, truncation, validation)."""
from .base import call_case, finalize, fill, raises_case, rng_for

ID, DIFFICULTY = "slugify", "easy"

STARTING = '''import re

DEFAULT_MAX_LEN = __MAX_LEN__
SEP = "__SEP__"


def slugify(text, max_len=DEFAULT_MAX_LEN, sep=SEP):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", sep, text)
    return text[:max_len]
'''

REFERENCE = '''import re
import unicodedata

DEFAULT_MAX_LEN = __MAX_LEN__
SEP = "__SEP__"


def slugify(text, max_len=DEFAULT_MAX_LEN, sep=SEP):
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    if isinstance(max_len, bool) or not isinstance(max_len, int) or max_len < 1:
        raise ValueError("max_len must be a positive int")
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    slug = re.sub(r"[^a-z0-9]+", lambda _m: sep, plain).strip(sep)
    if len(slug) <= max_len:
        return slug
    if slug[max_len] == sep:
        return slug[:max_len]
    cut = slug.rfind(sep, 0, max_len)
    return slug[:cut] if cut > 0 else slug[:max_len]
'''

README = '''# slugify

`slugify(text, max_len=DEFAULT_MAX_LEN, sep=SEP)` in `slugify.py` turns text into a URL slug.
For this project `DEFAULT_MAX_LEN = __MAX_LEN__` and `SEP = "__SEP__"`.

Rules, applied in this order:

1. `text` must be a `str`, otherwise raise `TypeError`.
2. `max_len` must be an `int` of at least 1 (not a bool), otherwise raise `ValueError`.
3. Accented letters become their base letter (`Caf\u00e9` -> `cafe`) and the result is lower case.
4. Every run of characters other than `a-z` and `0-9` becomes ONE `sep`.
5. The slug never starts or ends with `sep`.
6. If the slug is longer than `max_len`, keep as many whole words as fit in `max_len` characters.
   If the first word alone is longer than `max_len`, cut it at `max_len`. The result never ends with `sep`.
7. Text without letters or digits gives `""`.
'''

TESTS = '''import unittest

from slugify import SEP, slugify


class SlugifyTests(unittest.TestCase):
    def test_plain_words(self):
        self.assertEqual(slugify("Hello World", sep="-"), "hello-world")

    def test_default_separator(self):
        self.assertEqual(slugify("Hello World"), "hello" + SEP + "world")

    def test_punctuation_collapses(self):
        self.assertEqual(slugify("Rock & Roll!", sep="-"), "rock-roll")

    def test_accents(self):
        self.assertEqual(slugify("Cr\u00e8me Br\u00fbl\u00e9e", sep="-"), "creme-brulee")

    def test_truncates_at_word_boundary(self):
        self.assertEqual(slugify("one two three four", max_len=9, sep="-"), "one-two")


if __name__ == "__main__":
    unittest.main()
'''

WORDS = ["Caf\u00e9", "Z\u00fcrich", "na\u00efve", "Se\u00f1or", "r\u00e9sum\u00e9", "Alpha", "beta", "Gamma", "delta",
         "Epsilon", "42", "v2", "R\u00e9publique", "Fran\u00e7ois", "Sm\u00f6rg\u00e5s", "item", "launch", "plan"]
JOINERS = [" ", "  ", " - ", ", ", "!!", " & ", "_", "...", "\t", " / "]


def build(seed):
    rng = rng_for(ID, seed)
    max_len, sep = rng.choice([24, 30, 32, 40]), rng.choice(["-", "_"])
    values = dict(MAX_LEN=max_len, SEP=sep)
    files = {"slugify.py": fill(STARTING, **values), "README.md": fill(README, **values),
             "tests/test_slugify.py": TESTS}
    reference = {"slugify.py": fill(REFERENCE, **values)}

    c = []
    t, r = "target", "regression"
    c += [
        call_case(t, "accents", ID, "m.slugify('Caf\u00e9 M\u00fcnster', sep='-')", "cafe-munster"),
        call_case(t, "accents_default_sep", ID, "m.slugify('Cr\u00e8me Br\u00fbl\u00e9e')", f"creme{sep}brulee"),
        call_case(t, "collapse_runs", ID, "m.slugify('  Hello,   World!!  ', sep='-')", "hello-world"),
        call_case(t, "strip_edges", ID, "m.slugify('--A--', sep='-')", "a"),
        call_case(t, "no_alnum", ID, "m.slugify('!!! ???', sep='-')", ""),
        call_case(t, "word_boundary", ID, "m.slugify('the quick brown fox jumps', max_len=12, sep='-')", "the-quick"),
        call_case(r, "hard_cut_first_word", ID, "m.slugify('supercalifragilistic word', max_len=10, sep='-')", "supercalif"),
        call_case(t, "never_ends_with_sep", ID, "m.slugify('ab cd ef', max_len=3, sep='_')", "ab"),
        call_case(t, "other_separator", ID, "m.slugify('A  B.C', sep='.')", "a.b.c"),
        raises_case(t, "type_error", ID, "m.slugify(123)", "TypeError"),
        raises_case(t, "bad_max_len_zero", ID, "m.slugify('a', max_len=0)", "ValueError"),
        raises_case(t, "bad_max_len_bool", ID, "m.slugify('a', max_len=True)", "ValueError"),
    ]
    for i in range(6):
        words = [rng.choice(WORDS) for _ in range(rng.randint(3, 9))]
        words[rng.randrange(len(words))] = rng.choice(WORDS[:5])
        text = rng.choice(JOINERS).join(words)
        c.append(call_case("auto", f"generated_{i}", ID, f"m.slugify({text!r}, max_len={rng.randint(6, 40)}, sep={sep!r})"))
    c += [
        call_case(r, "simple", ID, "m.slugify('hello world', sep='-')", "hello-world"),
        call_case(r, "digits", ID, "m.slugify('Python 3 Rocks', sep='-')", "python-3-rocks"),
        call_case(r, "short_enough", ID, "m.slugify('One Two', max_len=50, sep='_')", "one_two"),
        call_case(r, "single_word", ID, "m.slugify('Word', sep='-')", "word"),
        call_case(r, "exact_boundary", ID, "m.slugify('the quick brown fox', max_len=9, sep='-')", "the-quick"),
        call_case(r, "default_sep_simple", ID, "m.slugify('a b')", f"a{sep}b"),
    ]
    intro = ("Task: `slugify.py` has bugs. Make `slugify` follow every rule in README.md "
             "(accents, separator runs, edges, word-boundary truncation, validation).")
    return finalize(ID, DIFFICULTY, "Fix the slug generator", intro, files, c, reference, seed)
