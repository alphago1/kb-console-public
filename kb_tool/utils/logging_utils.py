from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path


def setup_logging(logs_dir: str, run_id: str) -> str:
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    log_path = os.path.join(logs_dir, f"run-{run_id}.log")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    for h in list(logger.handlers):
        logger.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return log_path


def make_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")
