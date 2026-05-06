"""
KB Console — CLI 命令测试
验证 GUI 通过 subprocess 调用的所有 CLI 命令
"""
import subprocess, sys, os, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")
MAIN = str(PROJECT_ROOT / "kb_tool" / "main.py")
CONFIG = str(PROJECT_ROOT / "kb_tool" / "config.yaml")
CWD = str(PROJECT_ROOT / "kb_tool")

def run(args: list[str], timeout: int = 60) -> tuple[int, str]:
    cmd = [PYTHON, "-u", MAIN] + args + ["--config", CONFIG]
    r = subprocess.run(cmd, cwd=CWD, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + "\n" + (r.stderr or "")

def check(name, rc, output, condition):
    if condition:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}: rc={rc}")

print("=== CLI 命令测试 ===")

# 1. find — 快速搜索
print("--- find ---")
rc, out = run(["find", "--query", "止损"])
check("find 止损 退出码0", rc, out, rc == 0)
parsed = None
lines = out.splitlines()
for start in range(len(lines)):
    try:
        parsed = json.loads("\n".join(lines[start:]))
        break
    except:
        continue
check("find 输出可解析为 JSON", rc, out, parsed is not None and "count" in parsed)
check("find 结果 > 0", rc, out, parsed and parsed.get("count", 0) > 0 if parsed else False)

rc, out = run(["find", "--query", "ai"])
check("find ai 不崩溃", rc, out, rc == 0)

# 2. token-budget
print("--- token-budget ---")
rc, out = run(["token-budget", "--scope", "trading"])
check("token-budget 退出码0", rc, out, rc == 0)

# 3. mcp-list-tools
print("--- mcp-list-tools ---")
rc, out = run(["mcp-list-tools"])
check("mcp-list-tools 退出码0", rc, out, rc == 0)
check("mcp-list-tools 包含工具", rc, out, "kb.search_documents" in out)

# 4. mcp-smoke-test
print("--- mcp-smoke-test ---")
rc, out = run(["mcp-smoke-test"])
check("mcp-smoke-test 通过", rc, out, rc == 0)

# 5. weekly-organize — dry run
print("--- weekly-organize ---")
import shutil
desktop = os.path.expanduser("~/Desktop")
rc, out = run(["weekly-organize", "--dry-run", "--max-files", "2", "--source-dirs", desktop, "--non-recursive"], timeout=30)
check("weekly-organize dry-run 退出码0", rc, out, rc == 0)

# 6. build-folder-bundle
print("--- build-folder-bundle ---")
rc, out = run(["build-folder-bundle", "--folder", "AI与工具化"], timeout=30)
check("build-folder-bundle 退出码0", rc, out, rc == 0)

# 7. docs-stats
print("--- docs-stats ---")
rc, out = run(["docs-stats", "--output", str(PROJECT_ROOT / "kb_tool" / "kb_out" / "test_stats.md")], timeout=30)
check("docs-stats 退出码0", rc, out, rc == 0)

# 8. explore— verify all commands parse correctly
print("--- 命令参数解析 ---")
for cmd_name in ["scan", "export", "dashboard", "report", "review", "apply-review",
                  "build-chunks", "search", "monthly-report", "serve", "normalize-tags",
                  "bundle", "agent", "agent-test", "mcp-stdio", "mcp-http",
                  "mcp-list-tools", "mcp-smoke-test", "docs-migrate", "docs-stats",
                  "weekly-organize", "token-budget", "build-folder-bundle",
                  "analyze-folder", "project-analyze", "profile-me",
                  "build-trading-bundle", "trading-monthly-report",
                  "trading-system-build", "trading-analyze", "find",
                  "compact-course-transcripts"]:
    rc, _ = run([cmd_name, "--help"])
    check(f"{cmd_name} --help", rc, "", rc == 0)

print()
print("All CLI tests completed.")
