"""Unit tests for Workforce Identity Federation (WIF) normalization (`core/auth.py`)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from core.auth import canonicalize_wif_principal, extract_caller_principal


@pytest.mark.parametrize(
    ("raw_input", "expected"),
    [
        ("Himkar.V.Ageasy@AntaraSeniorCare.com", "himkar.v.ageasy@antaraseniorcare.com"),
        ("  HIMKAR.V@AGEASY.COM  ", "himkar.v@ageasy.com"),
        (
            "accounts.google.com:Himkar.V@AntaraSeniorCare.com",
            "himkar.v@antaraseniorcare.com",
        ),
        (
            "principal://iam.googleapis.com/locations/global/workforcePools/ge-pilot-wif/subject/Himkar.V",
            "principal://iam.googleapis.com/locations/global/workforcepools/ge-pilot-wif/subject/himkar.v",
        ),
    ],
)
def test_canonicalize_wif_principal_normalizes_case_and_whitespace(
    raw_input: str,
    expected: str,
) -> None:
    assert canonicalize_wif_principal(raw_input) == expected


@pytest.mark.parametrize("blank_value", ["", "   ", "accounts.google.com:   "])
def test_canonicalize_wif_principal_rejects_empty_values(blank_value: str) -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        canonicalize_wif_principal(blank_value)


def test_extract_caller_principal_prefers_wif_header_and_normalizes() -> None:
    headers = {
        "X-Goog-Authenticated-User-Email": "accounts.google.com:Fallback.User@Ageasy.com",
        "X-Smriti-Wif-Principal": "  Primary.User@Ageasy.com ",
    }
    assert extract_caller_principal(headers, require_auth=True) == "primary.user@ageasy.com"


def test_extract_caller_principal_raises_401_when_required_and_missing() -> None:
    with pytest.raises(HTTPException) as exc_info:
        extract_caller_principal({}, require_auth=True)
    assert exc_info.value.status_code == 401


def test_extract_caller_principal_uses_local_dev_fallback_when_not_required() -> None:
    assert extract_caller_principal({}, require_auth=False) == "local-dev@unauthenticated"


def test_extract_caller_principal_reads_oidc_bearer_when_cloud_run_iam_trusted() -> None:
    import base64
    import json

    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"email": "Himkar.V.Ageasy@AntaraSeniorCare.com"}).encode()
        )
        .decode()
        .rstrip("=")
    )
    token = f"Bearer {header}.{payload}.sig"

    # Ignored when trust_cloud_run_iam_bearer=False
    with pytest.raises(HTTPException) as exc_info:
        extract_caller_principal(
            {"Authorization": token},
            require_auth=True,
            trust_cloud_run_iam_bearer=False,
        )
    assert exc_info.value.status_code == 401

    # Accepted and normalized when running behind Cloud Run IAM (trust_cloud_run_iam_bearer=True)
    resolved = extract_caller_principal(
        {"Authorization": token},
        require_auth=True,
        trust_cloud_run_iam_bearer=True,
    )
    assert resolved == "himkar.v.ageasy@antaraseniorcare.com"
