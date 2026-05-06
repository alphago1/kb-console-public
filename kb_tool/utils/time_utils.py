from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from dateutil import parser as date_parser


@dataclass(frozen=True)
class DerivedTime:
    derived_time_month: Optional[str]
    time_source: Optional[str]


_FILENAME_DATE_PATTERNS = [
    # 2026-04-22, 20250423
    re.compile(r"(?P<y>20\d{2})[-_/]?(?P<m>0[1-9]|1[0-2])[-_/]?(?P<d>0[1-9]|[12]\d|3[01])"),
    re.compile(r"(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])"),  # like 0424 in filename (year missing)
]


def _to_month(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def derive_time_month(
    filename: str,
    filesystem_created_time: Optional[datetime],
    filesystem_modified_time: Optional[datetime],
    document_created_time: Optional[datetime],
    document_modified_time: Optional[datetime],
) -> DerivedTime:
    if document_created_time:
        return DerivedTime(_to_month(document_created_time), "document_created_time")
    if document_modified_time:
        return DerivedTime(_to_month(document_modified_time), "document_modified_time")

    # filename date
    for pat in _FILENAME_DATE_PATTERNS:
        m = pat.search(filename)
        if not m:
            continue
        try:
            if "y" in m.groupdict() and m.group("y"):
                y = int(m.group("y"))
                mo = int(m.group("m"))
                # day optional
                d = int(m.groupdict().get("d") or 1)
                return DerivedTime(f"{y:04d}-{mo:02d}", "filename_date")
            # pattern without year: fallback to filesystem year if present
            if filesystem_created_time:
                y = filesystem_created_time.year
                mo = int(m.group("m"))
                return DerivedTime(f"{y:04d}-{mo:02d}", "filename_date")
        except Exception:
            pass

    if filesystem_created_time:
        return DerivedTime(_to_month(filesystem_created_time), "filesystem_created_time")
    if filesystem_modified_time:
        return DerivedTime(_to_month(filesystem_modified_time), "filesystem_modified_time")
    return DerivedTime(None, None)


def try_parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return date_parser.parse(value)
    except Exception:
        return None
