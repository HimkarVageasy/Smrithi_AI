"""Post-render PII regex scrubber, banned-word gate, and mandatory citation verifier."""

from __future__ import annotations

import re
from collections.abc import Set as AbstractSet

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_INDIAN_PHONE_RE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
_CITATION_TAG_RE = re.compile(r"\[Source:\s*[^\]·]+·[^\]]+\]")


class OutputGuardrailViolation(ValueError):
    """Raised when rendered output violates citation or prohibited-claim invariants."""


def scrub_pii_text(text: str, *, preserve_emails: AbstractSet[str] = frozenset()) -> str:
    """Redact emails and 10-digit Indian mobile numbers from outbound text."""
    allowed_lower = {e.strip().lower() for e in preserve_emails}

    def _replace_email(match: re.Match[str]) -> str:
        candidate = match.group(0)
        if candidate.lower() in allowed_lower:
            return candidate
        return "[REDACTED_EMAIL]"

    scrubbed = _EMAIL_RE.sub(_replace_email, text)
    scrubbed = _INDIAN_PHONE_RE.sub("[REDACTED_PHONE]", scrubbed)
    return scrubbed


def audit_rendered_markdown(
    markdown_text: str,
    *,
    banned_words: AbstractSet[str] = frozenset(),
    preserve_emails: AbstractSet[str] = frozenset(),
    require_inline_citation: bool = True,
) -> str:
    """Scrub PII, block prohibited causal/margin claims, and verify [Source: ... · ...] tags."""
    cleaned = scrub_pii_text(markdown_text, preserve_emails=preserve_emails)

    for word in banned_words:
        pattern = re.compile(rf"\b{re.escape(word.strip())}\b", re.IGNORECASE)
        if pattern.search(cleaned):
            raise OutputGuardrailViolation(
                f"Output contains prohibited causal/unverified word '{word}'."
            )

    if require_inline_citation and not _CITATION_TAG_RE.search(cleaned):
        raise OutputGuardrailViolation(
            "Output is missing mandatory inline '[Source: <Connector> · <Window>]' citation."
        )

    return cleaned
