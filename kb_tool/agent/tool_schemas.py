from __future__ import annotations


def get_tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": "搜索知识库文档，支持关键词与月份、分类过滤",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "month_start": {"type": ["string", "null"]},
                        "month_end": {"type": ["string", "null"]},
                        "primary_category": {"type": ["string", "null"]},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_chunks",
                "description": "在文档分块中进行全文检索，返回证据片段",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "month_start": {"type": ["string", "null"]},
                        "month_end": {"type": ["string", "null"]},
                        "filters": {"type": ["object", "null"]},
                        "limit": {"type": "integer", "default": 10},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_document",
                "description": "按 document_id 获取文档详情",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "integer"},
                    },
                    "required": ["document_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "compare_periods",
                "description": "比较时间段内某主题的变化",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_month": {"type": "string"},
                        "end_month": {"type": "string"},
                        "topic": {"type": "string"},
                    },
                    "required": ["start_month", "end_month", "topic"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "summarize_month",
                "description": "聚合某个月的分类与重点摘要",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "month": {"type": "string"},
                    },
                    "required": ["month"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_writing_candidates",
                "description": "查找写作潜力高的文档候选",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "month_start": {"type": ["string", "null"]},
                        "month_end": {"type": ["string", "null"]},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "cluster_project_ideas",
                "description": "聚合并统计反复出现的项目想法标签",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "month_start": {"type": ["string", "null"]},
                        "month_end": {"type": ["string", "null"]},
                        "limit": {"type": "integer", "default": 30},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_report",
                "description": "生成报告文件，仅允许写入 kb_out/reports",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "report_type": {"type": "string"},
                        "period": {"type": "string"},
                        "topic": {"type": ["string", "null"]},
                    },
                    "required": ["report_type", "period"],
                },
            },
        },
    ]
