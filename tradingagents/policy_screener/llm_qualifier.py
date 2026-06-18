"""LLM 定性打分器。

让 LLM 从标的与政策主题的关联，推断"机构关注度上升但尚未重仓"等
定性信号，输出 0-100 分 + 一句话理由。

LLM 不可用（client 为 None 或调用抛异常）时降级为中性分 50。
不与现有 fund_news_analyst 混用：本模块只产出结构化分数，不写报告。
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

from .models import Candidate

_SYSTEM_PROMPT = (
    "你是一位擅长 A 股与公募基金的资深机构配置分析师。"
    "给定一只标的及其所属国家政策主题，判断当前'主力资金/机构资金"
    "尚未大规模介入'的程度（越未介入越高分），并给出一句话理由。"
    "只输出 JSON，格式：{\"score\": 0到100的整数, \"reason\": \"不超过30字\"}。"
)


def parse_llm_score(text: str) -> Tuple[int, str]:
    """从 LLM 文本解析 score/reason。

    解析失败或越界返回中性 (50, 默认理由)。
    """
    try:
        # 容错：可能文本含额外说明，尝试截取首个 {...}
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        obj = json.loads(text)
        score = int(round(float(obj["score"])))
        score = max(0, min(100, score))
        reason = str(obj.get("reason", "")).strip() or "无理由"
        return score, reason
    except Exception:
        return 50, "LLM 响应解析失败，采用中性分"


def qualify(candidate: Candidate, llm) -> Tuple[int, str]:
    """对单只候选标的做 LLM 定性打分。

    Args:
        candidate: 候选标的。
        llm: langchain 风格 LLM 对象（有 invoke 方法）。None 表示不可用。

    Returns:
        (score 0-100, reason 字符串)。LLM 不可用时返回 (50, 默认理由)。
    """
    if llm is None:
        return 50, "LLM 不可用，采用中性分"

    user_prompt = (
        f"标的：{candidate.name}（{candidate.ticker}），"
        f"所属政策主题：{candidate.theme}，板块：{candidate.sector}，"
        f"类型：{'基金/ETF' if candidate.is_fund else '股票'}。"
        f"请判断主力资金尚未大规模介入的程度并输出 JSON。"
    )

    try:
        messages = [
            ("system", _SYSTEM_PROMPT),
            ("human", user_prompt),
        ]
        resp = llm.invoke(messages)
        content = getattr(resp, "content", str(resp))
        return parse_llm_score(str(content))
    except Exception:
        return 50, "LLM 调用失败，采用中性分"