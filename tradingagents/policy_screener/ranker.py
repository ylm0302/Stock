"""综合排序器：加权 + 阈值过滤 + 价格筛选 + 排序 + 截断。纯函数。"""

from __future__ import annotations

from typing import List, Optional

from .fund_flow_scorer import passes_price_filter, passes_threshold
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
    max_price: Optional[float] = None,
) -> List[ScoredCandidate]:
    """阈值过滤 → 价格过滤 → 综合分 → 降序排序 → 截断 top_n。

    Args:
        scored:     打分后的候选标的列表。
        thresholds: 主力介入度阈值字典。
        weights:    综合分权重字典。
        top_n:      保留的推荐数量上限。
        max_price:  最高股价过滤（元）。None 或 0 表示不过滤。
    """
    passed = []
    for s in scored:
        m = _metrics_from_dict(s.metrics)
        # 1) 主力介入度阈值
        if not passes_threshold(m, thresholds):
            continue
        # 2) 价格筛选（普通人可购买）
        if not passes_price_filter(m, max_price):
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
        current_price=d.get("current_price"),
        is_fund=d.get("is_fund", False),
    )
