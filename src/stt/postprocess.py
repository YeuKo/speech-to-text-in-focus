"""Transcription post-processing: custom vocabulary and replacements.

Pure logic (no Windows or model dependencies), which makes it the easiest part
to test. Two mechanisms:

1. ``build_prompt``: builds the ``initial_prompt`` passed to Whisper to bias
   recognition towards the proper nouns in the dictionary.
2. ``apply``: applies replacements on the already-transcribed text. By default
   exact whole-word matching (case-insensitive). If ``rapidfuzz`` is installed,
   ``apply_fuzzy`` adds correction by phonetic similarity.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def build_prompt(terms: Iterable[str]) -> str | None:
    """Build the biasing prompt from the dictionary terms.

    Returns None when there are no terms, to avoid passing an empty prompt to
    Whisper.
    """
    cleaned = [t.strip() for t in terms if t and t.strip()]
    if not cleaned:
        return None
    return "Vocabulary: " + ", ".join(cleaned) + "."


def _match_case(source: str, replacement: str) -> str:
    """Adjust the replacement's case to match the original word when it makes sense.

    - If the original is UPPERCASE, the replacement is uppercased.
    - If the original starts with a capital, the replacement is capitalised.
    - Otherwise the replacement is kept as-is (useful for proper nouns such as
      "Anthropic" or "Kubernetes", which already carry their own capitalisation).
    """
    if source.isupper() and len(source) > 1:
        return replacement.upper()
    if source[:1].isupper() and replacement[:1].islower():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def apply(text: str, replacements: Mapping[str, str]) -> str:
    """Apply exact whole-word replacements (case-insensitive).

    Keys are matched on whole-word boundaries (``\\b``), so "anthropik" does not
    affect "anthropikism". The value keeps its spelling, adjusting only the
    leading case to match the original word.
    """
    if not replacements or not text:
        return text

    # Lowercased key -> canonical replacement.
    lookup = {k.lower(): v for k, v in replacements.items() if k}
    if not lookup:
        return text

    # Single pass alternating over all keys (longest first to avoid overlaps).
    keys = sorted(lookup, key=len, reverse=True)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b",
        re.IGNORECASE | re.UNICODE,
    )

    def _sub(m: re.Match[str]) -> str:
        original = m.group(0)
        replacement = lookup[original.lower()]
        return _match_case(original, replacement)

    return pattern.sub(_sub, text)


def apply_fuzzy(
    text: str,
    terms: Iterable[str],
    *,
    threshold: int = 85,
) -> str:
    """Correct words that resemble a dictionary term by similarity.

    Requires ``rapidfuzz``. If it is not installed, returns the text unchanged.
    Useful for phonetic variants that exact rules do not catch.
    """
    term_list = [t.strip() for t in terms if t and t.strip()]
    if not term_list or not text:
        return text
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return text

    def _replace(m: re.Match[str]) -> str:
        word = m.group(0)
        # Don't touch words that already match a term exactly.
        if word in term_list:
            return word
        match = process.extractOne(word, term_list, scorer=fuzz.ratio)
        if match and match[1] >= threshold and match[0].lower() != word.lower():
            return _match_case(word, match[0])
        return word

    return _WORD_RE.sub(_replace, text)


__all__ = ["build_prompt", "apply", "apply_fuzzy"]
