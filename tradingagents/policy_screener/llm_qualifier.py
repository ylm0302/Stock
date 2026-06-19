"""LLM 定性打分器 + 多空辩论 + 买入意愿星级。

流程：
1. qualify()        — 初筛定性分（0-100）+ 一句话理由（快速，每只标的都跑）
2. debate_and_verdict() — 对通过初筛的标的做多空辩论 → 买入意愿星级（1-5★）

LLM 不可用时全部降级为中性分/默认输出，不抛异常。
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Tuple

from .models import Candidate, ScoredCandidate

logger = logging.getLogger(__name__)

# ── 定性打分 Prompt ───────────────────────────────────────────────

_QUALIFY_SYSTEM = (
    "你是一位擅长 A 股与公募基金的资深机构配置分析师。"
    "给定一只标的及其所属国家政策主题，判断当前'主力资金/机构资金"
    "尚未大规模介入'的程度（越未介入越高分），并给出一句话理由。"
    "只输出 JSON，格式：{\"score\": 0到100的整数, \"reason\": \"不超过30字\"}。"
)

# ── 多空辩论 Prompt ───────────────────────────────────────────────

_DEBATE_SYSTEM = """你是一位 A 股专业投研分析师，需要对一只标的进行"多空辩论"并给出最终买入意愿评级。

## 辩论规则
- 多方（Bull）：从政策支持、行业趋势、估值低位、技术形态等角度给出买入理由
- 空方（Bear）：从风险因素、竞争压力、估值泡沫、宏观逆风等角度给出看空理由
- 每方观点不超过 60 字，需具体，不能空泛

## 买入意愿星级定义
- ⭐⭐⭐⭐⭐ 5星：强烈推荐，当前是极佳买点，风险收益比极优
- ⭐⭐⭐⭐   4星：推荐买入，逻辑清晰，可适量建仓
- ⭐⭐⭐     3星：可以关注，逻辑成立但存在一定不确定性，轻仓试探
- ⭐⭐       2星：谨慎观望，空方论据有力，暂不建议买入
- ⭐         1星：不建议买入，风险大于机会

## 输出格式（仅输出 JSON，不要有其他文字）
{
  "bull": "多方观点，不超过60字",
  "bear": "空方观点，不超过60字",
  "verdict": "综合结论，说明是否建议买入及理由，不超过60字",
  "stars": 1到5的整数
}"""


def parse_llm_score(text: str) -> Tuple[int, str]:
    """从 LLM 文本解析 score/reason。解析失败返回中性 (50, 默认理由)。"""
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
        obj = json.loads(text)
        score = int(round(float(obj["score"])))
        score = max(0, min(100, score))
        reason = str(obj.get("reason", "")).strip() or "无理由"
        return score, reason
    except Exception:
        return 50, "LLM 响应解析失败，采用中性分"


def qualify(candidate: Candidate, llm) -> Tuple[int, str]:
    """对单只候选标的做 LLM 定性打分（轻量级，每只都跑）。

    Returns:
        (score 0-100, reason)。LLM 不可用时返回 (50, 默认理由)。
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
        resp = llm.invoke([("system", _QUALIFY_SYSTEM), ("human", user_prompt)])
        content = getattr(resp, "content", str(resp))
        return parse_llm_score(str(content))
    except Exception as e:
        logger.debug("qualify %s 失败: %s", candidate.ticker, e)
        return 50, "LLM 调用失败，采用中性分"


def debate_and_verdict(
    scored: ScoredCandidate,
    llm,
    price: Optional[float] = None,
) -> Tuple[str, str, str, int]:
    """对 Top 候选标的进行多空辩论，输出买入意愿星级。

    Args:
        scored:  已通过初筛的打分标的。
        llm:     langchain LLM 对象。None 时使用降级逻辑。
        price:   当前股价（元），用于辅助判断。

    Returns:
        (bull_view, bear_view, verdict, stars)
        - bull_view: 多方观点字符串
        - bear_view: 空方观点字符串
        - verdict:   综合买入结论
        - stars:     1-5 整数买入意愿星级
    """
    if llm is None:
        return _fallback_debate(scored)

    m = scored.metrics
    gain_str = f"{m.get('price_gain_ratio', 0) * 100:.1f}%" if m.get('price_gain_ratio') is not None else "未知"
    turn_str = f"{m.get('turnover_rate', 0) * 100:.2f}%" if m.get('turnover_rate') is not None else "未知"
    inflow_str = f"{m.get('main_net_inflow_ratio', 0) * 100:.2f}%" if m.get('main_net_inflow_ratio') is not None else "未知"
    price_str = f"{price:.2f}元" if price is not None else "未知"

    user_prompt = (
        f"标的：{scored.name}（{scored.ticker}）\n"
        f"所属热点主题：{scored.theme}，板块：{scored.sector}\n"
        f"类型：{'基金/ETF' if scored.is_fund else 'A股股票'}\n"
        f"当前股价：{price_str}\n"
        f"近期主力净流入/市值：{inflow_str}（负数说明净流出，主力未介入）\n"
        f"区间涨幅：{gain_str}\n"
        f"日均换手率：{turn_str}\n"
        f"综合分（0-100）：{scored.composite_score:.0f}\n"
        f"初步推荐理由：{scored.reason}\n\n"
        "请进行多空辩论并给出买入意愿星级，输出 JSON。"
    )

    try:
        resp = llm.invoke([("system", _DEBATE_SYSTEM), ("human", user_prompt)])
        content = getattr(resp, "content", str(resp))

        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            obj = json.loads(content[start:end + 1])
            bull    = str(obj.get("bull", "")).strip()
            bear    = str(obj.get("bear", "")).strip()
            verdict = str(obj.get("verdict", "")).strip()
            stars   = int(obj.get("stars", 3))
            stars   = max(1, min(5, stars))
            return bull, bear, verdict, stars
    except Exception as e:
        logger.warning("debate_and_verdict %s 失败: %s", scored.ticker, e)

    return _fallback_debate(scored)


def _fallback_debate(scored: ScoredCandidate) -> Tuple[str, str, str, int]:
    """LLM 不可用或失败时的降级输出。基于量化指标估算星级。"""
    m = scored.metrics
    gain = m.get("price_gain_ratio")
    inflow = m.get("main_net_inflow_ratio")

    # 简单规则估算星级
    stars = 3
    if inflow is not None and inflow < -0.005:  # 净流出明显
        stars += 1
    if gain is not None and gain < -0.05:       # 近期下跌
        stars += 1
    if gain is not None and gain > 0.10:        # 已涨超 10%
        stars -= 1
    if scored.composite_score >= 80:
        stars = min(5, stars + 1)
    elif scored.composite_score < 60:
        stars = max(1, stars - 1)
    stars = max(1, min(5, stars))

    bull = f"政策主题{scored.theme}具备支撑，主力尚未大举介入，具备布局价值。"
    bear = f"无 LLM 分析，请参考综合分（{scored.composite_score:.0f}）和资金面数据自行判断。"
    verdict = f"综合分 {scored.composite_score:.0f}，建议{'关注' if stars >= 3 else '观望'}。"
    return bull, bear, verdict, stars
