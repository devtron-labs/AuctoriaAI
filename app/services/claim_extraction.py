"""
EPIC 5 — Claim extraction utilities.

Extracts structured claims from draft markdown using compiled regex patterns.
No LLM calls are made; all extraction is deterministic and pure-Python.

All regex patterns are compiled once at import time for performance.
"""

import re
from typing import List

from app.schemas.schemas import ExtractedClaim, ExtractedClaimType


# ---------------------------------------------------------------------------
# Compiled regex patterns (module-level for performance)
# ---------------------------------------------------------------------------

# Matches: "integrates with X", "integration with X", "connects to X", "works with X"
# Captures: system name (1–2 words).
# The capture group uses (?-i:...) to disable IGNORECASE locally so that the
# optional second word must start with an uppercase letter — this prevents
# capturing trailing common words like "and", "for", "databases", "payments".
_INTEGRATION_RE = re.compile(
    r'\b(?:integrates?\s+with|integration\s+with|connects?\s+to|works?\s+with)\s+'
    r'(?-i:([A-Za-z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)?))',
    re.IGNORECASE,
)

# Matches compliance standard names (case-insensitive)
_COMPLIANCE_RE = re.compile(
    r'\b(SOC\s*2|ISO\s*27001|GDPR|HIPAA|PCI\s*DSS|CCPA|FedRAMP)\b',
    re.IGNORECASE,
)

# Matches numeric performance metrics followed by a unit.
# Supports optional comma-separators in numbers (e.g. 10,000).
# Uses (?!\w) instead of \b at the end because % is a non-word character and
# \b does not form a boundary between two non-word characters (e.g. "%" + " ").
_PERFORMANCE_RE = re.compile(
    r'\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)'
    r'\s*(%|ms|seconds?|MB|GB|requests?/sec)(?!\w)',
    re.IGNORECASE,
)

# Matches superlative marketing words
_SUPERLATIVE_RE = re.compile(
    r'\b(best|fastest|most|leading|industry-leading|top|premier)\b',
    re.IGNORECASE,
)

# Used to split markdown into paragraphs
_PARA_SPLIT_RE = re.compile(r'\n\n+')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_paragraphs(markdown: str) -> list[str]:
    """Split markdown into paragraph chunks on blank lines."""
    return _PARA_SPLIT_RE.split(markdown.strip())


def _line_number_in_para(para: str, match_start: int) -> int:
    """Return the 1-indexed line number of a match within a paragraph."""
    return para[:match_start].count('\n') + 1


# ---------------------------------------------------------------------------
# Public extraction functions
# ---------------------------------------------------------------------------

def extract_integration_claims(markdown: str) -> List[ExtractedClaim]:
    """
    Extract integration claims from markdown.

    Patterns matched: "integrates with X", "integration with X",
    "connects to X", "works with X".

    Args:
        markdown: Raw markdown string from a DraftVersion.

    Returns:
        List of ExtractedClaim instances with claim_type=INTEGRATION.
    """
    claims: list[ExtractedClaim] = []
    for para_idx, para in enumerate(_split_paragraphs(markdown)):
        for match in _INTEGRATION_RE.finditer(para):
            system_name = match.group(1).strip()
            line_num = _line_number_in_para(para, match.start())
            claims.append(ExtractedClaim(
                claim_type=ExtractedClaimType.INTEGRATION,
                claim_text=system_name,
                location_in_draft=f"paragraph {para_idx + 1}, line {line_num}",
            ))
    return claims


def extract_compliance_claims(markdown: str) -> List[ExtractedClaim]:
    """
    Extract compliance standard claims from markdown.

    Standards detected (case-insensitive): SOC 2, ISO 27001, GDPR, HIPAA,
    PCI DSS, CCPA, FedRAMP.

    Args:
        markdown: Raw markdown string from a DraftVersion.

    Returns:
        List of ExtractedClaim instances with claim_type=COMPLIANCE.
    """
    claims: list[ExtractedClaim] = []
    for para_idx, para in enumerate(_split_paragraphs(markdown)):
        for match in _COMPLIANCE_RE.finditer(para):
            standard = match.group(1).strip()
            line_num = _line_number_in_para(para, match.start())
            claims.append(ExtractedClaim(
                claim_type=ExtractedClaimType.COMPLIANCE,
                claim_text=standard,
                location_in_draft=f"paragraph {para_idx + 1}, line {line_num}",
            ))
    return claims


def extract_performance_claims(markdown: str) -> List[ExtractedClaim]:
    """
    Extract performance metric claims from markdown.

    Matches numbers followed by a unit: %, ms, seconds, MB, GB, requests/sec.
    Examples: "99.9%", "50ms", "5 seconds", "10,000 requests/sec".

    The claim_text is stored as "{value}{unit}" (e.g. "99.9%", "50ms").

    Args:
        markdown: Raw markdown string from a DraftVersion.

    Returns:
        List of ExtractedClaim instances with claim_type=PERFORMANCE.
    """
    claims: list[ExtractedClaim] = []
    for para_idx, para in enumerate(_split_paragraphs(markdown)):
        for match in _PERFORMANCE_RE.finditer(para):
            # Normalise: strip commas from number, lowercase unit
            value = match.group(1).replace(',', '')
            unit = match.group(2).lower()
            # Normalise unit aliases ("seconds" → "seconds", keep as-is)
            metric_text = f"{value}{unit}"
            line_num = _line_number_in_para(para, match.start())
            claims.append(ExtractedClaim(
                claim_type=ExtractedClaimType.PERFORMANCE,
                claim_text=metric_text,
                location_in_draft=f"paragraph {para_idx + 1}, line {line_num}",
            ))
    return claims


def extract_superlatives(markdown: str) -> List[ExtractedClaim]:
    """
    Extract superlative marketing words from markdown.

    Words matched (case-insensitive): best, fastest, most, leading,
    industry-leading, top, premier.

    The claim_text is stored as the lowercased matched word.

    Args:
        markdown: Raw markdown string from a DraftVersion.

    Returns:
        List of ExtractedClaim instances with claim_type=SUPERLATIVE.
    """
    claims: list[ExtractedClaim] = []
    for para_idx, para in enumerate(_split_paragraphs(markdown)):
        for match in _SUPERLATIVE_RE.finditer(para):
            word = match.group(1).lower()
            line_num = _line_number_in_para(para, match.start())
            claims.append(ExtractedClaim(
                claim_type=ExtractedClaimType.SUPERLATIVE,
                claim_text=word,
                location_in_draft=f"paragraph {para_idx + 1}, line {line_num}",
            ))
    return claims


def extract_all_claims(markdown: str) -> List[ExtractedClaim]:
    """
    Extract all claim types from a draft in a single pass.

    Runs all four extractors and returns the combined list in order:
    integration → compliance → performance → superlatives.

    Args:
        markdown: Raw markdown string from a DraftVersion.

    Returns:
        Combined list of all ExtractedClaim instances. Empty list for blank
        or claim-free content.
    """
    if not markdown or not markdown.strip():
        return []
    return (
        extract_integration_claims(markdown)
        + extract_compliance_claims(markdown)
        + extract_performance_claims(markdown)
        + extract_superlatives(markdown)
    )
