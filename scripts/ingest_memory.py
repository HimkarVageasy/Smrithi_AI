"""CLI helper to upload official BRDs, post-mortems, or Excel rulesets to Smriti Memory."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a PDF/DOCX/MD/XLSX/CSV file into domain-isolated Smriti Memory."
    )
    parser.add_argument(
        "--domain", required=True, help="Target domain_id (e.g. performance_marketing)"
    )
    parser.add_argument("--file", required=True, help="Path to local document or spreadsheet")
    parser.add_argument(
        "--url",
        default="http://localhost:8080/v1/memory/ingest",
        help="Smriti /v1/memory/ingest endpoint URL",
    )
    parser.add_argument("--token", default="", help="Optional Cloud Run IAM OIDC Bearer token")
    parser.add_argument("--tags", default="", help="Comma-separated entity tags")
    args = parser.parse_args()

    file_path = Path(args.file).expanduser().resolve()
    raw_bytes = file_path.read_bytes()
    payload = {
        "domain_id": args.domain.strip().lower(),
        "filename": file_path.name,
        "content_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "entity_tags": [t.strip() for t in args.tags.split(",") if t.strip()],
        "trust_tier": "OFFICIAL_DOC",
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if args.token.strip():
        headers["Authorization"] = f"Bearer {args.token.strip()}"

    resp = httpx.post(args.url, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()
