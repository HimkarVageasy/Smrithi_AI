"""Workforce Identity Federation (WIF) normalization and gateway identity extraction."""

from __future__ import annotations

import base64
import json
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


def _extract_cloud_run_verified_bearer_principal(auth_header: str) -> str | None:
    """Read email/sub from an OIDC Bearer token already verified at Cloud Run IAM ingress."""
    parts = auth_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    segments = parts[1].strip().split(".")
    if len(segments) != 3:
        return None

    payload_b64 = segments[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
        claims = json.loads(decoded_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(claims, dict):
        return None

    for claim_key in ("email", "sub"):
        claim_val = claims.get(claim_key)
        if isinstance(claim_val, str) and claim_val.strip():
            return canonicalize_wif_principal(claim_val)
    return None


def extract_caller_principal(
    headers: Mapping[str, str],
    *,
    require_auth: bool = False,
    trust_cloud_run_iam_bearer: bool = False,
) -> str:
    """Extract and normalize caller WIF principal from gateway request headers."""
    lowered_headers = {k.lower(): v for k, v in headers.items()}
    for header_name in _IDENTITY_HEADER_CANDIDATES:
        raw_value = lowered_headers.get(header_name)
        if raw_value and raw_value.strip():
            return canonicalize_wif_principal(raw_value)

    if trust_cloud_run_iam_bearer:
        for bearer_header in ("authorization", "x-serverless-authorization"):
            auth_header = lowered_headers.get(bearer_header)
            if auth_header:
                bearer_principal = _extract_cloud_run_verified_bearer_principal(auth_header)
                if bearer_principal:
                    return bearer_principal

    if require_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Workforce Identity principal header.",
        )

    return "local-dev@unauthenticated"
