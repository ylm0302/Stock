"""综合排序器：加权 + 阈值过滤 + 排序 + 截断。纯函数。"""

from __future__ import annotations

from typing import List

from .fund_flow_scorer import passes_threshold
from .models import FundFlowMetrics, ScoredCandidate


def composite_score(scored: ScoredCandidate, weights: dict) -> float:
    """按权重合成综合分。"""
    return (
        weights["relevance"] * scored.relevance_score
        + weights["fund_flow"] * scored.fund_flow_score
        + weights["llm_qualitative"] * scored.llm_qualitative_score
    )


def rank_candidates(
    scored: List[ScoredCandidate],
    thresholds: dict,
    weights: dict,
    top_n: int,
) -> List[ScoredCandidate]:
    """阈值过滤 → 计算综合分 → 降序排序 → 截断 top_n。"""
    passed = []
    for s in scored:
        # 从 metrics 重建 FundFlowMetrics 以复用阈值判定
        m = _metrics_from_dict(s.metrics)
        if not passes_threshold(m, thresholds):
            continue
        s.composite_score = composite_score(s, weights)
        passed.append(s)

    passed.sort(key=lambda x: x.composite_score, reverse=True)
    return passed[:top_n]


def _metrics_from_dict(d: dict) -> FundFlowMetrics:
    """从 metrics dict（可能存的是 FundFlowMetrics.__dict__）重建。"""
    if not d:
        return FundFlowMetrics(ticker="")
    return FundFlowMetrics(
        ticker=d.get("ticker", ""),
        main_net_inflow_ratio=d.get("main_net_inflow_ratio"),
        north_inflow=d.get("north_inflow"),
        price_gain_ratio=d.get("price_gain_ratio"),
        turnover_rate=d.get("turnover_rate"),
        is_fund=d.get("is_fund", False),
    )