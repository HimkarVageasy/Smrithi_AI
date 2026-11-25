"""Workforce Identity Federation (WIF) normalization and gateway identity extraction."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import HTTPException, status

_IAP_EMAIL_PREFIX = "accounts.google.com:"

_IDENTITY_HEADER_CANDIDATES: tuple[str, ...] = (
    "x-smriti-wif-principal",
    "x-goog-authenticated-user-email",
    "x-goog-iap-jwt-assertion-sub",
)


def canonicalize_wif_principal(raw_principal: str) -> str:
    """Normalize Workforce Identity principals via .strip().lower() to prevent case bugs."""
    cleaned = raw_principal.strip()
    if cleaned.lower().startswith(_IAP_EMAIL_PREFIX):
        cleaned = cleaned[len(_IAP_EMAIL_PREFIX) :].strip()
    normalized = cleaned.lower()
    if not normalized:
        raise ValueError("Workforce Identity principal cannot be empty.")
    return normalized


def extract_caller_principal(
    headers: Mapping[str, str],
    *,
    require_auth: bool = False,
) -> str:
    """Extract and normalize caller WIF principal from gateway request headers."""
    lowered_headers = {k.lower(): v for k, v in headers.items()}
    for header_name in _IDENTITY_HEADER_CANDIDATES:
        raw_value = lowered_headers.get(header_name)
        if raw_value and raw_value.strip():
            return canonicalize_wif_principal(raw_value)

    if require_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Workforce Identity principal header.",
        )

    return "local-dev@unauthenticated"
