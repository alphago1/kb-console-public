from __future__ import annotations

from diagnosis.schemas import UserKnowledgeProfile


def check_word_compatibility(profile: UserKnowledgeProfile) -> list[str]:
    notes: list[str] = []

    if ".docx" in str(profile.source_file_types) or "Word" in str(profile.source_file_types):
        notes.append(
            "用户主要使用 Word (.docx) 格式 → 需要 Word-first 文档迁移："
            "LibreOffice 文本提取 + 全文缓存 + Word 兼容的分类流程"
        )
        notes.append(
            "Word 文件不支持 wiki 双链语法 → 源文件保持原格式不变，"
            "AI 生成的内容（wiki cache/reports）可以使用 Markdown，但人类主入口通过 reports 而非 wiki pages"
        )

    if ".md" not in str(profile.source_file_types) and "Markdown" not in str(profile.source_file_types):
        notes.append(
            "用户不使用 Markdown → wiki 层降级为 AI 内部使用，"
            "人类可读产物全部使用用户原生格式或系统生成的报告"
        )

    if profile.maintenance_willingness in ("低", "希望全自动"):
        notes.append(
            "用户维护意愿低 → wiki 页面不要求用户手动维护，所有内容由 AI 自动生成和更新"
        )

    if profile.human_reading_entry in ("打开文件夹浏览文件",):
        notes.append(
            "用户通过文件夹浏览 → 物理文件组织（docs/分类/月份）比 wiki 索引更重要"
        )

    if not notes:
        notes.append("用户工作流与 Karpathy baseline 兼容，无需特殊的 Word-first 适配")

    return notes


def check_report_first_compatibility(profile: UserKnowledgeProfile) -> dict:
    report_types = []
    has_report_need = False

    for output in (profile.preferred_outputs or []):
        if isinstance(output, str) and any(kw in output.lower() for kw in ["报告", "report", "月报", "周报", "季报"]):
            has_report_need = True
            report_types.append(output)

    if has_report_need:
        return {
            "strategy": "report_first",
            "report_types": report_types,
            "wiki_role": "wiki 层降级为报告生成的后台数据源，不作为人类主入口",
            "entry_point": "reports",
        }
    return {
        "strategy": "wiki_first",
        "report_types": report_types,
        "wiki_role": "wiki 作为主入口，报告作为补充产物",
        "entry_point": "wiki",
    }
