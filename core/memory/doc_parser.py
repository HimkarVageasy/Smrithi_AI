"""Stateless pure-Python document & spreadsheet parser (`MD/TXT/CSV/XLSX/DOCX/PDF` -> L1/L2/L3)."""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from typing import Any

from core.guardrails.output_audit import scrub_pii_text
from core.memory.schemas import MemoryChunk, TrustTier, new_chunk_uuid

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_COL_LETTERS_RE = re.compile(r"^([A-Za-z]+)")


def _excel_col_index(cell_ref: str) -> int:
    match = _COL_LETTERS_RE.match(cell_ref.strip())
    if not match:
        return 0
    idx = 0
    for ch in match.group(1).upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(0, idx - 1)


def extract_spreadsheet_rows(filename: str, raw_bytes: bytes) -> list[dict[str, str]]:
    """Extract header-keyed row dicts from `.csv` or `.xlsx` bytes without temp files."""
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        return [
            {str(k).strip(): str(v or "").strip() for k, v in row.items() if k}
            for row in reader
        ]

    if lower_name.endswith(".xlsx"):
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in zf.namelist():
                ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                for si in ss_root.iter():
                    if si.tag.endswith("}si") or si.tag == "si":
                        parts = [
                            t.text or ""
                            for t in si.iter()
                            if t.tag.endswith("}t") or t.tag == "t"
                        ]
                        shared.append("".join(parts))

            sheet_names = sorted(
                n
                for n in zf.namelist()
                if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
            )
            if not sheet_names:
                return []
            ws_root = ET.fromstring(zf.read(sheet_names[0]))
            grid: list[list[str]] = []
            for row_el in ws_root.iter():
                if not (row_el.tag.endswith("}row") or row_el.tag == "row"):
                    continue
                cells: dict[int, str] = {}
                for c_el in row_el:
                    if not (c_el.tag.endswith("}c") or c_el.tag == "c"):
                        continue
                    col_i = _excel_col_index(c_el.attrib.get("r", "A1"))
                    c_type = c_el.attrib.get("t", "")
                    val_txt = ""
                    for child in c_el.iter():
                        if c_type == "inlineStr" and (child.tag.endswith("}t") or child.tag == "t"):
                            val_txt += child.text or ""
                        elif c_type != "inlineStr" and (
                            child.tag.endswith("}v") or child.tag == "v"
                        ):
                            raw_v = (child.text or "").strip()
                            if c_type == "s" and raw_v.isdigit() and int(raw_v) < len(shared):
                                val_txt = shared[int(raw_v)]
                            else:
                                val_txt = raw_v
                    cells[col_i] = val_txt.strip()
                if cells:
                    max_col = max(cells)
                    grid.append([cells.get(i, "") for i in range(max_col + 1)])

            if len(grid) < 2:
                return []
            headers = [h.strip() for h in grid[0]]
            out: list[dict[str, str]] = []
            for data_row in grid[1:]:
                if not any(data_row):
                    continue
                rec = {
                    headers[i]: (data_row[i] if i < len(data_row) else "")
                    for i in range(len(headers))
                    if headers[i]
                }
                out.append(rec)
            return out

    raise ValueError(f"Unsupported spreadsheet extension for '{filename}'.")


def _extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(io.BytesIO(raw_bytes))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    except ImportError:
        pass

    chunks: list[str] = []
    for stream_m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw_bytes, re.DOTALL):
        buf = stream_m.group(1)
        try:
            buf = zlib.decompress(buf)
        except zlib.error:
            pass
        decoded = buf.decode("latin-1", errors="ignore")
        for txt_m in re.finditer(r"\(([^()]{2,})\)", decoded):
            chunks.append(txt_m.group(1))
    if chunks:
        return " ".join(chunks)
    return raw_bytes.decode("utf-8", errors="ignore").strip()


