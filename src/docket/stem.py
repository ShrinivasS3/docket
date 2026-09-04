"""Porter stemmer (1980), so recall tolerates plurals and derivational suffixes:
aggregation / aggregate -> aggreg, oscillator / oscillators / oscillation -> oscil.
Pure function of a lowercase ASCII word; anything else passes through."""

from __future__ import annotations

from functools import cache

_VOWELS = "aeiou"

_STEP2 = (
    ("ational", "ate"),
    ("tional", "tion"),
    ("enci", "ence"),
    ("anci", "ance"),
    ("izer", "ize"),
    ("abli", "able"),
    ("alli", "al"),
    ("entli", "ent"),
    ("eli", "e"),
    ("ousli", "ous"),
    ("ization", "ize"),
    ("ation", "ate"),
    ("ator", "ate"),
    ("alism", "al"),
    ("iveness", "ive"),
    ("fulness", "ful"),
    ("ousness", "ous"),
    ("aliti", "al"),
    ("iviti", "ive"),
    ("biliti", "ble"),
)
_STEP3 = (
    ("icate", "ic"),
    ("ative", ""),
    ("alize", "al"),
    ("iciti", "ic"),
    ("ical", "ic"),
    ("ful", ""),
    ("ness", ""),
)
_STEP4 = (
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment",
    "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
)  # fmt: skip


def _is_cons(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _is_cons(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """m in [C](VC)^m[V]: the number of vowel-consonant sequences."""
    n, i, length = 0, 0, len(stem)
    while i < length and _is_cons(stem, i):
        i += 1
    while i < length:
        while i < length and not _is_cons(stem, i):
            i += 1
        if i >= length:
            break
        n += 1
        while i < length and _is_cons(stem, i):
            i += 1
    return n


def _has_vowel(stem: str) -> bool:
    return any(not _is_cons(stem, i) for i in range(len(stem)))


def _double_cons(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _is_cons(word, len(word) - 1)


def _ends_cvc(word: str) -> bool:
    n = len(word)
    return (
        n >= 3
        and _is_cons(word, n - 1)
        and not _is_cons(word, n - 2)
        and _is_cons(word, n - 3)
        and word[-1] not in "wxy"
    )


def _longest(word: str, suffixes) -> str | None:
    best = None
    for suffix in suffixes:
        if word.endswith(suffix) and (best is None or len(suffix) > len(best)):
            best = suffix
    return best


@cache
def stem(word: str) -> str:
    if len(word) <= 2 or not word.isascii() or not word.isalpha():
        return word
    w = word
    # 1a
    if w.endswith("sses") or w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("ss"):
        pass
    elif w.endswith("s"):
        w = w[:-1]
    # 1b
    if w.endswith("eed"):
        if _measure(w[:-3]) > 0:
            w = w[:-1]
    else:
        cut = None
        for suffix in ("ed", "ing"):
            if w.endswith(suffix) and _has_vowel(w[: -len(suffix)]):
                cut = suffix
                break
        if cut:
            w = w[: -len(cut)]
            if w.endswith(("at", "bl", "iz")):
                w += "e"
            elif _double_cons(w) and w[-1] not in "lsz":
                w = w[:-1]
            elif _measure(w) == 1 and _ends_cvc(w):
                w += "e"
    # 1c
    if w.endswith("y") and _has_vowel(w[:-1]):
        w = w[:-1] + "i"
    # 2 and 3: longest matching suffix, applied when m(stem) > 0
    for rules in (_STEP2, _STEP3):
        suffix = _longest(w, [s for s, _ in rules])
        if suffix is not None:
            base = w[: -len(suffix)]
            if _measure(base) > 0:
                w = base + dict(rules)[suffix]
    # 4: drop the longest matching suffix when m(stem) > 1
    suffix = _longest(w, _STEP4)
    if suffix is not None:
        base = w[: -len(suffix)]
        if _measure(base) > 1 and (suffix != "ion" or base.endswith(("s", "t"))):
            w = base
    # 5a
    if w.endswith("e"):
        base = w[:-1]
        m = _measure(base)
        if m > 1 or (m == 1 and not _ends_cvc(base)):
            w = base
    # 5b
    if _measure(w) > 1 and _double_cons(w) and w.endswith("l"):
        w = w[:-1]
    return w
