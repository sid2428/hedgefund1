"""Unit tests for citation grounding.

The grounder has one job: decide whether a quote occurs in a document. It must
be strict about content (so fabricated citations are caught) and forgiving about
formatting (so HTML-stripping artefacts do not cause false rejections).
"""
from __future__ import annotations

import pytest

from app.utils.grounding import MIN_QUOTE_CHARS, CitationGrounder

SOURCE = """
Item 1A. Risk Factors

We depend on a limited number of customers. In fiscal 2024, our largest
customer, Apple Inc., represented approximately 22% of revenue — a
concentration that exposes us to their purchasing decisions.

We expect demand to remain volatile through the first quarter.
"""


# --- acceptance -------------------------------------------------------------


def test_exact_quote_is_verified():
    g = CitationGrounder(SOURCE)
    result = g.verify("We expect demand to remain volatile through the first quarter.")
    assert result.verified
    assert result.reason is None


def test_verified_span_points_at_original_text():
    g = CitationGrounder(SOURCE)
    quote = "We expect demand to remain volatile"
    result = g.verify(quote)
    assert result.verified
    excerpt = g.excerpt(result)
    assert excerpt is not None
    assert "volatile" in excerpt


def test_quote_spanning_a_line_break_is_verified():
    """Line wrapping is an artefact of the source document, not the model."""
    g = CitationGrounder(SOURCE)
    result = g.verify("our largest customer, Apple Inc., represented approximately 22%")
    assert result.verified


def test_collapsed_whitespace_is_tolerated():
    g = CitationGrounder(SOURCE)
    result = g.verify("We   expect  demand\n\n to remain volatile")
    assert result.verified


def test_typographic_characters_are_normalised():
    """Smart quotes and em dashes differ between the filing and model output."""
    g = CitationGrounder("The company's outlook — as described above — remains stable.")
    assert g.verify("The company's outlook - as described above - remains stable.").verified


def test_case_differences_are_tolerated():
    g = CitationGrounder(SOURCE)
    assert g.verify("WE EXPECT DEMAND TO REMAIN VOLATILE").verified


def test_elided_quote_requires_all_segments_in_order():
    g = CitationGrounder(SOURCE)
    assert g.verify("our largest customer ... represented approximately 22%").verified


# --- rejection --------------------------------------------------------------


def test_fabricated_quote_is_rejected():
    """The central guarantee. A plausible sentence that is not in the document."""
    g = CitationGrounder(SOURCE)
    result = g.verify(
        "our largest customer, Microsoft Corporation, represented approximately 31% of revenue"
    )
    assert not result.verified
    assert result.reason == "not_found_in_source"


def test_altered_number_is_rejected():
    """Changing a single digit must not pass. This is the realistic failure mode."""
    g = CitationGrounder(SOURCE)
    result = g.verify(
        "our largest customer, Apple Inc., represented approximately 82% of revenue"
    )
    assert not result.verified


def test_altered_entity_is_rejected():
    g = CitationGrounder(SOURCE)
    assert not g.verify("our largest customer, Apple Computer, represented approximately").verified


def test_elided_segments_out_of_order_are_rejected():
    g = CitationGrounder(SOURCE)
    result = g.verify("represented approximately 22% ... our largest customer")
    assert not result.verified


def test_empty_quote_is_rejected():
    g = CitationGrounder(SOURCE)
    assert g.verify("").reason == "empty_quote"
    assert g.verify("   ").reason == "empty_quote"


def test_empty_source_rejects_everything():
    g = CitationGrounder("")
    assert g.verify("any quote at all here").reason == "empty_source"


@pytest.mark.parametrize("quote", ["risk", "Apple", "22%", "customers"])
def test_short_fragments_are_rejected(quote):
    """Short strings occur by chance and are not evidence of anything."""
    g = CitationGrounder(SOURCE)
    result = g.verify(quote)
    assert not result.verified
    assert result.reason == "quote_too_short"
    assert len(quote) < MIN_QUOTE_CHARS


def test_result_is_falsy_when_unverified():
    g = CitationGrounder(SOURCE)
    assert not g.verify("not present in the document at all")
    assert g.verify("We expect demand to remain volatile")


def test_excerpt_returns_none_for_unverified_result():
    g = CitationGrounder(SOURCE)
    assert g.excerpt(g.verify("nowhere to be found in this text")) is None
