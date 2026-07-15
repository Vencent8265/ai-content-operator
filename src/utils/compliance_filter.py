"""
内容合规过滤器
──────────────
在文章生成后、审核前，对内容进行自动化合规检查。
返回风险标记列表，供审核 Agent 和人工审核参考。
"""

import re
from dataclasses import dataclass, field


# ══════════════════════════════════════════════════════════════
# AI 内容禁区清单
# ══════════════════════════════════════════════════════════════

# 高危词：直接触发红色标记，必须人工复核
HIGH_RISK_WORDS: list[str] = [
    "稳赚", "保证收益", "日入", "月入", "躺赚",
    "包治", "根治", "特效药", "秘方",
    "征信修复", "洗白", "刷单",
    "内幕消息", "稳赢",
]

# 敏感词：触发黄色标记，建议修改
SENSITIVE_WORDS: list[str] = [
    "取代人类", "灭绝", "毁灭",
    "泄露隐私", "监控每个人",
    "洗脑",
]

# AI 内容特定的合规关注点
AI_CONTENT_FLAGS: dict[str, str] = {
    "医疗诊断": "声称 AI 可以替代医生诊断",
    "金融预测": "声称可以准确预测股票/币价",
    "就业恐慌": "夸大 AI 导致大规模失业",
    "未授权引用": "引用具体论文/报告但未注明来源",
    "技术夸大": "声称某项技术已完美解决所有问题",
}


@dataclass
class ComplianceResult:
    """合规检查结果"""
    passed: bool = True
    risk_level: str = "low"   # "low" | "medium" | "high"
    flags: list[str] = field(default_factory=list)    # 人类可读的风险描述
    suggestions: list[str] = field(default_factory=list)  # 修改建议


def check_compliance(title: str, body: str) -> ComplianceResult:
    """
    对文章标题和正文进行合规检查。

    Returns:
        ComplianceResult: 包含风险等级、标记列表、修改建议
    """
    result = ComplianceResult()
    full_text = f"{title}\n{body}"

    # ── 1. 高危词扫描 ──
    high_hits = []
    for word in HIGH_RISK_WORDS:
        if word in full_text:
            high_hits.append(word)

    if high_hits:
        result.risk_level = "high"
        result.passed = False
        result.flags.append(f"检测到高危词: {', '.join(high_hits)}")
        result.suggestions.append("请移除所有高危敏感词，这些词可能触发平台审核或封号")

    # ── 2. 敏感词扫描 ──
    sensitive_hits = []
    for word in SENSITIVE_WORDS:
        if word in full_text:
            sensitive_hits.append(word)

    if sensitive_hits and result.risk_level != "high":
        result.risk_level = "medium"
        result.flags.append(f"检测到敏感词: {', '.join(sensitive_hits)}")
        result.suggestions.append("建议替换敏感表述，使用更中性的语言")

    # ── 3. AI 内容特定检查 ──
    for topic, description in AI_CONTENT_FLAGS.items():
        if topic in full_text:
            # 用简单的启发式规则判断是否真正触发了问题
            # 这里不做精确语义判断（那是 LLM 的事），只做关键词匹配
            result.flags.append(f"[AI内容] 涉及「{topic}」: {description}")

    # ── 4. 基础格式检查 ──
    if len(title) > 50:
        result.flags.append("标题超过 50 字，抖音推荐 15-30 字")
        result.suggestions.append("建议缩短标题到 30 字以内")
    if len(title) < 5:
        result.flags.append("标题过短（< 5 字），建议 15-30 字")

    if len(body) < 200:
        result.flags.append("正文过短（< 200 字），建议 300-1000 字以获取更好推荐")

    # ── 5. 链接检测 ──
    urls = re.findall(r'https?://[^\s]+', full_text)
    if urls:
        result.flags.append(f"包含 {len(urls)} 个外部链接，请确认来源可靠")
        result.suggestions.append("抖音对带链接的内容有限流风险，建议用「评论区见」代替直接放链接")

    return result


def check_batch(contents: list[tuple[str, str]]) -> list[ComplianceResult]:
    """批量检查"""
    return [check_compliance(title, body) for title, body in contents]
