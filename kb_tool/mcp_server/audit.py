from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def write_mcp_audit(cfg: dict, payload: dict) -> None:
    audit_path = cfg.get("mcp", {}).get("audit_log") or "./kb_out/logs/mcp_audit.jsonl"
    p = Path(audit_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        **payload,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
