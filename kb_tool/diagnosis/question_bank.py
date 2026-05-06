from __future__ import annotations

from .schemas import InterviewQuestion

QUESTIONS: list[dict] = [
    # ═══════════ 使用场景（affects: classification_policy, query_strategy）═══════════
    {
        "question_id": "Q001",
        "question_text": "你建立这个知识库，最主要想解决什么问题？",
        "question_type": "single_choice",
        "options": [
            "整理归档，方便以后查找",
            "发现规律，从过去的记录中学习",
            "辅助写作，积累可成文的素材",
            "构建个人决策和认知系统",
        ],
        "why_this_question": "primary_goal 决定整个知识库的架构取向——归档型要的是分类准确和检索快，认知型要的是跨时间对比和洞察发现，写作型要的是素材关联和质量评估。不同方向的分量完全不同。",
        "affects_fields": ["primary_goal"],
        "affects_components": ["classification_policy", "query_strategy", "report_template"],
    },
    {
        "question_id": "Q002",
        "question_text": "你平时在哪些场景下会去查自己的知识库？请描述最近一次具体场景。",
        "question_type": "open",
        "options": None,
        "why_this_question": "core_scenarios 决定检索优先级的权重分配——做决策前查规则、写作前找素材、复盘时看趋势，不同场景对应的检索策略完全不同。",
        "affects_fields": ["core_scenarios", "query_patterns"],
        "affects_components": ["query_strategy"],
    },
    {
        "question_id": "Q003",
        "question_text": "你的知识主要分布在哪些领域？请列出 3-6 个，并简要描述每个领域包含什么类型的内容。",
        "question_type": "open",
        "options": None,
        "why_this_question": "core_domains 直接决定分类体系的一级分类。如果用户实际关注的领域与系统预设不匹配，整个分类体系都需要重新设计。",
        "affects_fields": ["core_domains"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q004",
        "question_text": "粗略估计，你大概有多少篇文档？以什么格式为主？",
        "question_type": "single_choice",
        "options": [
            "几十篇（<100）",
            "几百篇（100-500）",
            "比较多（500-2000）",
            "很多（>2000）",
        ],
        "why_this_question": "corpus_scale 决定分析策略——小规模可以全量读入深度分析，大规模需要预算制分批压缩。规模差一个数量级，技术方案完全不同。",
        "affects_fields": ["corpus_scale_estimate"],
        "affects_components": ["query_strategy", "organize_schedule"],
    },

    # ═══════════ 维护意愿（affects: organize_schedule）═══════════
    {
        "question_id": "Q005",
        "question_text": "你愿意花多少时间在知识库维护上？",
        "question_type": "single_choice",
        "options": [
            "希望全自动，我只管写文件，系统自己整理",
            "可以每周花几分钟检查一下自动分类结果",
            "愿意定期回顾和调整分类体系",
            "我愿意深度参与知识库的设计和持续迭代",
        ],
        "why_this_question": "maintenance_willingness 决定自动化程度——全自动意味着系统不能依赖用户反馈来修正，深度参与意味着可以建立反馈闭环持续优化。",
        "affects_fields": ["maintenance_willingness"],
        "affects_components": ["organize_schedule"],
    },
    {
        "question_id": "Q006",
        "question_text": "你现在是怎么管理这些文件的？",
        "question_type": "open",
        "options": None,
        "why_this_question": "current_workflow 决定迁移策略。如果用户已有一套手动分类体系，系统需要尽可能兼容而非强行推翻——否则用户不会接受新系统。",
        "affects_fields": ["current_workflow"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q007",
        "question_text": "你主要用哪些格式记录内容？",
        "question_type": "multi_choice",
        "options": [
            ".docx (Word 文档)",
            ".md (Markdown)",
            ".txt (纯文本)",
            "PDF",
            "其他格式",
        ],
        "why_this_question": "source_file_types 决定文本提取和采样策略。Word 需要转换工具，Markdown 可直接读取但需要处理 frontmatter，不同格式的可靠性和提取成本不同。",
        "affects_fields": ["source_file_types"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q008",
        "question_text": "你的文件中包含敏感信息吗？你能接受将文本发送给云端 AI 做分析吗？",
        "question_type": "single_choice",
        "options": [
            "所有内容必须留在本地，不上传任何文本到云端",
            "可以脱敏后上传，但不能包含个人身份信息",
            "可以上传，只要数据不被第三方看到",
            "不关心隐私问题，分析质量第一",
        ],
        "why_this_question": "privacy_level 决定 LLM 调用策略，进而影响分析深度天花板——纯本地模型的分类和洞察能力远弱于云端大模型。这是决定系统能力上限的关键决策。",
        "affects_fields": ["privacy_level"],
        "affects_components": ["classification_policy", "query_strategy", "report_template"],
    },

    # ═══════════ 结构偏好（affects: classification_policy）═══════════
    {
        "question_id": "Q009",
        "question_text": "当你回忆一个文件的位置时，第一反应是'大概是关于 XX 主题的'还是'大概是 XX 时候写的'？",
        "question_type": "single_choice",
        "options": [
            "按主题/领域回忆",
            "按时间回忆",
            "两者差不多",
            "不太确定",
        ],
        "why_this_question": "structure_preference 决定一级分类是按领域（如'产品设计'/'技术笔记'）还是按时间段（如'2025-Q3'/'2026-Q1'）。这是分类体系最根本的设计决策，一旦确定后续很难改。",
        "affects_fields": ["structure_preference"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q010",
        "question_text": "一篇 2025 年写的笔记讨论的是 2023 年的事，你希望它归在哪个时间里？",
        "question_type": "single_choice",
        "options": [
            "归在内容描述的日期（2023 年）",
            "归在文件创建/修改的时间（2025 年）",
            "两个时间都需要标注",
            "不太关心时间维度",
        ],
        "why_this_question": "time_axis_preference 决定时间轴策略。复盘型用户关心内容时间（那件事什么时候发生的），项目型用户关心修改时间（最新方案是什么版本）。选错会导致用户永远找不到想找的文件。",
        "affects_fields": ["time_axis_preference"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q011",
        "question_text": "对于不同类型的内容——自己写的原创思考、摘录别人的观点、AI 帮你生成的总结——你希望它们放在一起还是分开？",
        "question_type": "single_choice",
        "options": [
            "放在一起，标注来源类型就行",
            "原创和摘录可以在一起，AI 生成的内容单独放",
            "每种来源类型都应该有独立空间",
            "没想过这个问题",
        ],
        "why_this_question": "source_type_policy 决定分类体系是否需要第二维度来区分内容来源。把外部摘录和原创思考混在一起会污染认知画像——AI 可能把别人的观点当成用户的认知。",
        "affects_fields": ["source_type_policy"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q012",
        "question_text": "哪些类型的文件你不希望进入知识库？",
        "question_type": "multi_choice",
        "options": [
            "外部讲义或课件（不是自己的内容）",
            "电子书",
            "合同和证件类文件",
            "简历和求职材料",
            "过时的参考资料",
            "纯下载或转载的内容",
            "工作相关的临时文件",
        ],
        "why_this_question": "exclusion_policy 决定排除规则的粒度。排错比漏分类的伤害更大——一本电子书被当成用户的原创思考放进来，会严重污染后续的所有分析结果。",
        "affects_fields": ["exclusion_policy"],
        "affects_components": ["classification_policy"],
    },

    # ═══════════ 消费入口（affects: query_strategy, report_template）═══════════
    {
        "question_id": "Q013",
        "question_text": "你最可能怎么浏览知识库的内容？",
        "question_type": "single_choice",
        "options": [
            "打开文件夹一层层浏览",
            "用搜索框搜关键词",
            "让 AI 助手帮我找",
            "看 Dashboard 统计大盘",
        ],
        "why_this_question": "human_reading_entry 决定检索界面的重心——浏览型用户需要好的目录结构和导航，搜索型用户需要精准的检索结果排序，AI 型用户需要好的自然语言理解。",
        "affects_fields": ["human_reading_entry"],
        "affects_components": ["query_strategy", "report_template"],
    },
    {
        "question_id": "Q014",
        "question_text": "你希望 AI 助手（如 Claude、ChatGPT）怎么使用你的知识库？",
        "question_type": "single_choice",
        "options": [
            "每次对话时实时搜索相关内容",
            "定期生成一个打包好的 Context Bundle，对话时直接丢进去",
            "两者都要",
            "不确定，还没想过这个场景",
        ],
        "why_this_question": "ai_reading_entry 决定 MCP 工具和 Context Bundle 的设计权重。实时搜索需要好的 chunk 检索和工具描述，打包模式需要好的内容筛选和定期更新机制。",
        "affects_fields": ["ai_reading_entry"],
        "affects_components": ["query_strategy", "organize_schedule"],
    },
    {
        "question_id": "Q015",
        "question_text": "你过去在知识库里搜索时，最常见的是哪种情况？",
        "question_type": "multi_choice",
        "options": [
            "找一个具体文件（我知道它大概叫什么）",
            "找某个时间段内的所有相关内容",
            "对比不同时期的观点或数据变化",
            "找出某个反复出现的主题或模式",
            "找出有潜力展开写作的素材",
        ],
        "why_this_question": "query_patterns 决定搜索架构中不同检索模式的权重——精确匹配、时间范围查询、跨时间对比、主题聚类、质量评估，每一种对应的工具调用链不同。",
        "affects_fields": ["query_patterns"],
        "affects_components": ["query_strategy"],
    },

    # ═══════════ 输出偏好（affects: report_template）═══════════
    {
        "question_id": "Q016",
        "question_text": "你最想要哪些类型的报告和产出？",
        "question_type": "multi_choice",
        "options": [
            "每周整理摘要（这周新入库了什么）",
            "月度回顾报告（这个月的主要变化和发现）",
            "跨时间认知演化报告（长期趋势和信念变化）",
            "知识盲区提示（你还没关注但应该关注的）",
            "写作素材汇总（可以展开成文的内容候选）",
            "个人画像报告（你的思维模式和关注偏好）",
            "Dashboard 可视化大盘",
        ],
        "why_this_question": "preferred_outputs 直接决定需要启用哪些分析组件。如果用户只想要周报，就不需要构建认知演化追踪和盲区检测这些重组件。",
        "affects_fields": ["preferred_outputs", "enabled_components", "disabled_components"],
        "affects_components": ["report_template"],
    },
    {
        "question_id": "Q017",
        "question_text": "你更偏好哪种报告风格？",
        "question_type": "single_choice",
        "options": [
            "深度优先：不常看，但每次要看到有价值的洞察",
            "频率优先：每周有简短更新就好",
            "都要：日常摘要 + 深度季报",
            "不确定，先看看系统能产出什么",
        ],
        "why_this_question": "report_preferences 决定报告的频率、粒度和叙事风格——是每次写 5000 字深度分析还是每周 500 字摘要。这直接影响 LLM 调用频率和 token 成本。",
        "affects_fields": ["report_preferences"],
        "affects_components": ["report_template", "organize_schedule"],
    },

    # ═══════════ 深度追问（场景化追问，仅在高优先级 gap 时触发）═══════════
    {
        "question_id": "Q018",
        "question_text": "你提到的几个主要领域之间有关联吗？比如一个领域的记录会影响另一个领域的决策吗？",
        "question_type": "open",
        "options": None,
        "why_this_question": "领域交叉关系影响分类体系是否需要 cross-reference 机制。如果两个领域之间存在引用关系，检索时需要跨分类关联查询。",
        "affects_fields": ["core_domains"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q019",
        "question_text": "在你记录最多的那个领域里，一篇典型的内容通常包含哪些结构？比如是自由叙述、结构化字段（时间/数据/结论）、还是两者混合？",
        "question_type": "multi_choice",
        "options": [
            "自由叙述——想到什么写什么，没有固定格式",
            "结构化记录——包含固定的字段或模板",
            "半结构化——部分是固定的，部分自由发挥",
            "情况不一，不同场景用不同格式",
        ],
        "why_this_question": "内容的内部结构决定标签抽取策略和报告模板设计。结构化内容可以自动化抽取字段，自由叙述需要 LLM 深度理解。两种策略的成本差一个数量级。",
        "affects_fields": ["core_domains"],
        "affects_components": ["classification_policy", "report_template"],
    },
    {
        "question_id": "Q020",
        "question_text": "你是否希望知识库能帮你发现'你在同一类问题上反复出现同样的模式'？比如某个你多次提到但似乎一直没解决的问题？",
        "question_type": "single_choice",
        "options": [
            "非常需要，这是我最想要的功能之一",
            "有一定兴趣，可以作为附加功能",
            "不太需要，我只是想整理文件",
        ],
        "why_this_question": "对反复模式的兴趣程度决定是否启用 recurrence 检测和认知演化追踪——这两个是最消耗 LLM token 的分析组件，只在用户有明确需求时才启用。",
        "affects_fields": ["preferred_outputs"],
        "affects_components": ["report_template", "query_strategy"],
    },
    {
        "question_id": "Q021",
        "question_text": "你的内容创作习惯是怎样的？",
        "question_type": "single_choice",
        "options": [
            "碎片记录——有想法就记下来，以后再整理成文",
            "完整写作——想清楚了再一次性写成完整内容",
            "两者都有，不同场景不同习惯",
        ],
        "why_this_question": "创作习惯决定写作候选的推荐频率和标准。碎片型用户需要高频推荐（每周提醒'这些碎片可以串起来了'），完整型用户需要低频深度推荐（每月提醒'这个话题可以展开'）。",
        "affects_fields": ["query_patterns", "preferred_outputs"],
        "affects_components": ["report_template", "organize_schedule"],
    },
    {
        "question_id": "Q022",
        "question_text": "你是否有过'写了但现在不太想再看到'的内容？比如某段时间的情绪宣泄，事后觉得不太有保留价值？",
        "question_type": "single_choice",
        "options": [
            "是，有些内容不想反复被翻出来",
            "没有，所有写过的内容都愿意保留",
            "不确定，想先看看系统会怎么处理这些内容",
        ],
        "why_this_question": "影响 exclusion_policy 中敏感/情绪化内容的处理策略——是降权检索、标记为低优先级、还是完全排除。这不只是技术决策，也是隐私和情感保护。",
        "affects_fields": ["exclusion_policy"],
        "affects_components": ["classification_policy", "query_strategy"],
    },
    {
        "question_id": "Q023",
        "question_text": "你希望系统多久告诉你一次'你可能没意识到的事'？比如发现了新的认知矛盾，或一个长期没进展的话题出现了转机？",
        "question_type": "single_choice",
        "options": [
            "有新发现就随时通知我",
            "每周整理时顺带看看",
            "每月一次深度分析就够了",
            "不需要，我自己手动触发即可",
        ],
        "why_this_question": "洞察推送频率直接决定 LLM 调用量和系统运行成本。高频推送需要每次扫描都跑全量对比分析，低频则可以在月报中集中呈现。",
        "affects_fields": ["report_preferences"],
        "affects_components": ["organize_schedule", "report_template"],
    },
    {
        "question_id": "Q024",
        "question_text": "对于你的记录中反复提到但还没有结论的问题（如'是否应该转型'、'某项目是否值得继续投入'），你希望系统怎么处理？",
        "question_type": "single_choice",
        "options": [
            "持续追踪——有新证据时提醒我",
            "列在侧边栏作为'开放问题清单'，我自己想看时再看",
            "定期汇总相关思考，但不主动推送",
            "不需要特别处理",
        ],
        "why_this_question": "开放问题的追踪策略决定 cognition_snapshot 的演化追踪设计。active tracking 需要每次扫描都做信念 diff 对比，成本高但价值大。",
        "affects_fields": ["preferred_outputs"],
        "affects_components": ["query_strategy", "report_template"],
    },
    {
        "question_id": "Q025",
        "question_text": "你更偏好报告给出确定性的结论，还是给出多个可能性加证据让你自行判断？",
        "question_type": "single_choice",
        "options": [
            "确定性结论——简洁明确，告诉我就行",
            "多个可能性加证据——我自己来判断",
            "两者结合——主要结论确定，次要发现标注不确定性",
        ],
        "why_this_question": "报告风格偏好决定 LLM 输出的温度和格式。确定性风格需要低温度 + 结构化输出模板，探索性风格需要中温度 + 开放式分析框架。",
        "affects_fields": ["report_preferences"],
        "affects_components": ["report_template"],
    },
    {
        "question_id": "Q026",
        "question_text": "你的文件主要是中文、英文、还是混合？",
        "question_type": "single_choice",
        "options": [
            "主要是中文",
            "中英文混合较多",
            "有大量纯英文内容",
            "涉及其他语言",
        ],
        "why_this_question": "语言分布影响分词策略、FTS5 tokenizer 选择、和 LLM prompt 语言设计。混合语言文档的搜索召回率和分类准确率需要针对性调优。",
        "affects_fields": ["source_file_types"],
        "affects_components": ["query_strategy", "classification_policy"],
    },
    {
        "question_id": "Q027",
        "question_text": "如果一个分类下只有很少几篇文档，你倾向于合并到更大的分类还是保留它？",
        "question_type": "single_choice",
        "options": [
            "合并——分类太少没有意义",
            "保留——以后可能会增加",
            "看内容是否足够独特再决定",
        ],
        "why_this_question": "影响分类体系的最小粒度阈值。合并型用户需要系统主动建议合并方案，保留型用户需要更宽松的新建分类阈值。",
        "affects_fields": ["structure_preference"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q028",
        "question_text": "你是否愿意让系统自动重命名你的文件？比如把'未命名文档.docx'改为'2025-03-15_主题摘要_abc123.docx'这种含时间和内容摘要的格式？",
        "question_type": "single_choice",
        "options": [
            "可以，自动重命名更整洁",
            "不行，文件名不能改",
            "可以重命名，但保留原标题作为备注",
        ],
        "why_this_question": "文件重命名权限直接影响 organize_schedule——如果用户不允许改名，系统只能靠数据库映射管理路径，物理文件组织无法优化。",
        "affects_fields": ["current_workflow"],
        "affects_components": ["organize_schedule"],
    },
    {
        "question_id": "Q029",
        "question_text": "你收藏的外部文章、别人发给你的资料、AI 帮你生成的总结——它们和你的原创内容应该放在一起还是分开？",
        "question_type": "single_choice",
        "options": [
            "严格分开——原创和非原创不能混在一起",
            "可以放在一起，但必须标注来源",
            "外部资料一般不需要进知识库，除非我特别标注",
        ],
        "why_this_question": "这是 source_type_policy 中最影响认知分析质量的决策。外部资料和原创混在一起，认知画像会被污染——AI 可能把别人的观点当成用户的认知变化。",
        "affects_fields": ["source_type_policy"],
        "affects_components": ["classification_policy"],
    },
    {
        "question_id": "Q030",
        "question_text": "回顾你现有的知识管理方式，你觉得最大的痛点是什么？如果可以加一个功能，你最想要什么？",
        "question_type": "open",
        "options": None,
        "why_this_question": "开放收尾问题，用于捕捉前面 29 个结构化问题可能遗漏的真实需求。用户主动提出的'最想要的'往往直接决定 MVP 的优先级排序。",
        "affects_fields": ["preferred_outputs", "primary_goal"],
        "affects_components": ["report_template", "query_strategy"],
    },

]


def get_question(question_id: str) -> InterviewQuestion | None:
    for q in QUESTIONS:
        if q["question_id"] == question_id:
            return InterviewQuestion(**q)
    return None


def get_all_questions() -> list[InterviewQuestion]:
    return [InterviewQuestion(**q) for q in QUESTIONS]


def get_questions_by_field(field_name: str) -> list[InterviewQuestion]:
    return [InterviewQuestion(**q) for q in QUESTIONS if field_name in q.get("affects_fields", [])]


def get_questions_by_component(component: str) -> list[InterviewQuestion]:
    return [InterviewQuestion(**q) for q in QUESTIONS if component in q.get("affects_components", [])]
