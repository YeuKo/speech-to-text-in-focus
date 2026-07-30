"""Transcription post-processing: custom vocabulary and replacements.

Pure logic (no Windows or model dependencies), which makes it the easiest part
to test. Three mechanisms:

1. ``build_prompt``: builds the ``initial_prompt`` passed to Whisper to bias
   recognition towards the proper nouns in the dictionary. ``with_context``
   extends it with what was said moments ago, so a chunk is not decoded blind.
2. ``apply``: applies replacements on the already-transcribed text. By default
   exact whole-word matching (case-insensitive). If ``rapidfuzz`` is installed,
   ``apply_fuzzy`` adds correction by phonetic similarity.
3. ``is_prompt_echo`` / ``is_context_echo`` / ``collapse_repeats``: drop the text
   Whisper invents when there is nothing to transcribe.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Sentence boundary: after .!?… and the closing punctuation Spanish adds.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

# First word of the prompt built by build_prompt, and its likely translations:
# Whisper may echo the prompt in the language of the audio.
_PROMPT_PREAMBLE = frozenset({"vocabulary", "vocabulario", "vocabulaire", "vokabular"})

# Shortest word apply_fuzzy will touch: below this, similarity scores are noise.
_FUZZY_MIN_LEN = 5

# Longest repeating cycle collapse_repeats looks for, in sentences.
_MAX_CYCLE = 3

# Whisper keeps only the *last* ~224 tokens of the initial prompt and silently
# drops the rest, so an unbounded context would push the vocabulary — which goes
# first — out of the prompt entirely. Budgeted in characters (Spanish runs about
# three per token) with room to spare.
_PROMPT_MAX_CHARS = 600

# Shortest run of words is_context_echo will call an echo. Five words repeated
# verbatim are almost certainly the model reciting its prompt back; two are
# something a person plausibly said twice.
_ECHO_MIN_WORDS = 5


def build_prompt(terms: Iterable[str]) -> str | None:
    """Build the biasing prompt from the dictionary terms.

    Returns None when there are no terms, to avoid passing an empty prompt to
    Whisper.
    """
    cleaned = [t.strip() for t in terms if t and t.strip()]
    if not cleaned:
        return None
    return "Vocabulary: " + ", ".join(cleaned) + "."


def with_context(prompt: str | None, context: str) -> str | None:
    """Extend the biasing prompt with what was just transcribed.

    Chunks are decoded one at a time and independently, so by default the model
    starts each one knowing nothing about the sentence it is in the middle of.
    Whisper's ``initial_prompt`` is precisely the channel for that context: text
    that precedes the audio and conditions the decoding. Feeding it the tail of
    the dictation is what keeps a sentence whole across a cut.

    The context is trimmed to what fits alongside the vocabulary, keeping the
    most recent part and starting it on a sentence boundary where possible.
    """
    context = context.strip()
    if not context:
        return prompt

    prefix = f"{prompt} " if prompt else ""
    budget = _PROMPT_MAX_CHARS - len(prefix)
    if budget <= 0:                                # a vocabulary that long is already
        return prompt                              # more than the prompt can hold

    tail = _tail(context, budget)
    return prefix + tail if tail else prompt


def _tail(text: str, budget: int) -> str:
    """The last ``budget`` characters of ``text``, starting on a clean boundary.

    Handing the model half a word is worse than handing it less context, so the
    cut is moved forward to the start of a sentence — or of a word, when keeping
    whole sentences would leave almost nothing.
    """
    if len(text) <= budget:
        return text

    cut = text[-budget:]
    boundary = _SENTENCE_SPLIT.search(cut)
    if boundary is not None and len(cut) - boundary.end() >= budget // 4:
        return cut[boundary.end():]

    space = cut.find(" ")
    return cut[space + 1:] if space != -1 else cut


def _words(text: str) -> list[str]:
    """The words of ``text``, lowercased — punctuation and spacing dropped."""
    return [w.lower() for w in _WORD_RE.findall(text)]


def is_context_echo(text: str, context: str) -> bool:
    """True if the transcription only repeats the context it was primed with.

    Same failure as ``is_prompt_echo``, one step further: given little or no
    speech, Whisper continues its prompt instead of transcribing, and now the
    prompt carries the previous sentences. Left alone it would paste a sentence
    the user already said.

    Only fires when **everything** returned was already in the context and there
    is a decent run of it: repeating a five-word phrase word for word is the
    model reciting, while a short "sí, exacto" is a person agreeing twice.
    """
    words = _words(text)
    if len(words) < _ECHO_MIN_WORDS:
        return False
    # Padded so the match cannot start or end mid-word ("ana" inside "banana").
    return f" {' '.join(words)} " in f" {' '.join(_words(context))} "


def is_prompt_echo(text: str, terms: Iterable[str]) -> bool:
    """True if the transcription is just the biasing prompt echoed back.

    Given almost no speech to work with, Whisper tends to "continue" its
    ``initial_prompt`` and return the vocabulary list itself ("Anthropic,
    Kubernetes, Grafana"). That is never something the user dictated, so it is
    dropped.

    Deliberately conservative: it requires **every** word to be a dictionary term
    and at least two distinct terms, so a legitimate one-word dictation
    ("Grafana") is never thrown away.
    """
    words = _words(text)
    if not words:
        return False

    # The model sometimes repeats the prompt's preamble too, translated or not.
    with_preamble = words[0] in _PROMPT_PREAMBLE
    if with_preamble:
        words = words[1:]
        if not words:
            return True

    term_words = {w.lower() for t in terms for w in _WORD_RE.findall(t)}
    if not term_words or not all(w in term_words for w in words):
        return False
    # "Vocabulary: Grafana" can only be the prompt; a bare "Grafana" cannot.
    return with_preamble or len(set(words)) >= 2


def collapse_repeats(text: str, *, min_repeats: int = 3, min_length: int = 12) -> str:
    """Collapse a sentence repeated back to back down to a single copy.

    When Whisper loses the thread — usually on trailing silence or noise — it can
    latch onto a phrase and emit it over and over to the end of the recording.
    Decoding each window independently makes that far rarer, but it cannot be ruled
    out, and the OpenAI backend offers no such knob at all, so the text is checked
    here too.

    The loop is not always a single sentence: the model also gets stuck
    alternating two or three of them, so cycles up to ``_MAX_CYCLE`` sentences long
    are recognised and reduced to one turn of the cycle.

    Conservative on purpose: a cycle must repeat ``min_repeats`` times and carry at
    least ``min_length`` characters. Someone dictating "no, no, no" keeps every no.
    """
    if not text:
        return text

    parts = _SENTENCE_SPLIT.split(text)
    if len(parts) < min_repeats:
        return text

    keys = [p.strip().lower() for p in parts]

    def _repeats_of(start: int, size: int) -> int:
        """How many times the block of ``size`` sentences at ``start`` repeats."""
        cycle = keys[start:start + size]
        count = 1
        nxt = start + size
        while keys[nxt:nxt + size] == cycle:
            count += 1
            nxt += size
        return count

    out: list[str] = []
    i = 0
    while i < len(parts):
        best_size, best_repeats = 1, 1
        for size in range(1, _MAX_CYCLE + 1):
            if i + size * min_repeats > len(parts):
                break
            repeats = _repeats_of(i, size)
            block_length = sum(len(k) for k in keys[i:i + size])
            if (repeats >= min_repeats and block_length >= min_length
                    and size * repeats > best_size * best_repeats):
                best_size, best_repeats = size, repeats

        if best_repeats >= min_repeats:
            out.extend(parts[i:i + best_size])          # keep one turn of the cycle
            i += best_size * best_repeats
        else:
            out.append(parts[i])
            i += 1

    collapsed = " ".join(out)
    if collapsed != text:
        log.info("Collapsed a repeated phrase (%d chars -> %d).", len(text), len(collapsed))
    return collapsed


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

    Catches the spellings Whisper invents for a name it does not know
    ("iberdrolla", "antropic"). Requires ``rapidfuzz``; without it the text is
    returned unchanged.

    Only words and terms of at least ``_FUZZY_MIN_LEN`` characters take part: on
    short words the similarity score is noise ("mano" scores 86 against "Ana"),
    and rewriting an ordinary word into a client's name is far worse than leaving
    a name misspelled.
    """
    term_list = [t.strip() for t in terms if t and t.strip() and len(t.strip()) >= _FUZZY_MIN_LEN]
    if not term_list or not text:
        return text
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return text

    def _replace(m: re.Match[str]) -> str:
        word = m.group(0)
        if len(word) < _FUZZY_MIN_LEN:
            return word
        # A word that already is the term scores 100 and comes back in the
        # canonical spelling, which also fixes case and accents ("telefonica").
        # Compare case-insensitively: a term's leading capital costs ~10 points
        # of ratio on its own, which is enough to miss every real variant.
        match = process.extractOne(word, term_list, scorer=fuzz.ratio, processor=str.lower)
        if match and match[1] >= threshold:
            return _match_case(word, match[0])
        return word

    return _WORD_RE.sub(_replace, text)


__all__ = [
    "build_prompt",
    "with_context",
    "is_prompt_echo",
    "is_context_echo",
    "collapse_repeats",
    "apply",
    "apply_fuzzy",
]