def extract_document_text(filename: str, raw_bytes: bytes) -> str:
    """Extract clean plain text from `.md`, `.txt`, `.docx`, or `.pdf` bytes."""
    lower_name = filename.lower()
    if lower_name.endswith((".md", ".txt")):
        return raw_bytes.decode("utf-8-sig", errors="replace").strip()

    if lower_name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        paragraphs: list[str] = []
        for p_el in root.iter():
            if p_el.tag.endswith("}p") or p_el.tag == "p":
                runs = [
                    t.text or ""
                    for t in p_el.iter()
                    if t.tag.endswith("}t") or t.tag == "t"
                ]
                line = "".join(runs).strip()
                if line:
                    paragraphs.append(line)
        return "\n\n".join(paragraphs)

    if lower_name.endswith(".pdf"):
        return _extract_pdf_text(raw_bytes)

    raise ValueError(f"Unsupported document extension for '{filename}'.")


def chunk_document_hierarchy(
    *,
    domain_id: str,
    source_title: str,
    raw_text: str,
    entity_tags: list[str],
    caller_wif: str,
    created_at_iso: str,
    trust_tier: TrustTier = "OFFICIAL_DOC",
    gcs_uri: str | None = None,
    extra_metrics: dict[str, Any] | None = None,
) -> list[MemoryChunk]:
    """Decompose document text into PII-scrubbed L1 Summary -> L2 Section -> L3 Atomic chunks."""
    clean_full = scrub_pii_text(raw_text.strip())
    if not clean_full:
        return []

    root_id = new_chunk_uuid()
    sections: list[tuple[str, list[str]]] = []
    curr_title = "Overview"
    curr_lines: list[str] = []

    for raw_line in clean_full.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        h_match = _HEADING_RE.match(stripped)
        if h_match:
            if curr_lines:
                sections.append((curr_title, curr_lines))
                curr_lines = []
            curr_title = h_match.group(2).strip()[:64]
        else:
            curr_lines.append(stripped.lstrip("-*• ").strip())
    if curr_lines:
        sections.append((curr_title, curr_lines))

    summary_preview = " ".join(line for _, lines in sections for line in lines)[:600]
    out: list[MemoryChunk] = [
        MemoryChunk(
            chunk_uuid=root_id,
            parent_chunk_uuid=None,
            root_chunk_uuid=root_id,
            level=1,
            domain_id=domain_id,
            trust_tier=trust_tier,
            entity_tags=entity_tags,
            section_type="Summary",
            content_text=summary_preview or source_title,
            metrics_json=extra_metrics or {},
            source_title=source_title,
            gcs_uri=gcs_uri,
            created_by_wif=caller_wif,
            approved_by_wif=caller_wif,
            created_at_iso=created_at_iso,
        )
    ]

    for sec_title, items in sections[:12]:
        sec_id = new_chunk_uuid()
        sec_text = " ".join(items)[:1200]
        if len(sec_text) < 3:
            continue
        out.append(
            MemoryChunk(
                chunk_uuid=sec_id,
                parent_chunk_uuid=root_id,
                root_chunk_uuid=root_id,
                level=2,
                domain_id=domain_id,
                trust_tier=trust_tier,
                entity_tags=entity_tags,
                section_type=sec_title,
                content_text=sec_text,
                metrics_json={},
                source_title=source_title,
                gcs_uri=gcs_uri,
                created_by_wif=caller_wif,
                approved_by_wif=caller_wif,
                created_at_iso=created_at_iso,
            )
        )
        for fact in items[:15]:
            if len(fact) >= 8:
                out.append(
                    MemoryChunk(
                        chunk_uuid=new_chunk_uuid(),
                        parent_chunk_uuid=sec_id,
                        root_chunk_uuid=root_id,
                        level=3,
                        domain_id=domain_id,
                        trust_tier=trust_tier,
                        entity_tags=entity_tags,
                        section_type=sec_title,
                        content_text=fact[:1000],
                        metrics_json=extra_metrics or {},
                        source_title=source_title,
                        gcs_uri=gcs_uri,
                        created_by_wif=caller_wif,
                        approved_by_wif=caller_wif,
                        created_at_iso=created_at_iso,
                    )
                )
    return out
