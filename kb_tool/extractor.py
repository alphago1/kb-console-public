from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

from docx import Document


def _read_text_file(path: str) -> str:
    encodings = ["utf-8-sig", "utf-8", "utf-16", "gbk", "cp936", "latin-1"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read()
        except Exception:
            continue
    # last resort
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def extract_docx(path: str) -> tuple[str, Optional[datetime], Optional[datetime]]:
    doc = Document(path)
    parts: list[str] = []
    for p in doc.paragraphs:
        txt = (p.text or "").strip()
        if txt:
            parts.append(txt)
    created = doc.core_properties.created
    modified = doc.core_properties.modified
    return "\n".join(parts), created, modified


def convert_doc_to_docx(soffice_path: str, doc_path: str, out_dir: str) -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    cmd = [
        soffice_path,
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--convert-to",
        "docx",
        "--outdir",
        out_dir,
        doc_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"LibreOffice convert failed: {proc.stderr or proc.stdout}")

    out_name = Path(doc_path).with_suffix(".docx").name
    out_path = str(Path(out_dir) / out_name)
    if not os.path.exists(out_path):
        raise FileNotFoundError(f"converted file not found: {out_path}")
    return out_path


def extract_text(
    cfg: dict, path: str, extension: str
) -> Tuple[Optional[str], Optional[datetime], Optional[datetime], Optional[str]]:
    """Return (text, document_created_time, document_modified_time, error)."""
    try:
        if extension in {".md", ".txt"}:
            return _read_text_file(path), None, None, None
        if extension == ".docx":
            text, created, modified = extract_docx(path)
            return text, created, modified, None
        if extension == ".doc":
            soffice = cfg["extractor"].get("libreoffice_soffice_path")
            if not soffice or not os.path.exists(soffice):
                return None, None, None, "LibreOffice soffice.exe 未配置或不存在"
            tmp = cfg["extractor"].get("temp_dir", "./kb_out/tmp")
            converted = convert_doc_to_docx(soffice, path, tmp)
            text, created, modified = extract_docx(converted)
            return text, created, modified, None
        return None, None, None, "不支持的扩展名"
    except Exception as e:
        logging.exception("extract failed: %s", path)
        return None, None, None, str(e)
