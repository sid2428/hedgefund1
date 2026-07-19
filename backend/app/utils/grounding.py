"""Citation grounding — verify a model-supplied quote occurs in its source.

The model proposes, deterministic code verifies.

An LLM asked to extract facts will occasionally return a `source_text` that
reads plausibly but does not appear anywhere in the filing. Such a fact is
indistinguishable from a real one downstream: it carries a citation, a
confidence score, and a section name. The only way to catch it is to go back to
the source document and check.

This module does exactly that, and nothing else. It answers one question:
does this quote literally occur in this document?

Matching is deliberately strict about *content* and forgiving about
*formatting*. Filing text arrives via HTML stripping, so whitespace runs,
non-breaking spaces and typographic quotes are artefacts of the pipeline rather
than of the model, and normalising them away removes false rejections without
creating false acceptances. Everything else -- wording, numbers, names, order --
must match.
"""
from __future__ import annotations

from dataclasses import dataclass

# Typographic characters that HTML-stripped filing text and model output
# routinely disagree on. Mapping both sides through this table removes a large
# class of spurious rejections.
#
# Written as escape sequences rather than literal glyphs: several of these are
# visually indistinguishable from ASCII in an editor, so a re-encode of this
# file could silently weaken the check without failing a single test.
_CHAR_MAP: dict[str, str] = {
    # Single quotes / apostrophes.
    "‘": "'",  # left single quotation mark
    "’": "'",  # right single quotation mark (also used as apostrophe)
    "‚": "'",  # single low-9 quotation mark
    "‛": "'",  # single high-reversed-9 quotation mark
    "′": "'",  # prime
    # Double quotes.
    "“": '"',  # left double quotation mark
    "”": '"',  # right double quotation mark
    "„": '"',  # double low-9 quotation mark
    "‟": '"',  # double high-reversed-9 quotation mark
    "″": '"',  # double prime
    # Dashes and minus.
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
    "‒": "-",  # figure dash
    "–": "-",  # en dash
    "—": "-",  # em dash
    "―": "-",  # horizontal bar
    "−": "-",  # minus sign
    # Zero-width and formatting characters that str.isspace() does NOT catch.
    # These must be mapped explicitly or they silently break valid matches.
    "﻿": " ",  # zero-width no-break space / BOM
    "​": " ",  # zero-width space
    "‌": " ",  # zero-width non-joiner
    "‍": " ",  # zero-width joiner
    "­": " ",  # soft hyphen
    # Ellipsis -> the ASCII form, so the elision handling below sees it.
    "…": "...",
}

# A quote shorter than this is not evidence of anything -- short fragments occur
# by chance in any long document, so accepting them would make the check
# meaningless.
MIN_QUOTE_CHARS = 12

# Elision marker. Models frequently shorten a long passage as
# "revenue increased ... driven by demand". Each segment is then required to
# appear, in order, rather than treating the whole string as one literal.
_ELISION = "..."


def _fold_char(ch: str) -> str:
    """Lowercase a single character without changing its length.

    `str.lower()` can expand certain characters (e.g. U+0130), which would break
    the normalised-to-original offset mapping. Any character that does not fold
    to exactly one character is left as-is.
    """
    low = ch.lower()
    return low if len(low) == 1 else ch


def _normalise(text: str) -> tuple[str, list[int]]:
    """Normalise `text` and return it alongside an offset map.

    Returns `(normalised, offsets)` where `offsets[i]` is the index in the
    original `text` that produced `normalised[i]`. That map is what lets a match
    found in normalised space be reported as a span in the original document.

    Normalisation: map typographic characters to ASCII, collapse every run of
    whitespace to a single space, and lowercase.
    """
    chars: list[str] = []
    offsets: list[int] = []
    prev_was_space = False

    for i, ch in enumerate(text):
        mapped = _CHAR_MAP.get(ch, ch)

        # Single whitespace character: collapse runs to one space.
        if len(mapped) == 1 and mapped.isspace():
            if prev_was_space:
                continue
            chars.append(" ")
            offsets.append(i)
            prev_was_space = True
            continue

        prev_was_space = False
        # A mapping may expand (ellipsis -> "..."); every character it produces
        # points back at the same original index.
        for out_ch in mapped:
            chars.append(_fold_char(out_ch))
            offsets.append(i)

    return "".join(chars), offsets


@dataclass(frozen=True)
class GroundingResult:
    """Outcome of checking one quote against one source document."""

    verified: bool
    reason: str | None = None
    char_start: int | None = None
    char_end: int | None = None

    def __bool__(self) -> bool:
        return self.verified


class CitationGrounder:
    """Verifies quotes against a single source document.

    The source is normalised once at construction, so checking many facts
    against one filing costs a single pass over the document plus a substring
    search per fact.
    """

    __slots__ = ("_raw", "_norm", "_offsets")

    def __init__(self, source_text: str) -> None:
        self._raw = source_text or ""
        self._norm, self._offsets = _normalise(self._raw)

    def verify(self, quote: str) -> GroundingResult:
        """Check whether `quote` occurs in the source document.

        On success the returned span refers to offsets in the *original* source
        text, not the normalised form, so it can be used to re-read the passage
        from the stored document later.
        """
        if not quote or not quote.strip():
            return GroundingResult(False, "empty_quote")

        if not self._norm:
            return GroundingResult(False, "empty_source")

        normalised_quote, _ = _normalise(quote)
        normalised_quote = normalised_quote.strip()

        if len(normalised_quote) < MIN_QUOTE_CHARS:
            return GroundingResult(False, "quote_too_short")

        # Split on elision markers; every segment must appear, in order.
        segments = [s.strip() for s in normalised_quote.split(_ELISION)]
        segments = [s for s in segments if s]
        if not segments:
            return GroundingResult(False, "quote_too_short")

        cursor = 0
        first_start: int | None = None
        last_end: int | None = None

        for segment in segments:
            found = self._norm.find(segment, cursor)
            if found == -1:
                return GroundingResult(False, "not_found_in_source")
            if first_start is None:
                first_start = found
            last_end = found + len(segment)
            cursor = last_end

        if first_start is None or last_end is None:
            return GroundingResult(False, "not_found_in_source")

        return GroundingResult(
            verified=True,
            char_start=self._offsets[first_start],
            char_end=self._offsets[last_end - 1] + 1,
        )

    def excerpt(self, result: GroundingResult) -> str | None:
        """Return the original (un-normalised) text for a verified span."""
        if not result.verified or result.char_start is None or result.char_end is None:
            return None
        return self._raw[result.char_start : result.char_end]
