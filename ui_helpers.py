from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml


@dataclass
class AppPaths:
    workspace_root: Path
    kb_tool_dir: Path
    config_path: Path
    python_exe: Path
    main_py: Path
    docs_dir: Path
    kb_out_dir: Path
    reports_dir: Path
    bundles_dir: Path
    logs_dir: Path
    sqlite_path: Path


def _resolve_from_kb_tool(kb_tool_dir: Path, p: str | None) -> Path:
    if not p:
        return kb_tool_dir
    x = Path(p)
    if x.is_absolute():
        return x
    return (kb_tool_dir / x).resolve()


def load_app_paths(workspace_root: Path | None = None) -> tuple[dict[str, Any], AppPaths]:
    root = workspace_root or Path(__file__).resolve().parent
    kb_tool = (root / "kb_tool").resolve()
    config_path = (kb_tool / "config.yaml").resolve()

    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    py = (root / ".venv" / "Scripts" / "python.exe").resolve()
    if not py.exists():
        py = Path(sys.executable).resolve()

    docs_dir = _resolve_from_kb_tool(kb_tool, cfg.get("workflow", {}).get("docs_root"))
    kb_out = _resolve_from_kb_tool(kb_tool, cfg["storage"]["output_dir"])
    reports = _resolve_from_kb_tool(kb_tool, cfg["storage"]["reports_dir"])
    logs = _resolve_from_kb_tool(kb_tool, cfg["storage"]["logs_dir"])
    sqlite_path = _resolve_from_kb_tool(kb_tool, cfg["storage"]["sqlite_path"])
    bundles = kb_out / "bundles"

    # Overwrite relative paths in cfg with absolutes — so callers that
    # pass cfg directly (e.g. find_idea(cfg)) resolve to the right files.
    cfg["storage"]["sqlite_path"] = str(sqlite_path)
    cfg["storage"]["output_dir"] = str(kb_out)
    cfg["storage"]["reports_dir"] = str(reports)
    cfg["storage"]["logs_dir"] = str(logs)
    if cfg.get("workflow", {}).get("docs_root"):
        cfg["workflow"]["docs_root"] = str(docs_dir)

    paths = AppPaths(
        workspace_root=root,
        kb_tool_dir=kb_tool,
        config_path=config_path,
        python_exe=py,
        main_py=(kb_tool / "main.py").resolve(),
        docs_dir=docs_dir,
        kb_out_dir=kb_out,
        reports_dir=reports,
        bundles_dir=bundles,
        logs_dir=logs,
        sqlite_path=sqlite_path,
    )
    return cfg, paths


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def path_is_under(path: Path, roots: list[Path]) -> bool:
    rp = path.resolve()
    for root in roots:
        rr = root.resolve()
        if str(rp).lower().startswith(str(rr).lower() + os.sep.lower()) or str(rp).lower() == str(rr).lower():
            return True
    return False


def safe_startfile(path: Path, allowed_roots: list[Path]) -> tuple[bool, str]:
    if not path.exists():
        return False, f"path not found: {path}"
    if not path_is_under(path, allowed_roots):
        return False, f"path not allowed: {path}"
    os.startfile(str(path))
    return True, "ok"


def copy_to_clipboard(text: str) -> tuple[bool, str]:
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Set-Clipboard -Value @'\n{text}\n'@",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return True, "ok"
    except Exception as e:
        return False, str(e)


