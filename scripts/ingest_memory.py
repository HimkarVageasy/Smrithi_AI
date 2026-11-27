"""CLI uploader to ingest single files (`--file`) or entire folders (`--dir`) into Smriti Memory."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import httpx

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt", ".xlsx", ".csv"}


def _ingest_one(
    file_path: Path,
    *,
    domain_id: str,
    endpoint_url: str,
    headers: dict[str, str],
    tags: list[str],
) -> dict[str, object]:
    raw_bytes = file_path.read_bytes()
    payload = {
        "domain_id": domain_id,
        "filename": file_path.name,
        "content_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "entity_tags": tags,
        "trust_tier": "OFFICIAL_DOC",
    }
    resp = httpx.post(endpoint_url, json=payload, headers=headers, timeout=45.0)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest PDF/DOCX/MD/XLSX/CSV files or folders into Smriti Memory."
    )
    parser.add_argument(
        "--domain", required=True, help="Target domain_id (e.g. performance_marketing)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="Path to a single document or spreadsheet")
    group.add_argument("--dir", help="Folder of BRDs, post-mortems, and Excel rulesets")
    parser.add_argument(
        "--url",
        default="http://localhost:8080/v1/memory/ingest",
        help="Smriti /v1/memory/ingest endpoint URL",
    )
    parser.add_argument("--token", default="", help="Cloud Run IAM OIDC Bearer token")
    parser.add_argument("--tags", default="", help="Optional comma-separated entity tags")
    args = parser.parse_args()

    domain_id = args.domain.strip().lower()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if args.token.strip():
        headers["Authorization"] = f"Bearer {args.token.strip()}"

    targets: list[Path] = []
    if args.file:
        targets.append(Path(args.file).expanduser().resolve())
    else:
        folder = Path(args.dir).expanduser().resolve()
        targets.extend(
            sorted(
                p
                for p in folder.rglob("*")
                if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        )

    results = [
        _ingest_one(fp, domain_id=domain_id, endpoint_url=args.url, headers=headers, tags=tags)
        for fp in targets
    ]
    print(json.dumps({"files_ingested": len(results), "results": results}, indent=2))


if __name__ == "__main__":
    main()
