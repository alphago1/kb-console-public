from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from models import FileRecord
from utils.path_utils import matches_any_glob, norm_abs


def _stat_times(path: str) -> tuple[Optional[datetime], Optional[datetime], int]:
    st = os.stat(path)
    ctime = datetime.fromtimestamp(st.st_ctime)
    mtime = datetime.fromtimestamp(st.st_mtime)
    return ctime, mtime, int(st.st_size)


def iter_files(root_dirs: list[str], exclude_dir_globs: list[str]) -> Iterable[str]:
    for root in root_dirs:
        root_abs = norm_abs(root)
        for dirpath, dirnames, filenames in os.walk(root_abs):
            # prune excluded dirs
            pruned = []
            for d in list(dirnames):
                full = os.path.join(dirpath, d)
                if matches_any_glob(full, exclude_dir_globs):
                    pruned.append(d)
            for d in pruned:
                dirnames.remove(d)

            for name in filenames:
                yield os.path.join(dirpath, name)


def scan_files(cfg: dict, db, run_id: str, dry_run: bool, max_files: Optional[int] = None) -> dict:
    sc = cfg["scanner"]
    include_exts = {e.lower() for e in sc.get("include_extensions", [])}
    exclude_file_globs = sc.get("exclude_file_globs", [])
    exclude_dir_globs = sc.get("exclude_dir_globs", [])

    # Always exclude our own output + venv if under roots
    auto_exclude = ["*/kb_tool/kb_out*", "*/kb_out*", "*/.venv*", "*/__pycache__*"]
    exclude_dir_globs = list(exclude_dir_globs) + auto_exclude

    total = 0
    supported = 0
    excluded = 0
    processed = 0
    skipped_unchanged = 0
    errors = 0
    candidates: list[FileRecord] = []

    for path in iter_files(sc["root_dirs"], exclude_dir_globs):
        total += 1
        base = os.path.basename(path)
        if matches_any_glob(base, exclude_file_globs):
            excluded += 1
            continue

        ext = Path(path).suffix.lower()
        if ext not in include_exts:
            excluded += 1
            continue

        supported += 1

        ctime, mtime, size = _stat_times(path)
        fr = FileRecord(
            path=path,
            filename=os.path.basename(path),
            extension=ext,
            size_bytes=size,
            filesystem_created_time=ctime,
            filesystem_modified_time=mtime,
        )

        if dry_run:
            processed += 1
        else:
            candidates.append(fr)

        if max_files and (supported >= max_files):
            break

    if not dry_run and candidates:
        workers = int(cfg.get("llm", {}).get("max_concurrency", 1) or 1)
        workers = max(1, workers)
        logging.info("processing %s files with max_concurrency=%s", len(candidates), workers)

        def _run_one(fr: FileRecord) -> str:
            try:
                changed = db.process_file(fr, run_id=run_id)
                return "processed" if changed else "skipped"
            except Exception:
                logging.exception("failed processing file: %s", fr.path)
                return "error"

        done = 0
        if workers == 1:
            for fr in candidates:
                state = _run_one(fr)
                if state == "processed":
                    processed += 1
                elif state == "skipped":
                    skipped_unchanged += 1
                else:
                    errors += 1
                done += 1
                if done % 10 == 0:
                    logging.info("progress: %s/%s", done, len(candidates))
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(_run_one, fr) for fr in candidates]
                for fut in as_completed(futures):
                    state = fut.result()
                    if state == "processed":
                        processed += 1
                    elif state == "skipped":
                        skipped_unchanged += 1
                    else:
                        errors += 1
                    done += 1
                    if done % 10 == 0:
                        logging.info("progress: %s/%s", done, len(candidates))

    return {
        "total_seen": total,
        "supported_ext": supported,
        "excluded": excluded,
        "processed": processed,
        "skipped_unchanged": skipped_unchanged,
        "errors": errors,
        "dry_run": dry_run,
    }