def recent_markdown_files(base: Path) -> list[Path]:
    if not base.exists():
        return []
    files = [p for p in base.rglob("*.md") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def group_reports(reports_dir: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for p in recent_markdown_files(reports_dir):
        rel = p.relative_to(reports_dir)
        group = rel.parts[0] if len(rel.parts) > 1 else "root"
        out.setdefault(group, []).append(p)
    return out


def read_markdown(path: Path, max_chars: int = 120000) -> str:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    if len(txt) > max_chars:
        return txt[:max_chars] + "\n\n...<truncated>"
    return txt


def get_dashboard_state(paths: AppPaths) -> dict[str, Any]:
    state: dict[str, Any] = {
        "docs_count": 0,
        "total_chars": 0,
        "latest_weekly_report": None,
        "latest_weekly_time": None,
        "recent_reports": [],
    }

    if paths.sqlite_path.exists():
        con = sqlite3.connect(str(paths.sqlite_path))
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(extracted_char_count),0) AS c FROM documents WHERE COALESCE(docs_path, path) LIKE ?",
            (str(paths.docs_dir).replace("/", "\\") + "%",),
        ).fetchone()
        state["docs_count"] = int(row["n"] or 0)
        state["total_chars"] = int(row["c"] or 0)
        con.close()

    weekly_dir = paths.reports_dir / "weekly"
    weekly_files = recent_markdown_files(weekly_dir)
    if weekly_files:
        state["latest_weekly_report"] = str(weekly_files[0])
        state["latest_weekly_time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(weekly_files[0].stat().st_mtime))

    state["recent_reports"] = [str(p) for p in recent_markdown_files(paths.reports_dir)[:10]]
    return state


def run_cli_collect(paths: AppPaths, args: list[str]) -> dict[str, Any]:
    cmd = [str(paths.python_exe), "-u", str(paths.main_py)] + args + ["--config", str(paths.config_path)]
    proc = subprocess.run(cmd, cwd=str(paths.kb_tool_dir), capture_output=True, text=True)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return {"cmd": cmd, "returncode": proc.returncode, "output": out}


def try_parse_json_from_text(text: str) -> dict[str, Any] | None:
    txt = (text or "").strip()
    if not txt:
        return None
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    for i in range(len(lines)):
        chunk = "\n".join(lines[i:])
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


# ═══════════════════════════════════════════════════════════════
# Phase 1: New async infrastructure + Phase 2-4 utilities
# ═══════════════════════════════════════════════════════════════

# ── Async Subprocess Runner ──

def _beep(freq: int = 880, duration: float = 0.2) -> None:
    """Play a short browser beep via Web Audio API. Silently fails if blocked."""
    import streamlit as st
    st.markdown(
        f"""<script>(function(){{try{{var c=new AudioContext();var g=c.createGain();
g.gain.value=0.15;g.connect(c.destination);var o=c.createOscillator();
o.type='sine';o.frequency.value={freq};o.connect(g);
o.start();o.stop(c.currentTime+{duration});}}catch(e){{}}}})()</script>""",
        unsafe_allow_html=True,
    )


def run_cli_live_async(
    paths: AppPaths,
    args: list[str],
    title: str,
    on_complete: dict = None,
) -> dict[str, Any]:
    """Non-blocking CLI runner. Stores progress in st.session_state[task_id].
    Returns task_id for tracking."""
    import streamlit as st

    task_id = f"task_{title}_{datetime.now().strftime('%H%M%S')}"

    st.session_state[f"{task_id}_title"] = title
    st.session_state[f"{task_id}_running"] = True
    st.session_state[f"{task_id}_phase"] = "starting"
    st.session_state[f"{task_id}_lines"] = ["正在启动子进程..."]
    st.session_state[f"{task_id}_progress"] = 5
    st.session_state[f"{task_id}_result"] = None
    st.session_state[f"{task_id}_error"] = None
    st.session_state[f"{task_id}_returncode"] = None

    cmd = [str(paths.python_exe), "-u", str(paths.main_py)] + args + ["--config", str(paths.config_path)]

    from streamlit.runtime.scriptrunner import get_script_run_ctx

    ctx = get_script_run_ctx()

    def _worker():
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(paths.kb_tool_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            st.session_state[f"{task_id}_proc"] = proc

            st.session_state[f"{task_id}_phase"] = "running"
            while True:
                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    stripped = line.rstrip("\n")
                    lines = st.session_state[f"{task_id}_lines"]
                    lines.append(stripped)
                    st.session_state[f"{task_id}_lines"] = lines[-300:]
                    if len(lines) % 10 == 0:
                        st.session_state[f"{task_id}_progress"] = min(90, len(lines))
                elif proc.poll() is not None:
                    break

            rc = proc.wait()
            st.session_state[f"{task_id}_returncode"] = rc
            text = "\n".join(st.session_state[f"{task_id}_lines"])
            st.session_state[f"{task_id}_result"] = try_parse_json_from_text(text) or {"output": text}
            st.session_state[f"{task_id}_progress"] = 100

            if rc == 0:
                st.session_state[f"{task_id}_phase"] = "done"
            else:
                st.session_state[f"{task_id}_phase"] = "failed"

        except Exception as e:
            st.session_state[f"{task_id}_phase"] = "failed"
            st.session_state[f"{task_id}_error"] = str(e)

        finally:
            st.session_state[f"{task_id}_running"] = False
            if f"{task_id}_proc" in st.session_state:
                del st.session_state[f"{task_id}_proc"]

    thread = threading.Thread(target=_worker, daemon=True)
    if ctx:
        from streamlit.runtime.scriptrunner import add_script_run_ctx
        add_script_run_ctx(thread, ctx)
    thread.start()

    st.toast(f"⏳ {title} 已在后台启动，你可以浏览其他页面，任务不会中断", icon="⏳")

    return task_id


def render_task_progress(task_id: str) -> bool:
    """Render progress UI for a running task. Returns True if task is still running.
    Returns False if task not found or already completed/failed/cancelled."""
    import streamlit as st

    if not task_id or f"{task_id}_running" not in st.session_state:
        return False

    if not st.session_state.get(f"{task_id}_running") and st.session_state.get(f"{task_id}_phase") not in ("running", "starting"):
        return False

    title = st.session_state.get(f"{task_id}_title", "Task")
    phase = st.session_state.get(f"{task_id}_phase", "")
    progress = st.session_state.get(f"{task_id}_progress", 0)
    lines = st.session_state.get(f"{task_id}_lines", [])

    # Parse real progress from JSON lines like {"progress":{"current":130,"total":200}}
    import json as _json
    for line in reversed(lines):
        try:
            obj = _json.loads(line)
            if isinstance(obj, dict) and "progress" in obj:
                pg = obj["progress"]
                if isinstance(pg, dict) and "current" in pg and "total" in pg:
                    if pg["total"] > 0:
                        progress = int(pg["current"] / pg["total"] * 95) + 5
                    if pg["current"] >= pg["total"]:
                        phase = "running"
                    break
            if isinstance(obj, dict) and "phase" in obj and obj["phase"] == "scan_done":
                st.session_state[f"{task_id}_total_files"] = obj.get("total_files", 0)
        except Exception:
            pass

    if phase == "done":
        st.success(f"✅ {title} — 完成")
        if not st.session_state.get(f"{task_id}_notified"):
            st.toast(f"✅ {title} 已完成！", icon="✅")
            _beep(880, 0.2)
            st.session_state[f"{task_id}_notified"] = True
        # Show result data (persists across page switches)
        result = st.session_state.get(f"{task_id}_result")
        if result and isinstance(result, dict):
            report = result.get("report") or result.get("weekly_report") or result.get("output_dir")
            if report:
                st.caption(f"📄 输出: {report}")
            with st.expander("📋 详情", expanded=False):
                st.json(result)
        return False
    if phase == "failed":
        err = st.session_state.get(f"{task_id}_error") or ""
        lines = st.session_state.get(f"{task_id}_lines", [])
        st.error(f"❌ {title} — 失败: {err}")
        if not st.session_state.get(f"{task_id}_notified"):
            st.toast(f"❌ {title} 失败", icon="❌")
            _beep(220, 0.4)
            st.session_state[f"{task_id}_notified"] = True
        if lines:
            with st.expander("📋 错误日志", expanded=False):
                st.code("\n".join(lines[-30:]), language="text")
        return False

    phase_labels = {
        "starting": "子进程启动中...",
        "running": "执行中...",
    }
    if phase == "starting" and lines and any("HTTP Request" in l for l in lines):
        phase = "running"
    st.info(f"🔄 {title} — {phase_labels.get(phase, phase)}")
    st.caption("💡 任务在后台运行中，你可以切换到其他页面，回来时进度不会丢失")
    st.progress(progress / 100)

    if lines:
        with st.expander("📋 实时日志", expanded=(progress < 100)):
            st.code("\n".join(lines[-50:]), language="text")

    if st.session_state.get(f"{task_id}_running"):
        cancel_key = f"cancel_{task_id}"
        if st.button("✕ 取消任务", key=cancel_key):
            proc = st.session_state.get(f"{task_id}_proc")
            if proc:
                proc.terminate()
            st.session_state[f"{task_id}_running"] = False
            st.session_state[f"{task_id}_phase"] = "cancelled"
            st.rerun()

    still_running = st.session_state.get(f"{task_id}_running", False)
    if still_running:
        time.sleep(1.5)
        st.rerun()

    return still_running


def run_cli_sync(paths: AppPaths, args: list[str], title: str) -> dict[str, Any]:
    """Synchronous CLI runner with spinner. For fast operations (< 5s)."""
    import streamlit as st

    cmd = [str(paths.python_exe), "-u", str(paths.main_py)] + args + ["--config", str(paths.config_path)]
    st.caption(f"执行命令: {' '.join(cmd)}")

    start = time.time()
    proc = subprocess.run(cmd, cwd=str(paths.kb_tool_dir), capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = time.time() - start

    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    result = try_parse_json_from_text(text) or {"output": text, "returncode": proc.returncode}

    if proc.returncode == 0:
        st.success(f"{title} 完成，耗时 {elapsed:.1f}s")
    else:
        st.error(f"{title} 失败，退出码 {proc.returncode}，耗时 {elapsed:.1f}s")

    return result


# ── Config Management ──

def load_config_full(config_path: str) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(cfg: dict[str, Any], config_path: str) -> bool:
    """Save config with timestamped backup. Returns True on success."""
    try:
        backup = f"{config_path}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        shutil.copy2(config_path, backup)

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        keep_recent_backups(config_path, keep=5)
        return True
    except Exception:
        return False


def keep_recent_backups(config_path: str, keep: int = 5):
    parent = Path(config_path).parent
    stem = Path(config_path).name
    backups = sorted(parent.glob(f"{stem}.*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
    for b in backups[keep:]:
        b.unlink(missing_ok=True)


# ── DeepSeek Connectivity Test ──

def test_deepseek_connection(cfg: dict) -> dict[str, Any]:
    """Send a minimal ping to DeepSeek API and return status."""
    llm = cfg.get("llm", {})
    base_url = llm.get("base_url", "https://api.deepseek.com")
    model = llm.get("model", "deepseek-v4-flash")
    api_key = os.getenv(llm.get("api_key_env", "DEEPSEEK_API_KEY")) or ""

    start = time.time()
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "reply OK"}],
                "max_tokens": 5,
                "temperature": 0,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=float(llm.get("timeout_seconds", 10)),
        )
        elapsed_ms = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            return {"ok": True, "latency_ms": elapsed_ms, "model": model}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}", "latency_ms": elapsed_ms}
    except requests.Timeout:
        return {"ok": False, "error": "请求超时 (timeout)", "latency_ms": int((time.time() - start) * 1000)}
    except requests.ConnectionError as e:
        return {"ok": False, "error": f"无法连接到 API: {e}", "latency_ms": int((time.time() - start) * 1000)}
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_ms": int((time.time() - start) * 1000)}


# ── Dashboard Enriched Data ──

def get_dashboard_enriched(paths: AppPaths) -> dict[str, Any]:
    """Enriched dashboard data: KPIs, category distribution, monthly trends, token forecast."""
    state = get_dashboard_state(paths)
    enriched = dict(state)

    if not paths.sqlite_path.exists():
        enriched["db_exists"] = False
        return enriched

    enriched["db_exists"] = True
    con = sqlite3.connect(str(paths.sqlite_path))
    con.row_factory = sqlite3.Row

    # Category distribution
    cat_rows = con.execute(
        """
        SELECT primary_category, COUNT(*) AS n, COALESCE(SUM(extracted_char_count), 0) AS total_chars
        FROM documents WHERE include_in_kb=1 AND primary_category IS NOT NULL
        GROUP BY primary_category ORDER BY total_chars DESC
        """
    ).fetchall()
    enriched["category_dist"] = [{"category": r["primary_category"], "count": r["n"], "chars": r["total_chars"]} for r in cat_rows]

    # Top category by chars
    if cat_rows:
        enriched["top_category"] = {"name": cat_rows[0]["primary_category"], "chars": cat_rows[0]["total_chars"]}
        total = sum(r["total_chars"] for r in cat_rows) or 1
        enriched["top_category"]["pct"] = round(cat_rows[0]["total_chars"] / total * 100)

    # Monthly trend
    month_rows = con.execute(
        """
        SELECT COALESCE(derived_time_month, time_month) AS month, COUNT(*) AS n,
               COALESCE(SUM(extracted_char_count), 0) AS total_chars
        FROM documents WHERE include_in_kb=1
        GROUP BY month ORDER BY month
        """
    ).fetchall()
    enriched["monthly_trend"] = [{"month": r["month"], "files": r["n"], "chars": r["total_chars"]} for r in month_rows if r["month"]]

    # 1M token forecast (recent 3-month avg)
    if len(enriched["monthly_trend"]) >= 3:
        recent = enriched["monthly_trend"][-3:]
        avg_high_tokens = sum(r["chars"] / 1.2 for r in recent) / 3
        current_high = sum(r["chars"] / 1.2 for r in enriched["monthly_trend"])
        if avg_high_tokens > 0:
            months_to_1m = max(0, (1_000_000 - current_high) / avg_high_tokens)
            enriched["token_forecast"] = {"current_high": int(current_high), "monthly_avg_high": int(avg_high_tokens), "months_to_1m": round(months_to_1m, 1)}

    # Pending review count
    review_row = con.execute("SELECT COUNT(*) AS n FROM documents WHERE needs_review=1").fetchone()
    enriched["pending_review"] = int(review_row["n"])

    # Extensions count
    ext_rows = con.execute("SELECT extension, COUNT(*) AS n FROM documents WHERE include_in_kb=1 GROUP BY extension").fetchall()
    enriched["extension_dist"] = [{"ext": r["extension"] or ".unknown", "count": r["n"]} for r in ext_rows]

    con.close()
    return enriched


# ── Folder / Scope Utilities ──

def get_available_folders(paths: AppPaths) -> list[dict[str, Any]]:
    """Get all docs subfolders with file counts."""
    folders = []
    if paths.docs_dir.exists():
        for p in sorted(paths.docs_dir.iterdir()):
            if p.is_dir() and not p.name.startswith("_"):
                doc_files = list(p.rglob("*")) if p.is_dir() else []
                docx_count = sum(1 for f in doc_files if f.suffix.lower() in (".docx", ".doc", ".md", ".txt"))
                folders.append({"name": p.name, "path": str(p), "file_count": docx_count})
    return folders


def get_available_months(paths: AppPaths) -> list[str]:
    """Get list of unique months from DB."""
    if not paths.sqlite_path.exists():
        return []
    con = sqlite3.connect(str(paths.sqlite_path))
    months = [r[0] for r in con.execute(
        "SELECT DISTINCT COALESCE(derived_time_month, time_month) FROM documents WHERE include_in_kb=1 ORDER BY 1"
    ).fetchall() if r[0]]
    con.close()
    return months


# ── System Health Check ──

def system_health_check(cfg: dict, paths: AppPaths) -> list[dict[str, Any]]:
    """Run all system health checks and return results."""
    results = []

    # DB check
    if paths.sqlite_path.exists():
        try:
            con = sqlite3.connect(str(paths.sqlite_path))
            count = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            results.append({"name": "数据库连接", "ok": True, "detail": f"{count} 文档，SQLite 正常"})
            con.close()
        except Exception as e:
            results.append({"name": "数据库连接", "ok": False, "detail": str(e)})
    else:
        results.append({"name": "数据库连接", "ok": None, "detail": "数据库不存在，请先执行 scan"})

    # Config syntax
    try:
        cfg_path = str(paths.config_path)
        yaml.safe_load(open(cfg_path, encoding="utf-8"))
        results.append({"name": "config.yaml 语法", "ok": True, "detail": "格式正确"})
    except Exception as e:
        results.append({"name": "config.yaml 语法", "ok": False, "detail": str(e)})

    # Reports dir writable
    try:
        ensure_dir(paths.reports_dir)
        test_file = paths.reports_dir / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        results.append({"name": "报告目录可写入", "ok": True, "detail": str(paths.reports_dir)})
    except Exception as e:
        results.append({"name": "报告目录可写入", "ok": False, "detail": str(e)})

    # Python exe
    if paths.python_exe.exists():
        results.append({"name": "Python 解释器", "ok": True, "detail": str(paths.python_exe)})
    else:
        results.append({"name": "Python 解释器", "ok": False, "detail": "不存在"})

    # Disk space
    try:
        usage = shutil.disk_usage(paths.kb_out_dir)
        gb = usage.free / (1024 ** 3)
        if gb >= 1:
            results.append({"name": "磁盘剩余空间", "ok": True, "detail": f"{gb:.1f} GB 可用"})
        else:
            results.append({"name": "磁盘剩余空间", "ok": None, "detail": f"仅 {gb:.1f} GB"})
    except Exception:
        results.append({"name": "磁盘剩余空间", "ok": None, "detail": "无法检测"})

    # DeepSeek API
    deep_res = test_deepseek_connection(cfg)
    if deep_res["ok"]:
        results.append({"name": "DeepSeek API", "ok": True, "detail": f"连接正常，延迟 {deep_res['latency_ms']}ms"})
    else:
        results.append({"name": "DeepSeek API", "ok": False, "detail": deep_res.get("error", "未知错误")})

    return results


# ── Monthly Report Builder (reused in Topic Analyze) ──

def estimate_scope_tokens(paths: AppPaths, folders: list[str], month_start: str | None = None, month_end: str | None = None) -> dict[str, Any]:
    """Estimate token budget for a given scope (folders + time range)."""
    if not paths.sqlite_path.exists():
        return {"document_count": 0, "total_chars": 0, "token_low": 0, "token_high": 0, "strategy": "unknown"}

    con = sqlite3.connect(str(paths.sqlite_path))
    con.row_factory = sqlite3.Row

    ph = ",".join(["?"] * len(folders))
    sql = f"SELECT COUNT(*) AS n, COALESCE(SUM(extracted_char_count), 0) AS c FROM documents WHERE include_in_kb=1 AND primary_category IN ({ph})"
    params = list(folders)

    if month_start:
        sql += " AND COALESCE(derived_time_month, time_month) >= ?"
        params.append(month_start)
    if month_end:
        sql += " AND COALESCE(derived_time_month, time_month) <= ?"
        params.append(month_end)

    row = con.execute(sql, params).fetchone()
    con.close()

    n = int(row["n"]) if row else 0
    c = int(row["c"]) if row else 0
    t_low = max(1, int(c / 2.2))
    t_high = max(1, int(c / 1.2))

    if t_high < 850_000:
        strategy = "single_full_read"
    elif t_high <= 1_500_000:
        strategy = "category_batches"
    else:
        strategy = "monthly_batches_or_compacted"

    return {
        "document_count": n,
        "total_chars": c,
        "token_low": t_low,
        "token_high": t_high,
        "fits_1m": t_high <= 1_000_000,
        "strategy": strategy,
    }
