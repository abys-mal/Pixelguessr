"""Conservative validation of newly assigned player names, never historical scans."""

import re
import unicodedata
from functools import lru_cache

from better_profanity import Profanity
from django.core.exceptions import ValidationError

NAME_ERROR = "This name isn't allowed. Please choose another."
# Neutral identities and beliefs are not inappropriate names. The upstream list
# contains some of these terms; keep local exceptions explicit and reviewable.
NEUTRAL_WORDS = ("gay", "lesbian", "queer", "bisexual", "homosexual", "transgender", "god")
SPELLED_WORD = re.compile(r"(?<!\w)(?:[a-z0-9@*$]\s+){2,}[a-z0-9@*$](?!\w)")


@lru_cache(maxsize=1)
def name_filter():
    checker = Profanity()
    checker.load_censor_words(whitelist_words=list(NEUTRAL_WORDS))
    return checker


@lru_cache(maxsize=2)
def joined_word_patterns(reverse=False):
    """Reuse the pinned package's filtered vocabulary and character substitutions."""
    checker = name_filter()
    by_length = {}
    for entry in checker.CENSOR_WORDSET:
        word = str(entry)
        if not re.fullmatch(r"[a-z0-9]{2,}", word):
            continue
        if reverse:
            word = word[::-1]
        pattern = "".join(
            "(?:" + "|".join(re.escape(c) for c in checker.CHARS_MAPPING.get(char, (char,))) + ")"
            for char in word
        )
        by_length.setdefault(len(word), set()).add(pattern)
    return tuple(
        (length, re.compile("|".join(sorted(patterns))))
        for length, patterns in sorted(by_length.items())
    )


def joined_terms(token, *, edge=False, reverse=False):
    """Require two complete terms, not a single prohibited substring.

    Whole tokens may consist of short terms. At an edge of a longer name each
    term must be at least four characters, so 'assassin' is not mistaken for a
    repeated short term. Bounded segmentation avoids a backtracking repetition
    over the package's overlapping leetspeak variants.
    """
    if reverse:
        token = token[::-1]
    parts = [-1] * (len(token) + 1)
    parts[0] = 0
    for start in range(len(token)):
        if parts[start] < 0:
            continue
        for length, pattern in joined_word_patterns(reverse):
            end = start + length
            if end > len(token):
                break
            if edge and length < 4:
                continue
            if pattern.fullmatch(token, start, end):
                count = parts[start] + 1
                if count >= 2 and (edge or end == len(token)):
                    return True
                parts[end] = max(parts[end], count)
    return False


def contains_joined_terms(text):
    return any(
        joined_terms(token)
        or joined_terms(token, edge=True)
        or joined_terms(token, edge=True, reverse=True)
        for token in re.findall(r"[a-z0-9@*$]{4,}", text)
    )


def validate_player_name(value):
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Cf")
    # Preserve whole-word matching: innocent substrings (Scunthorpe, Dickinson,
    # Classic) must not become offences. CamelCase is an explicit token boundary.
    camel = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", normalized)
    for text in {normalized.casefold(), camel.casefold()}:
        separated = re.sub(r"[._-]+", " ", text)
        compact = SPELLED_WORD.sub(lambda match: re.sub(r"\s+", "", match.group()), separated)
        without_suffix = re.sub(r"(?<=[a-z])[0-9]+\b", "", compact)
        if any(
            name_filter().contains_profanity(candidate) or contains_joined_terms(candidate)
            for candidate in {text, compact, without_suffix}
        ):
            raise ValidationError(NAME_ERROR)
