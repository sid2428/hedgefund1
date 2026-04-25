"""Token-aware text chunking for long SEC filings."""
from __future__ import annotations

import re

import tiktoken

_ENCODING_CACHE: dict[str, tiktoken.Encoding] = {}


def _get_encoding(name: str) -> tiktoken.Encoding:
    if name not in _ENCODING_CACHE:
        try:
            _ENCODING_CACHE[name] = tiktoken.get_encoding(name)
        except (ValueError, KeyError):
            _ENCODING_CACHE[name] = tiktoken.get_encoding("cl100k_base")
    return _ENCODING_CACHE[name]


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    """Return the number of tokens for `text` under the named encoding."""
    if not text:
        return 0
    enc = _get_encoding(encoding_name)
    return len(enc.encode(text))


def smart_chunk(
    text: str,
    max_tokens: int = 6000,
    overlap_tokens: int = 200,
    encoding_name: str = "cl100k_base",
) -> list[str]:
    """Split `text` into chunks that respect natural boundaries.

    Strategy: split on double newlines (paragraphs) first; if a single paragraph
    is larger than `max_tokens` we further split it on sentence boundaries.
    Adjacent chunks share `overlap_tokens` of trailing context for continuity.
    """
    if not text:
        return []

    enc = _get_encoding(encoding_name)
    total = len(enc.encode(text))
    if total <= max_tokens:
        return [text]

    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0

    def _flush() -> None:
        nonlocal buf, buf_tokens
        if buf:
            chunks.append("\n\n".join(buf).strip())
            buf, buf_tokens = [], 0

    for para in paragraphs:
        para_tokens = len(enc.encode(para))

        if para_tokens > max_tokens:
            _flush()
            # Sentence-level fallback for oversized paragraphs.
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sbuf: list[str] = []
            sbuf_tokens = 0
            for s in sentences:
                s_tok = len(enc.encode(s))
                if sbuf_tokens + s_tok > max_tokens and sbuf:
                    chunks.append(" ".join(sbuf).strip())
                    sbuf, sbuf_tokens = [], 0
                sbuf.append(s)
                sbuf_tokens += s_tok
            if sbuf:
                chunks.append(" ".join(sbuf).strip())
            continue

        if buf_tokens + para_tokens > max_tokens and buf:
            _flush()
        buf.append(para)
        buf_tokens += para_tokens

    _flush()

    # Apply overlap by prepending the tail of the previous chunk.
    if overlap_tokens > 0 and len(chunks) > 1:
        with_overlap: list[str] = [chunks[0]]
        for prev, curr in zip(chunks, chunks[1:]):
            tail = enc.decode(enc.encode(prev)[-overlap_tokens:])
            with_overlap.append(f"...{tail}\n\n{curr}")
        chunks = with_overlap

    return chunks
