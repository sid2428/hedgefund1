"""Filing preprocessing: HTML cleaning + section splitting + chunking.

10-K / 10-Q filings have a stable Item-numbered structure. We split on the
Item headings using regex anchors that tolerate the wide stylistic variation
seen across filers (e.g., "ITEM 1A", "Item 1A.", "ITEM 1A. RISK FACTORS").
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.utils.chunker import smart_chunk

# (item_key, display_name, anchor regex). Order matters: must match the
# canonical SEC ordering so each section's text ends where the next begins.
SECTION_PATTERNS_10K: list[tuple[str, str, re.Pattern[str]]] = [
    ("Item 1", "Item 1 Business", re.compile(r"item\s*1[\.\s]+business", re.I)),
    ("Item 1A", "Item 1A Risk Factors", re.compile(r"item\s*1a[\.\s]+risk\s+factors", re.I)),
    (
        "Item 1B",
        "Item 1B Unresolved Staff Comments",
        re.compile(r"item\s*1b[\.\s]+unresolved\s+staff", re.I),
    ),
    ("Item 2", "Item 2 Properties", re.compile(r"item\s*2[\.\s]+properties", re.I)),
    ("Item 3", "Item 3 Legal Proceedings", re.compile(r"item\s*3[\.\s]+legal\s+proceedings", re.I)),
    (
        "Item 7",
        "Item 7 MD&A",
        re.compile(r"item\s*7[\.\s]+management.{0,40}discussion", re.I | re.S),
    ),
    (
        "Item 7A",
        "Item 7A Quantitative Disclosures",
        re.compile(r"item\s*7a[\.\s]+quantitative", re.I),
    ),
    (
        "Item 8",
        "Item 8 Financial Statements",
        re.compile(r"item\s*8[\.\s]+financial\s+statements", re.I),
    ),
    ("Item 9", "Item 9 Changes/Disagreements", re.compile(r"item\s*9[\.\s]+changes", re.I)),
    ("Item 9A", "Item 9A Controls", re.compile(r"item\s*9a[\.\s]+controls", re.I)),
]

SECTION_PATTERNS_10Q: list[tuple[str, str, re.Pattern[str]]] = [
    ("Part I", "Part I Financial Information", re.compile(r"part\s+i[\s\.]+financial", re.I)),
    ("Item 1", "Item 1 Financial Statements", re.compile(r"item\s*1[\.\s]+financial", re.I)),
    (
        "Item 2",
        "Item 2 MD&A",
        re.compile(r"item\s*2[\.\s]+management.{0,40}discussion", re.I | re.S),
    ),
    (
        "Item 3",
        "Item 3 Quantitative Disclosures",
        re.compile(r"item\s*3[\.\s]+quantitative", re.I),
    ),
    ("Item 4", "Item 4 Controls", re.compile(r"item\s*4[\.\s]+controls", re.I)),
    ("Part II", "Part II Other Information", re.compile(r"part\s+ii[\s\.]+other", re.I)),
    ("Item 1A", "Item 1A Risk Factors", re.compile(r"item\s*1a[\.\s]+risk\s+factors", re.I)),
]

SECTION_NAMES_10K: list[str] = [name for _, name, _ in SECTION_PATTERNS_10K]
SECTION_NAMES_10Q: list[str] = [name for _, name, _ in SECTION_PATTERNS_10Q]


@dataclass
class FilingSection:
    name: str
    text: str
    char_count: int


def clean_text(raw: str) -> str:
    """Normalize whitespace and remove non-breaking spaces / artifacts."""
    if not raw:
        return ""
    text = raw.replace(" ", " ").replace("​", "")
    # Collapse runs of spaces/tabs but preserve newlines for paragraph structure.
    text = re.sub(r"[ \t]+", " ", text)
    # Drop SEC-style table-of-contents page numbers like "  3 ".
    text = re.sub(r"\n\s*\d{1,3}\s*\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_by_sections(
    text: str, filing_type: str = "10-K"
) -> dict[str, str]:
    """Return a dict of section_name -> section_text.

    Falls back to {"FULL": text} when no sections are matched (common in 8-Ks).
    """
    text = clean_text(text)
    if not text:
        return {}

    patterns = (
        SECTION_PATTERNS_10K if filing_type.upper() == "10-K" else SECTION_PATTERNS_10Q
    )

    matches: list[tuple[str, str, int]] = []
    for key, name, pat in patterns:
        m = pat.search(text)
        if m:
            matches.append((key, name, m.start()))
    matches.sort(key=lambda t: t[2])

    if not matches:
        return {"FULL": text}

    sections: dict[str, str] = {}
    for i, (_key, name, start) in enumerate(matches):
        end = matches[i + 1][2] if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Skip extremely short matches (table of contents).
        if len(body) >= 200:
            sections[name] = body

    if not sections:
        return {"FULL": text}
    return sections


def chunk_section(
    section_text: str, max_tokens: int = 6000, overlap_tokens: int = 200
) -> list[str]:
    """Token-bound chunks for a single section."""
    return smart_chunk(section_text, max_tokens=max_tokens, overlap_tokens=overlap_tokens)


def preprocess_filing(
    raw_text: str,
    filing_type: str = "10-K",
    max_tokens: int = 6000,
) -> list[FilingSection]:
    """One-shot: clean -> split into sections -> emit `FilingSection` per chunk.

    Each entry preserves the section name so downstream agents know which
    Item the chunk came from (useful for `source_section` on extracted facts).
    """
    sections = split_by_sections(raw_text, filing_type=filing_type)
    out: list[FilingSection] = []
    for name, body in sections.items():
        for chunk in chunk_section(body, max_tokens=max_tokens):
            out.append(FilingSection(name=name, text=chunk, char_count=len(chunk)))
    return out
