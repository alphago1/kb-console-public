"""
Audit: Karpathy Baseline + Adaptation Engine
"""
import sys, os, json, yaml
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "kb_tool"))

BUGS = 0

def check(name, condition, detail=""):
    global BUGS
    if condition:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} — {detail}")
        BUGS += 1

print("=" * 60)
print("1. YAML 文件名 vs component_id 映射")
print("=" * 60)

from karpathy_baseline.baseline_generator import generate_baseline, _KARPATHY_DEFAULTS, _COMPONENTS_DIR

components = generate_baseline()
comp_dir = Path(_COMPONENTS_DIR)
yaml_files = set(f.name for f in comp_dir.glob("*.yaml"))

print(f"  Component IDs: {len(components)}")
print(f"  YAML files: {len(yaml_files)}")

# Check YAML loading: each component finds EITHER exact match OR layer-level karpathy_{layer}.yaml
for c in components:
    exact = f"{c.component_id.replace('.', '_')}.yaml"
    layer = f"karpathy_{c.layer}.yaml"
    found = (exact in yaml_files) or (layer in yaml_files)
    check(f"YAML source for {c.component_id}", found,
          f"neither {exact} nor {layer} found")

# Count matched YAMLs (karpathy layer YAMLs match multiple components)
layer_yamls = {f"karpathy_{c.layer}.yaml" for c in components}
unmatched_yamls = [f for f in yaml_files if f not in layer_yamls and f not in {f"{c.component_id.replace('.', '_')}.yaml" for c in components}]
if unmatched_yamls:
    print(f"\n  ℹ️  {len(unmatched_yamls)} project-specific YAMLs (not per-component): {sorted(unmatched_yamls)}")

print(f"\n{'=' * 60}")
print("2. Profile ↔ Adaptation Rule 字段值对齐")
print("=" * 60)

from diagnosis.schemas import UserKnowledgeProfile
from karpathy_baseline.adaptation_rules import adapt_component, RULES

# Check which fields adaptation rules actually reference
import re
rule_src = (PROJECT / "kb_tool" / "karpathy_baseline" / "adaptation_rules.py").read_text(encoding="utf-8")
rule_fields_used = set()
for field in ["maintenance_willingness", "structure_preference", "human_reading_entry",
               "preferred_outputs", "source_file_types", "primary_goal", "report_preferences",
               "time_axis_preference", "source_type_policy"]:
    if f'_val(p, "{field}")' in rule_src:
        rule_fields_used.add(field)

print(f"  Rules reference {len(rule_fields_used)} profile fields: {sorted(rule_fields_used)}")

# Check each rule's condition against profile field types
for i, (condition, action, reason) in enumerate(RULES):
    # Basic sanity: does the rule check fields that exist in UserKnowledgeProfile?
    check(f"Rule {i+1} has action and reason", bool(action and reason))

# Test with actual profile JSON
profile_path = PROJECT / "kb_tool" / "kb_out" / "diagnosis" / "session_001" / "profile_draft.json"
if profile_path.exists():
    profile = UserKnowledgeProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
    print(f"\n  Profile loaded: primary_goal='{profile.primary_goal}', "
          f"maintenance='{profile.maintenance_willingness}', "
          f"structure='{profile.structure_preference}'")

    # Check which fields have non-empty values
    for f in profile.field_names():
        val = getattr(profile, f, None)
        has_val = val and val != [] and val != {} and val != ""
        if not has_val:
            print(f"  ⚠️  Profile field '{f}' is empty — rules depending on it won't fire")

    # Check each adaptation rule against profile
    print(f"\n  Adaptation results:")
    actions = {}
    for c in components:
        from karpathy_baseline.adaptation_rules import _match_rule
        matched = _match_rule(profile, c)
        action = matched[0] if matched else "KEEP (no rule matched)"
        reason = matched[1] if matched else ""
        actions[c.component_id] = (action, reason)
        if action != "KEEP":
            print(f"    {action}: {c.component_id} — {reason}")
else:
    print(f"  ⚠️  Profile not found at {profile_path}")

print(f"\n{'=' * 60}")
print("3. CLI 命令解析")
print("=" * 60)

import subprocess
PYTHON = str(PROJECT / ".venv" / "Scripts" / "python.exe")
MAIN = str(PROJECT / "kb_tool" / "main.py")
CWD = str(PROJECT / "kb_tool")

for cmd_name in ["karpathy-baseline-generate", "karpathy-adapt"]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [PYTHON, "-u", MAIN, cmd_name, "--help"],
        cwd=CWD, capture_output=True, text=True, timeout=10, env=env
    )
    check(f"{cmd_name} --help 解析成功", r.returncode == 0, r.stderr[:200])

print(f"\n{'=' * 60}")
print("4. 模块导入完整性")
print("=" * 60)

modules = [
    "karpathy_baseline",
    "karpathy_baseline.baseline_schema",
    "karpathy_baseline.baseline_generator",
    "karpathy_baseline.adaptation_rules",
    "karpathy_baseline.compatibility",
    "karpathy_baseline.diff_generator",
    "diagnosis",
    "diagnosis.schemas",
    "diagnosis.question_bank",
    "diagnosis.inference",
    "diagnosis.gap_analyzer",
    "diagnosis.interview_planner",
    "diagnosis.profile_builder",
]
for mod in modules:
    try:
        __import__(mod)
        check(f"import {mod}", True)
    except Exception as e:
        check(f"import {mod}", False, str(e)[:200])

print(f"\n{'=' * 60}")
print("5. 交付物完整性")
print("=" * 60)

blueprint_dir = PROJECT / "kb_tool" / "kb_out" / "blueprints" / "session_001"
expected_files = [
    "adaptation_diff.md",
    "adapted_knowledge_blueprint.md",
    "component_plan.yaml",
    "word_compatibility_plan.md",
    "wiki_cache_policy.yaml",
    "report_first_policy.yaml",
]
for fname in expected_files:
    exists = (blueprint_dir / fname).exists()
    check(f"Blueprint: {fname}", exists)

print(f"\n{'=' * 60}")
print("6. Diagnosis 流程完整性")
print("=" * 60)

diag_dir = PROJECT / "kb_tool" / "kb_out" / "diagnosis" / "session_001"
for fname in ["profile_draft.json", "interview_plan.json"]:
    exists = (diag_dir / fname).exists()
    check(f"Diagnosis: {fname}", exists)

# Check profile_draft has confidence_map
if (diag_dir / "profile_draft.json").exists():
    profile_data = json.loads((diag_dir / "profile_draft.json").read_text(encoding="utf-8"))
    conf_map = profile_data.get("confidence_map", {})
    filled = sum(1 for v in conf_map.values() if v > 0)
    check(f"Profile has {filled} fields with confidence > 0", filled > 5,
          f"only {filled} fields filled, profile may be too sparse")

# Check interview_plan has questions
if (diag_dir / "interview_plan.json").exists():
    plan_data = json.loads((diag_dir / "interview_plan.json").read_text(encoding="utf-8"))
    n_questions = len(plan_data.get("selected_questions", []))
    check(f"Interview plan has {n_questions} questions", n_questions > 0,
          "no questions selected — gap analysis may be too strict or profile too complete")

print(f"\n{'=' * 60}")
print(f"SUMMARY: {BUGS} bugs found")
print("=" * 60)
sys.exit(0 if BUGS == 0 else 1)
