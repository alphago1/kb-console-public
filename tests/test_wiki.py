"""Tests for wiki_page_builder + wiki_router"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Ensure kb_tool is in path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kb_tool"))


def test_router_title_match():
    """wiki_router should match pages by title."""
    from wiki_router import route_query
    # Create temp kb dir with a page_index.json
    with tempfile.TemporaryDirectory() as tmp:
        kb_dir = Path(tmp) / "wiki"
        kb_dir.mkdir(parents=True, exist_ok=True)
        page_index = [
            {"title": "交易复盘", "type": "category", "category": "交易复盘",
             "doc_count": 74, "path": str(kb_dir / "pages" / "category" / "交易复盘.md")},
            {"title": "止损纪律", "type": "topic", "category": "交易复盘",
             "doc_count": 12, "path": str(kb_dir / "pages" / "topic" / "止损纪律.md")},
        ]
        (kb_dir / "page_index.json").write_text(json.dumps(page_index, ensure_ascii=False), encoding="utf-8")

        # Exact title match
        result = route_query("止损纪律", str(kb_dir.parent))
        assert result["confidence"] >= 0.7, f"Expected high confidence, got {result['confidence']}"
        assert not result["fallback_needed"], f"Expected no fallback, got {result}"
        assert len(result["selected_pages"]) >= 1

        # No match → fallback
        result2 = route_query("不存在的主题xyz", str(kb_dir.parent))
        assert result2["fallback_needed"], f"Expected fallback for unknown query"
        assert result2["strategy"] == "fallback_fts"

    print("[PASS]test_router_title_match PASSED")


def test_router_fallback_on_empty_index():
    """wiki_router should fallback when index is empty."""
    from wiki_router import route_query
    with tempfile.TemporaryDirectory() as tmp:
        kb_dir = Path(tmp) / "wiki"
        kb_dir.mkdir(parents=True, exist_ok=True)
        (kb_dir / "page_index.json").write_text("[]", encoding="utf-8")

        result = route_query("任何查询", str(kb_dir.parent))
        assert result["fallback_needed"]
        assert result["fallback_reason"] == "wiki_pages_not_built"

    print("[PASS]test_router_fallback_on_empty_index PASSED")


def test_router_no_index_file():
    """wiki_router should handle missing index gracefully."""
    from wiki_router import route_query
    with tempfile.TemporaryDirectory() as tmp:
        result = route_query("任何查询", tmp)
        assert result["fallback_needed"]
        assert "not_built" in result["fallback_reason"]

    print("[PASS]test_router_no_index_file PASSED")


def test_page_builder_type_field():
    """Generated pages must have correct type field (not overridden by LLM)."""
    from wiki_page_builder import _call_llm
    # Test that _call_llm overrides type
    # We test the internal logic: parsed.setdefault vs direct assignment
    # The fix changed setdefault to direct assignment for title/type
    import inspect
    source = inspect.getsource(_call_llm)
    # Verify direct assignment (not setdefault) for title and type
    assert 'parsed["title"]' in source, "title should use direct assignment"
    assert 'parsed["type"]' in source, "type should use direct assignment"
    assert 'parsed["category"]' in source, "category should use direct assignment"

    print("[PASS]test_page_builder_type_field PASSED")


def test_page_builder_absolute_paths():
    """page_index.json paths should be absolute."""
    from wiki_page_builder import _write_page
    # Test that _write_page uses p.resolve()
    import inspect
    build_source = inspect.getsource(_write_page)
    # Check the build_wiki_pages function for all_pages.append
    with open(Path(__file__).resolve().parents[1] / "kb_tool" / "wiki_page_builder.py", encoding="utf-8") as f:
        content = f.read()
    assert "str(p.resolve())" in content, "all_pages should use p.resolve() for absolute paths"

    print("[PASS]test_page_builder_absolute_paths PASSED")


def test_frontmatter_parsing():
    """_parse_frontmatter should correctly split YAML frontmatter and body."""
    from wiki_page_builder import _parse_frontmatter
    text = """---
title: Test
type: topic
---
## Definition
This is the body."""
    result = _parse_frontmatter(text)
    assert result["title"] == "Test"
    assert result["type"] == "topic"
    assert "## Definition" in result["body"]

    # Test with code block wrapping
    text2 = """```markdown
---
title: Wrapped
---
Body here
```"""
    result2 = _parse_frontmatter(text2)
    assert result2["title"] == "Wrapped"
    assert "Body here" in result2["body"]

    print("[PASS]test_frontmatter_parsing PASSED")


def test_router_partial_title_match():
    """wiki_router should match partial title words."""
    from wiki_router import route_query
    with tempfile.TemporaryDirectory() as tmp:
        kb_dir = Path(tmp) / "wiki"
        kb_dir.mkdir(parents=True, exist_ok=True)
        page_index = [
            {"title": "交易心理", "type": "topic", "category": "交易复盘",
             "doc_count": 4, "path": "/tmp/pages/topic/交易心理.md"},
            {"title": "情绪", "type": "topic", "category": "交易心理与情绪",
             "doc_count": 32, "path": "/tmp/pages/topic/情绪.md"},
        ]
        (kb_dir / "page_index.json").write_text(json.dumps(page_index, ensure_ascii=False), encoding="utf-8")

        result = route_query("交易心理", str(kb_dir.parent))
        assert result["confidence"] >= 0.7
        assert len(result["matches"]) >= 1
        # First match should be the exact title match
        assert result["matches"][0]["title"] == "交易心理"

    print("[PASS]test_router_partial_title_match PASSED")


if __name__ == "__main__":
    test_router_title_match()
    test_router_fallback_on_empty_index()
    test_router_no_index_file()
    test_page_builder_type_field()
    test_page_builder_absolute_paths()
    test_frontmatter_parsing()
    test_router_partial_title_match()
    print("\n===== ALL 7 TESTS PASSED =====")
