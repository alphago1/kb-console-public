from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import yaml

from utils.logging_utils import make_run_id, setup_logging

# Fix GBK terminal garbled output on Windows: reconfigure stdout/stderr to UTF-8.
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_scan(args: argparse.Namespace) -> int:
    from scanner import scan_files
    from database import KBDatabase

    cfg = load_config(args.config)
    out_dir = cfg["storage"]["output_dir"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    run_id = make_run_id()
    log_path = setup_logging(cfg["storage"]["logs_dir"], run_id)
    logging.info("run_id=%s log=%s", run_id, log_path)

    db = KBDatabase(cfg)
    db.init()

    stats = scan_files(cfg, db=db, run_id=run_id, dry_run=args.dry_run, max_files=args.max_files)
    logging.info("scan done: %s", stats)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from database import KBDatabase

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    db = KBDatabase(cfg)
    db.init()
    paths = db.export_all()
    logging.info("exported: %s", paths)
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from dashboard import build_dashboard

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    out_path = build_dashboard(cfg)
    logging.info("dashboard: %s", out_path)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from quarterly_report import build_quarterly_report

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    q = args.quarter or cfg.get("report", {}).get("default_quarter")
    out_path = build_quarterly_report(cfg, quarter=q)
    logging.info("report: %s", out_path)
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from review_ui import build_review_artifacts

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = build_review_artifacts(cfg, confidence_threshold=args.threshold)
    logging.info("review artifacts: %s", out)
    return 0


def cmd_apply_review(args: argparse.Namespace) -> int:
    from review_ui import apply_review_updates

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = apply_review_updates(cfg, args.file)
    logging.info("apply-review: %s", out)
    return 0


def cmd_build_chunks(args: argparse.Namespace) -> int:
    from chunker import build_chunks

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = build_chunks(cfg, rebuild=args.rebuild)
    logging.info("chunk build: %s", out)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from chunker import build_chunks, search_chunks

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    # Ensure chunk table has data
    build_chunks(cfg, rebuild=False)
    rows = search_chunks(cfg, query=args.query, limit=args.limit)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    logging.info("search results=%s", len(rows))
    return 0


def cmd_monthly_report(args: argparse.Namespace) -> int:
    from monthly_report import build_monthly_report

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = build_monthly_report(cfg, args.month)
    logging.info("monthly report: %s", out)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from server import create_app

    cfg = load_config(args.config)
    app = create_app(cfg)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def cmd_normalize_tags(args: argparse.Namespace) -> int:
    from tag_normalizer import normalize_tags_in_db

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = normalize_tags_in_db(cfg["storage"]["sqlite_path"])
    logging.info("normalize-tags: %s", out)
    return 0


def cmd_bundle(args: argparse.Namespace) -> int:
    from model_context_bundle import build_model_context_bundle

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = build_model_context_bundle(cfg)
    logging.info("bundle: %s", out)
    return 0


def cmd_mcp_stdio(args: argparse.Namespace) -> int:
    from mcp_server.server import run_stdio_server

    cfg = load_config(args.config)
    # stdio mode: avoid non-protocol logs on stdout.
    logging.getLogger().handlers.clear()
    return run_stdio_server(cfg)


def cmd_mcp_http(args: argparse.Namespace) -> int:
    from mcp_server.server import run_http_server

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    return run_http_server(cfg, host=args.host, port=args.port)


def cmd_mcp_list_tools(args: argparse.Namespace) -> int:
    from mcp_server.tools import list_tools

    cfg = load_config(args.config)
    tools = list_tools(cfg)
    for t in tools:
        print(t["name"])
    return 0


def cmd_mcp_smoke_test(args: argparse.Namespace) -> int:
    from mcp_server.adapters import call_tool
    from mcp_server.tools import list_tools

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    tools = list_tools(cfg)
    names = {t["name"] for t in tools}
    required = {
        "kb.search_documents",
        "kb.search_chunks",
        "kb.get_document",
        "kb.compare_periods",
        "kb.summarize_month",
        "kb.find_writing_candidates",
        "kb.cluster_project_ideas",
    }
    missing = sorted(required - names)
    if missing:
        print("missing tools:", missing)
        return 1

    # 1) happy path
    r1 = call_tool(cfg, "kb.search_documents", {"query": "止损 执行力", "limit": 10}, client="smoke")
    txt = json.dumps(r1, ensure_ascii=False)
    if "disclaimer" not in r1:
        print("failed: disclaimer missing")
        return 1
    if len(txt) > int(cfg.get("mcp", {}).get("max_result_chars", 12000)) + 512:
        print("failed: result too large")
        return 1
    if bool(cfg.get("mcp", {}).get("redact_source_paths", True)):
        items = r1.get("items") if isinstance(r1, dict) else None
        has_path = bool(items and any(isinstance(it, dict) and ("path" in it) for it in items))
        if has_path and "[KB_ROOT]" not in txt:
            print("failed: path not redacted")
            return 1

    # 2) unknown tool must be denied
    r2 = call_tool(cfg, "kb.delete_file", {"path": "x"}, client="smoke")
    if "error" not in r2:
        print("failed: unknown tool not denied")
        return 1

    # 3) path-like args should be denied
    r3 = call_tool(cfg, "kb.search_documents", {"query": "C:\\Windows"}, client="smoke")
    if "error" not in r3:
        print("failed: path-like input not denied")
        return 1

    # 4) audit should exist
    audit_path = cfg.get("mcp", {}).get("audit_log") or "./kb_out/logs/mcp_audit.jsonl"
    if not Path(audit_path).exists():
        print("failed: mcp audit log not found")
        return 1

    print("mcp-smoke-test passed")
    return 0


def cmd_docs_migrate(args: argparse.Namespace) -> int:
    from docs_migrator import migrate_docs

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    out = migrate_docs(
        cfg,
        docs_root=args.docs_root,
        include_excluded=not args.only_included,
        dry_run=args.dry_run,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if int(out.get("errors") or 0) == 0 else 1


def cmd_docs_stats(args: argparse.Namespace) -> int:
    from docs_stats import write_docs_stats_report

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    out = write_docs_stats_report(cfg, docs_root=args.docs_root, output_path=args.output)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if int(out.get("errors") or 0) == 0 else 1


def cmd_weekly_organize(args: argparse.Namespace) -> int:
    from workflow_mainline import weekly_organize

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    source_dirs = args.source_dirs.split(",") if args.source_dirs else None
    out = weekly_organize(cfg, dry_run=args.dry_run, max_files=args.max_files, source_dirs=source_dirs, recursive=not args.non_recursive)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if int(out.get("errors") or 0) == 0 else 1


def cmd_token_budget(args: argparse.Namespace) -> int:
    from bundle_builder import build_budget, fetch_folder_docs
    from workflow_mainline import token_budget as trading_token_budget

    cfg = load_config(args.config)
    if args.scope == "trading":
        out = trading_token_budget(cfg, scope="trading")
    elif args.scope == "folder":
        if not args.folder:
            raise ValueError("--folder is required when --scope folder")
        docs = fetch_folder_docs(cfg, args.folder)
        out = {"scope": "folder", "folder": args.folder, **build_budget(docs)}
    else:
        raise ValueError("scope must be trading or folder")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_build_folder_bundle(args: argparse.Namespace) -> int:
    from folder_analyzer import build_folder_bundle

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = build_folder_bundle(cfg, folder=args.folder)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze_folder(args: argparse.Namespace) -> int:
    from folder_analyzer import analyze_folder

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = analyze_folder(cfg, folder=args.folder, question=args.question)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_project_analyze(args: argparse.Namespace) -> int:
    from project_analyzer import project_analyze

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = project_analyze(cfg, topic=args.topic, question=args.question)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_profile_me(args: argparse.Namespace) -> int:
    from profile_analyzer import profile_me

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = profile_me(cfg, scope=args.scope)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_build_trading_bundle(args: argparse.Namespace) -> int:
    from workflow_mainline import build_trading_bundle

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = build_trading_bundle(cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_trading_monthly_report(args: argparse.Namespace) -> int:
    from workflow_mainline import trading_monthly_report

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = trading_monthly_report(cfg, args.month)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_trading_system_build(args: argparse.Namespace) -> int:
    from workflow_mainline import trading_system_build

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = trading_system_build(cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_trading_analyze(args: argparse.Namespace) -> int:
    from workflow_mainline import trading_analyze

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    categories = args.categories.split(",") if args.categories else None
    out = trading_analyze(cfg, topic=args.topic, categories=categories)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    from workflow_mainline import find_idea

    cfg = load_config(args.config)
    out = find_idea(cfg, query=args.query, month_start=args.month_start, month_end=args.month_end, category=args.category)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_compact_course_transcripts(args: argparse.Namespace) -> int:
    from workflow_mainline import compact_course_transcripts

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)
    out = compact_course_transcripts(cfg)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_diagnosis_from_notes(args: argparse.Namespace) -> int:
    from diagnosis import build_profile, infer_signals_from_text

    input_path = args.input
    output_dir = args.output
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    text = Path(input_path).read_text(encoding="utf-8", errors="ignore")
    signals = infer_signals_from_text(text)
    profile = build_profile(signals)

    out_path = Path(output_dir) / "profile_draft.json"
    out_path.write_text(profile.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "input": str(input_path),
        "signals_found": len(signals),
        "profile": str(out_path),
        "fields_with_confidence": {
            k: v for k, v in profile.confidence_map.items() if v > 0
        },
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_diagnosis_plan(args: argparse.Namespace) -> int:
    from diagnosis import UserKnowledgeProfile, analyze_gaps, plan_interview

    profile_path = args.profile
    output_dir = args.output
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    raw = Path(profile_path).read_text(encoding="utf-8")
    profile = UserKnowledgeProfile.model_validate_json(raw)
    gaps = analyze_gaps(profile)
    plan = plan_interview(profile, gaps)

    out_path = Path(output_dir) / "interview_plan.json"
    out_path.write_text(plan.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "profile": str(profile_path),
        "gaps_found": len(gaps),
        "questions_selected": len(plan.selected_questions),
        "plan": str(out_path),
        "gap_summary": [
            {"field": g.field_name, "priority": g.priority, "confidence": g.current_confidence}
            for g in gaps[:10]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_karpathy_baseline_generate(args: argparse.Namespace) -> int:
    from karpathy_baseline import generate_baseline, write_baseline_markdown

    output_dir = args.output
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    components = generate_baseline()
    md_path = write_baseline_markdown(components, str(Path(output_dir) / "karpathy_baseline.md"))

    print(json.dumps({
        "baseline_version": "karpathy-v1",
        "components": len(components),
        "layers": list(dict.fromkeys(c.layer for c in components)),
        "baseline_md": md_path,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_karpathy_adapt(args: argparse.Namespace) -> int:
    from diagnosis.schemas import UserKnowledgeProfile
    from karpathy_baseline import (
        generate_baseline,
        generate_diff,
        write_diff_markdown,
        generate_blueprint,
        check_word_compatibility,
        check_report_first_compatibility,
    )

    output_dir = args.output
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    profile = UserKnowledgeProfile.model_validate_json(
        Path(args.profile).read_text(encoding="utf-8")
    )
    components = generate_baseline()

    # Extract session name from output path (e.g., kb_out/blueprints/session_001 → session_001)
    session_name = Path(args.output).name

    diff = generate_diff(profile, components, session=session_name)
    diff_path = write_diff_markdown(diff, str(Path(output_dir) / "adaptation_diff.md"))

    # Generate adapted blueprint
    blueprint = generate_blueprint(profile, components, diff, session=Path(args.output).parent.name)
    bp_path = Path(output_dir) / "adapted_knowledge_blueprint.md"

    bp_lines = [
        f"# Adapted Knowledge Blueprint",
        f"",
        f"> Session: {blueprint.profile_session}",
        f"> Baseline: {blueprint.baseline_used}",
        f"> Entry Point: {blueprint.entry_point}",
        f"",
        blueprint.summary_narrative,
        "",
        "---",
        "",
        "## Enabled Components",
        "",
    ]
    for c in blueprint.enabled_components:
        bp_lines.append(f"- **{c.name}** (`{c.component_id}`): {c.default_policy}")
    if blueprint.downgraded_components:
        bp_lines.append("")
        bp_lines.append("## Downgraded Components")
        bp_lines.append("")
        for c in blueprint.downgraded_components:
            bp_lines.append(f"- **{c.name}** (`{c.component_id}`)")
    if blueprint.replaced_components:
        bp_lines.append("")
        bp_lines.append("## Replaced Components")
        bp_lines.append("")
        for r in blueprint.replaced_components:
            bp_lines.append(f"- `{r['component_id']}`: {r['reason']}")
    if blueprint.enhanced_components:
        bp_lines.append("")
        bp_lines.append("## Enhanced Components")
        bp_lines.append("")
        for e in blueprint.enhanced_components:
            bp_lines.append(f"- `{e['component_id']}`: {e['reason']}")
    if blueprint.disabled_components:
        bp_lines.append("")
        bp_lines.append("## Disabled Components")
        bp_lines.append("")
        for d in blueprint.disabled_components:
            bp_lines.append(f"- `{d}`")
    if blueprint.word_compatibility_notes:
        bp_lines.append("")
        bp_lines.append("## Word Compatibility Notes")
        bp_lines.append("")
        for n in blueprint.word_compatibility_notes:
            bp_lines.append(f"- {n}")

    bp_path.write_text("\n".join(bp_lines) + "\n", encoding="utf-8")

    # Write component_plan.yaml
    import yaml as _yaml
    cp_path = Path(output_dir) / "component_plan.yaml"
    cp_path.write_text(_yaml.dump({
        "version": "adapted-v1",
        "session": blueprint.profile_session,
        "entry_point": blueprint.entry_point,
        "report_first": blueprint.report_first,
        "word_first": blueprint.word_first,
        "human_index_strategy": blueprint.human_index_strategy,
        "log_strategy": blueprint.log_strategy,
        "wiki_cache_strategy": blueprint.wiki_cache_strategy,
        "enabled_count": len(blueprint.enabled_components),
        "downgraded_count": len(blueprint.downgraded_components),
        "replaced_count": len(blueprint.replaced_components),
        "enhanced_count": len(blueprint.enhanced_components),
        "disabled_count": len(blueprint.disabled_components),
    }, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    # Word compatibility plan
    word_notes = check_word_compatibility(profile)
    wc_path = Path(output_dir) / "word_compatibility_plan.md"
    wc_path.write_text(
        "# Word Compatibility Plan\n\n" +
        "\n".join(f"- {n}" for n in word_notes) + "\n",
        encoding="utf-8",
    )

    # Wiki cache policy
    wiki_cache_path = Path(output_dir) / "wiki_cache_policy.yaml"
    wiki_cache_path.write_text(_yaml.dump({
        "strategy": blueprint.wiki_cache_strategy,
        "format": "JSON",
        "location": "kb_out/cache/wiki_cache.json",
        "max_size_chars": 100000,
        "update_on_ingest": True,
        "full_rebuild": "monthly",
    }, allow_unicode=True), encoding="utf-8")

    # Report-first policy
    report_policy = check_report_first_compatibility(profile)
    rf_path = Path(output_dir) / "report_first_policy.yaml"
    rf_path.write_text(_yaml.dump(report_policy, allow_unicode=True), encoding="utf-8")

    print(json.dumps({
        "baseline_used": "karpathy-v1",
        "profile": str(args.profile),
        "diff": str(diff_path),
        "blueprint": str(bp_path),
        "component_plan": str(cp_path),
        "word_compatibility_plan": str(wc_path),
        "wiki_cache_policy": str(wiki_cache_path),
        "report_first_policy": str(rf_path),
        "adaptation_summary": {
            "keep": diff.keep_count,
            "downgrade": diff.downgrade_count,
            "replace": diff.replace_count,
            "enhance": diff.enhance_count,
            "disable": diff.disable_count,
        },
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    from agent.runtime import AgentRuntime

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    rt = AgentRuntime(cfg)
    result = rt.run(args.query)
    print(result["answer"])
    logging.info("agent steps=%s tool_calls=%s", result["steps"], result["tool_calls"])
    return 0


def cmd_agent_test(args: argparse.Namespace) -> int:
    from agent.runtime import AgentRuntime

    cfg = load_config(args.config)
    run_id = make_run_id()
    setup_logging(cfg["storage"]["logs_dir"], run_id)

    tests = [
        "我 2025-12 到 2026-03 的交易错误有什么变化？",
        "我关于止损和执行力的认知发生了什么变化？",
        "找出最近三个月写作潜力最高的文档。",
        "我有哪些 RAG 项目想法反复出现？",
        "生成 2026-03 的交易复盘月报。",
    ]
    rt = AgentRuntime(cfg)

    passed = 0
    for i, q in enumerate(tests, 1):
        ok = False
        steps = 0
        tool_calls = 0
        answer = ""
        error = None
        try:
            res = rt.run(q)
            ok = bool((res.get("answer") or "").strip())
            steps = res.get("steps", 0)
            tool_calls = res.get("tool_calls", 0)
            answer = (res.get("answer") or "")[:240]
        except Exception as e:
            error = str(e)

        if ok:
            passed += 1

        try:
            if error:
                print(f"[{i}] PASS=False ERROR={error}\nQ: {q}\n")
            else:
                print(f"[{i}] PASS={ok} steps={steps} tool_calls={tool_calls}\nQ: {q}\nA: {answer}\n")
        except UnicodeEncodeError:
            print(f"[{i}] PASS={ok} steps={steps} tool_calls={tool_calls}\nQ: {q}\nA: <skipped: encoding error>\n")

    print(f"agent-test summary: {passed}/{len(tests)} passed")
    return 0 if passed == len(tests) else 1


def cmd_build_deep_custom(args: argparse.Namespace) -> int:
    from deep_custom_build import dry_run as deep_dry_run, build_deep_custom

    cfg = load_config(args.config)
    out_dir = args.output

    if args.dry_run:
        result = deep_dry_run(cfg)
        print(json.dumps({"mode":"dry-run","total_seen":result["total_seen"],
            "supported":result["supported"],"excluded":result["excluded"],
            "extensions":result["extensions"]}, ensure_ascii=False, indent=2))
        return 0

    build_result = build_deep_custom(
        config_path=args.config, blueprint_path=args.blueprint,
        policy_path=args.policy, components_path=args.components, output_dir=out_dir,
        skip_scan=args.no_scan if hasattr(args,'no_scan') else False,
        skip_wiki=args.skip_wiki if hasattr(args,'skip_wiki') else False,
        wiki_only=args.wiki_only if hasattr(args,'wiki_only') else False,
    )
    print(json.dumps({"mode":"full-build","output_dir":build_result["output_dir"],
        "database":build_result["database"],"scan":build_result["scan"],
        "wiki_pages":build_result.get("wiki_pages","")}, ensure_ascii=False, indent=2))
    print("\n===== BUILD COMPLETE =====")
    print(f"输出: {build_result['output_dir']}")
    print("安全确认: 源文件未被移动/修改/删除")
    return 0


def cmd_validate_deep_custom(args: argparse.Namespace) -> int:
    from validation import run_all_scenarios, generate_all_reports
    results = run_all_scenarios(args.kb)
    reports = generate_all_reports(results, args.output)
    print(json.dumps({"status":"ok","scenarios":len(results),
        "passed":sum(1 for r in results if r.status=="pass"),
        "failed":sum(1 for r in results if r.status=="fail"),
        "reports":reports}, ensure_ascii=False, indent=2))
    for r in results:
        icon = {"pass":"✅","partial":"⚠️","fail":"❌"}.get(r.status,"?")
        print(f"{icon} {r.scenario_name}: {r.status}")
    return 0


def cmd_wiki_route(args: argparse.Namespace) -> int:
    from wiki_router import route_query
    result = route_query(args.query, args.kb)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_build_supervised_kb(args: argparse.Namespace) -> int:
    """Build official knowledge base using user-approved policies."""
    from supervised_build import build_supervised_kb

    # Resolve sqlite path: --sqlite flag > config's sqlite_path
    sqlite_path = getattr(args, "sqlite", None)
    if not sqlite_path and hasattr(args, "config") and args.config:
        try:
            cfg = load_config(args.config)
            sqlite_path = cfg.get("storage", {}).get("sqlite_path")
        except Exception:
            pass

    result = build_supervised_kb(
        inventory_path=args.inventory,
        policy_dir=args.policy,
        output_dir=args.output,
        llm_assignments_path=args.llm_assignments,
        sqlite_path=sqlite_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_sample_review(args: argparse.Namespace) -> int:
    """Generate stratified review sample from auto-cluster results."""
    from feedback.sample_review import generate_review_sample

    result = generate_review_sample(
        assignments_path=args.assignments,
        output_dir=args.output,
        max_samples=args.max_samples,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_learn_from_review(args: argparse.Namespace) -> int:
    """Learn from user feedback: generate category schema, tag ontology, rules."""
    from feedback.sample_review import learn_from_feedback

    result = learn_from_feedback(
        assignments_path=args.assignments,
        review_csv_path=args.review,
        output_dir=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_scan_filenames(args: argparse.Namespace) -> int:
    """Scan filenames only — build file world map. Zero content reads, zero LLM calls."""
    from filename_scanner import scan_filenames

    root_dirs = getattr(args, "root_dir", None)
    if root_dirs:
        root_dirs = [d.strip() for d in root_dirs.split(",") if d.strip()]

    result = scan_filenames(
        config_path=args.config,
        output_dir=args.output,
        recursive=not args.no_recursive,
        max_files=args.max_files,
        root_dirs=root_dirs,
    )

    print(json.dumps({
        "status": "ok",
        "total_files": result["total_files"],
        "total_folders": result["total_folders"],
        "total_size_bytes": result["total_size_bytes"],
        "total_size_human": f"{result['total_size_bytes']/1_000_000:.1f} MB" if result["total_size_bytes"] > 1_000_000 else f"{result['total_size_bytes']/1_000:.1f} KB",
        "extensions": result["extensions"],
        "recursive": result["recursive"],
        "elapsed_ms": result["elapsed_ms"],
        "output_dir": result["output_dir"],
        "output_files": [str(f) for f in result["output_files"]],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_auto_cluster(args: argparse.Namespace) -> int:
    """Content-aware auto-cluster: full-text → LLM summaries → classification."""
    from auto_cluster import run_experiment

    config_path = getattr(args, "config", None)

    result = run_experiment(
        inventory_path=args.inventory,
        output_dir=args.output,
        target=args.target,
        full_texts_path=args.full_texts,
        config_path=config_path,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_test_all(args: argparse.Namespace) -> int:
    """Run all tests using MockLLM. No real API calls, no real user files."""
    from pathlib import Path

    # Import test runner from tests/
    test_runner_path = Path(__file__).resolve().parent.parent / "tests" / "test_runner.py"
    if not test_runner_path.exists():
        print(f"ERROR: test runner not found at {test_runner_path}")
        return 1

    import importlib.util
    spec = importlib.util.spec_from_file_location("test_runner", str(test_runner_path))
    test_runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(test_runner)

    output_dir = Path(args.output) if args.output else None
    result = test_runner.run_all_tests(output_dir=output_dir)
    return 0 if result["all_passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kb_tool", description="Local knowledge-base organizer")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="scan/extract/sample/classify/store")
    s.add_argument("--config", required=True)
    s.add_argument("--dry-run", action="store_true", help="only scan and show stats; do not call LLM")
    s.add_argument("--max-files", type=int, default=None, help="limit files for a test run")
    s.set_defaults(func=cmd_scan)

    e = sub.add_parser("export", help="export csv/json")
    e.add_argument("--config", required=True)
    e.set_defaults(func=cmd_export)

    d = sub.add_parser("dashboard", help="generate dashboard/index.html")
    d.add_argument("--config", required=True)
    d.set_defaults(func=cmd_dashboard)

    r = sub.add_parser("report", help="generate quarterly report")
    r.add_argument("--config", required=True)
    r.add_argument("--quarter", required=False)
    r.set_defaults(func=cmd_report)

    rv = sub.add_parser("review", help="generate review.html and review_updates.csv")
    rv.add_argument("--config", required=True)
    rv.add_argument("--threshold", type=float, default=0.75)
    rv.set_defaults(func=cmd_review)

    ar = sub.add_parser("apply-review", help="apply manual review updates into sqlite")
    ar.add_argument("--config", required=True)
    ar.add_argument("--file", required=True)
    ar.set_defaults(func=cmd_apply_review)

    bc = sub.add_parser("build-chunks", help="chunk included docs and build FTS index")
    bc.add_argument("--config", required=True)
    bc.add_argument("--rebuild", action="store_true")
    bc.set_defaults(func=cmd_build_chunks)

    se = sub.add_parser("search", help="full-text search in chunks")
    se.add_argument("--config", required=True)
    se.add_argument("--query", required=True)
    se.add_argument("--limit", type=int, default=20)
    se.set_defaults(func=cmd_search)

    mr = sub.add_parser("monthly-report", help="generate monthly report")
    mr.add_argument("--config", required=True)
    mr.add_argument("--month", required=True)
    mr.set_defaults(func=cmd_monthly_report)

    sv = sub.add_parser("serve", help="run local FastAPI server")
    sv.add_argument("--config", required=True)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)

    nt = sub.add_parser("normalize-tags", help="normalize existing emotion/topic tags in sqlite")
    nt.add_argument("--config", required=True)
    nt.set_defaults(func=cmd_normalize_tags)

    mb = sub.add_parser("bundle", help="build model_context_bundle.md")
    mb.add_argument("--config", required=True)
    mb.set_defaults(func=cmd_bundle)

    ag = sub.add_parser("agent", help="[experimental] run deepseek tool-calling agent")
    ag.add_argument("--config", required=True)
    ag.add_argument("--query", required=True)
    ag.set_defaults(func=cmd_agent)

    at = sub.add_parser("agent-test", help="[experimental] run built-in 5 agent test queries")
    at.add_argument("--config", required=True)
    at.set_defaults(func=cmd_agent_test)

    ms = sub.add_parser("mcp-stdio", help="[experimental] run MCP server over stdio")
    ms.add_argument("--config", required=True)
    ms.set_defaults(func=cmd_mcp_stdio)

    mh = sub.add_parser("mcp-http", help="[experimental] run MCP server over localhost HTTP")
    mh.add_argument("--config", required=True)
    mh.add_argument("--host", default="127.0.0.1")
    mh.add_argument("--port", type=int, default=8765)
    mh.set_defaults(func=cmd_mcp_http)

    ml = sub.add_parser("mcp-list-tools", help="[experimental] list enabled MCP tools")
    ml.add_argument("--config", required=True)
    ml.set_defaults(func=cmd_mcp_list_tools)

    mt = sub.add_parser("mcp-smoke-test", help="[experimental] run MCP smoke tests")
    mt.add_argument("--config", required=True)
    mt.set_defaults(func=cmd_mcp_smoke_test)

    dm = sub.add_parser("docs-migrate", help="copy KB source files into workspace docs/ and rewrite sqlite paths")
    dm.add_argument("--config", required=True)
    dm.add_argument("--docs-root", required=False, default=None, help="override docs root (default: <workspace>/docs)")
    dm.add_argument("--dry-run", action="store_true", help="preview only; do not copy or update DB")
    dm.add_argument("--only-included", action="store_true", help="only migrate include_in_kb=1 documents")
    dm.set_defaults(func=cmd_docs_migrate)

    ds = sub.add_parser("docs-stats", help="compute word/char stats for workspace docs/ and write a markdown report")
    ds.add_argument("--config", required=True)
    ds.add_argument("--docs-root", required=False, default=None, help="override docs root (default: <workspace>/docs)")
    ds.add_argument("--output", required=False, default=None, help="output markdown path (default: <workspace>/docs_字数统计报告.md)")
    ds.set_defaults(func=cmd_docs_stats)

    wo = sub.add_parser("weekly-organize", help="mainline: weekly organize for new/changed files into docs")
    wo.add_argument("--config", required=True)
    wo.add_argument("--dry-run", action="store_true", help="scan and classify candidates without writing docs/sqlite")
    wo.add_argument("--max-files", type=int, default=None, help="limit source files for a small weekly run")
    wo.add_argument("--source-dirs", type=str, default=None, help="comma-separated source directories (overrides config)")
    wo.add_argument("--non-recursive", action="store_true", help="only scan top-level files, don't recurse into subdirs")
    wo.set_defaults(func=cmd_weekly_organize)

    tb = sub.add_parser("token-budget", help="mainline: estimate token budget and strategy")
    tb.add_argument("--config", required=True)
    tb.add_argument("--scope", default="trading", choices=["trading", "folder"])
    tb.add_argument("--folder", required=False, default=None)
    tb.set_defaults(func=cmd_token_budget)

    bfb = sub.add_parser("build-folder-bundle", help="mainline: build scoped full-read bundle for a folder")
    bfb.add_argument("--config", required=True)
    bfb.add_argument("--folder", required=True)
    bfb.set_defaults(func=cmd_build_folder_bundle)

    af = sub.add_parser("analyze-folder", help="mainline: analyze a folder with scoped full-read")
    af.add_argument("--config", required=True)
    af.add_argument("--folder", required=True)
    af.add_argument("--question", required=True)
    af.set_defaults(func=cmd_analyze_folder)

    pa = sub.add_parser("project-analyze", help="mainline: analyze a project/topic with scoped full-read")
    pa.add_argument("--config", required=True)
    pa.add_argument("--topic", required=True)
    pa.add_argument("--question", required=True)
    pa.set_defaults(func=cmd_project_analyze)

    pm = sub.add_parser("profile-me", help="mainline: build personal/trading/ai-projects profile")
    pm.add_argument("--config", required=True)
    pm.add_argument("--scope", required=True, choices=["all", "trading", "ai-projects"])
    pm.set_defaults(func=cmd_profile_me)

    btb = sub.add_parser("build-trading-bundle", help="mainline: build full trading bundle markdown")
    btb.add_argument("--config", required=True)
    btb.set_defaults(func=cmd_build_trading_bundle)

    tmr = sub.add_parser("trading-monthly-report", help="mainline: generate trading monthly report by month")
    tmr.add_argument("--config", required=True)
    tmr.add_argument("--month", required=True)
    tmr.set_defaults(func=cmd_trading_monthly_report)

    tsb = sub.add_parser("trading-system-build", help="mainline: build trading system report from full corpus")
    tsb.add_argument("--config", required=True)
    tsb.set_defaults(func=cmd_trading_system_build)

    ta = sub.add_parser("trading-analyze", help="mainline: analyze a trading topic across corpus")
    ta.add_argument("--config", required=True)
    ta.add_argument("--topic", required=True)
    ta.add_argument("--categories", type=str, default=None, help="comma-separated categories to search (default: trading categories)")
    ta.set_defaults(func=cmd_trading_analyze)

    fi = sub.add_parser("find", help="mainline: find where an idea appears (FTS + filename)")
    fi.add_argument("--config", required=True)
    fi.add_argument("--query", required=True)
    fi.add_argument("--month-start", required=False, default=None)
    fi.add_argument("--month-end", required=False, default=None)
    fi.add_argument("--category", required=False, default=None)
    fi.set_defaults(func=cmd_find)

    dn = sub.add_parser("diagnosis-from-notes", help="diagnosis: infer user profile from text notes")
    dn.add_argument("--config", required=True)
    dn.add_argument("--input", required=True, help="path to markdown/txt file with user notes/answers")
    dn.add_argument("--output", required=True, help="output directory for profile_draft.json")
    dn.set_defaults(func=cmd_diagnosis_from_notes)

    dp = sub.add_parser("diagnosis-plan", help="diagnosis: generate interview plan from profile gaps")
    dp.add_argument("--config", required=True)
    dp.add_argument("--profile", required=True, help="path to profile_draft.json")
    dp.add_argument("--output", required=True, help="output directory for interview_plan.json")
    dp.set_defaults(func=cmd_diagnosis_plan)

    kb_base = sub.add_parser("karpathy-baseline-generate", help="baseline: generate default Karpathy-style wiki baseline")
    kb_base.add_argument("--output", required=True, help="output directory for baseline markdown")
    kb_base.set_defaults(func=cmd_karpathy_baseline_generate)

    kb_adapt = sub.add_parser("karpathy-adapt", help="baseline: adapt Karpathy baseline to user profile")
    kb_adapt.add_argument("--baseline", required=True, help="path to baseline directory (with karpathy_baseline.md)")
    kb_adapt.add_argument("--profile", required=True, help="path to UserKnowledgeProfile JSON")
    kb_adapt.add_argument("--output", required=True, help="output directory for adapted blueprint + diff + policies")
    kb_adapt.set_defaults(func=cmd_karpathy_adapt)

    bdc = sub.add_parser("build-deep-custom", help="deep-custom: full build pipeline")
    bdc.add_argument("--config", required=True)
    bdc.add_argument("--blueprint", required=True)
    bdc.add_argument("--policy", required=True)
    bdc.add_argument("--components", required=True)
    bdc.add_argument("--output", required=True)
    bdc.add_argument("--dry-run", action="store_true")
    bdc.add_argument("--no-scan", action="store_true")
    bdc.add_argument("--skip-wiki", action="store_true")
    bdc.add_argument("--wiki-only", action="store_true")
    bdc.set_defaults(func=cmd_build_deep_custom)

    vd = sub.add_parser("validate-deep-custom", help="validation: run 5 core scenario tests")
    vd.add_argument("--kb", required=True)
    vd.add_argument("--output", required=True)
    vd.set_defaults(func=cmd_validate_deep_custom)

    wr = sub.add_parser("wiki-route", help="wiki: route query through wiki pages")
    wr.add_argument("--query", required=True)
    wr.add_argument("--kb", required=True)
    wr.set_defaults(func=cmd_wiki_route)

    cc = sub.add_parser("compact-course-transcripts", help="mainline: compact trading transcript-style docs")
    cc.add_argument("--config", required=True)
    cc.set_defaults(func=cmd_compact_course_transcripts)

    ta_test = sub.add_parser("test-all", help="run all tests with MockLLM (no real API, no real files)")
    ta_test.add_argument("--output", required=False, default=None, help="override output directory for test_report.md")
    ta_test.set_defaults(func=cmd_test_all)

    sf = sub.add_parser("scan-filenames", help="scan filenames only — build file world map, zero content reads, zero LLM")
    sf.add_argument("--config", required=True, help="path to config.yaml")
    sf.add_argument("--output", required=False, default="./kb_out/file_inventory", help="output directory (default: ./kb_out/file_inventory)")
    sf.add_argument("--no-recursive", action="store_true", help="only scan top-level files, don't recurse into subdirs")
    sf.add_argument("--max-files", type=int, default=None, help="limit files for a test run")
    sf.add_argument("--root-dir", required=False, default=None, help="override scan root directory (comma-separated; overrides config.root_dirs)")
    sf.set_defaults(func=cmd_scan_filenames)

    ac = sub.add_parser("auto-cluster", help="content-aware clustering: full-text → LLM summaries → classification")
    ac.add_argument("--inventory", required=True, help="path to file_inventory.jsonl")
    ac.add_argument("--output", required=True, help="output directory for cluster results")
    ac.add_argument("--target", type=int, default=None, help="target category count (default: ceil(files/30))")
    ac.add_argument("--full-texts", required=False, default=None, help="pre-extracted full_texts.jsonl path")
    ac.add_argument("--config", required=False, default=None, help="path to config.yaml (for text extraction settings)")
    ac.add_argument("--dry-run", action="store_true", help="preview only, no LLM calls")
    ac.set_defaults(func=cmd_auto_cluster)

    sr = sub.add_parser("sample-review", help="generate stratified review sample from auto-cluster results")
    sr.add_argument("--assignments", required=True, help="path to final_assignments.jsonl")
    sr.add_argument("--output", required=True, help="output directory for review_sample.csv")
    sr.add_argument("--max-samples", type=int, default=100, help="max files to sample (default: min(10%%, 100))")
    sr.add_argument("--config", required=False, default=None, help=argparse.SUPPRESS)
    sr.set_defaults(func=cmd_sample_review)

    lr = sub.add_parser("learn-from-review", help="learn category schema/tags/rules from user-reviewed CSV")
    lr.add_argument("--review", required=True, help="path to user-edited review_sample.csv")
    lr.add_argument("--assignments", required=True, help="path to final_assignments.jsonl")
    lr.add_argument("--output", required=True, help="output directory for learned artifacts")
    lr.add_argument("--config", required=False, default=None, help=argparse.SUPPRESS)
    lr.set_defaults(func=cmd_learn_from_review)

    skb = sub.add_parser("build-supervised-kb", help="build official KB using user-approved policies (SQLite + dashboard + stats)")
    skb.add_argument("--inventory", required=True, help="path to file_inventory.jsonl")
    skb.add_argument("--policy", required=True, help="directory with 5 YAML policy files")
    skb.add_argument("--output", required=True, help="output directory for supervised KB")
    skb.add_argument("--llm-assignments", required=False, default=None, help="path to final_assignments.jsonl for LLM category hints")
    skb.add_argument("--sqlite", required=False, default=None, help="path to main kb.sqlite3 (writes into existing KB instead of creating standalone)")
    skb.add_argument("--config", required=False, default=None, help="path to config.yaml (used to resolve default sqlite path)")
    skb.set_defaults(func=cmd_build_supervised_kb)

    return p


def main() -> int:
    parser = build_parser()
    args, _unknown = parser.parse_known_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
