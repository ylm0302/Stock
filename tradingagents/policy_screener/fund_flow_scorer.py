"""资金面打分器。

分两层：
  - 纯函数层（本文件上半部）：score_metrics / passes_threshold，可精确测试。
  - akshare 拉取层（本文件下半部 + runner 调用）：fetch_metrics。

打分语义：指标越接近"未介入"端，分越高（0-100，缺失指标跳过）。
"""

from __future__ import annotations

from .models import FundFlowMetrics


# ── 纯函数：单指标 → 0-100 ──────────────────────────────────────

def _ratio_score(value: float, neutral: float, saturate: float) -> float:
    """线性把 ratio 映射到 0-100：值 ≤ neutral 得 100，值 ≥ saturate 得 0。

    value 越低（主力未介入）→ 分越高。
    """
    if value <= neutral:
        return 100.0
    if value >= saturate:
        return 0.0
    # 线性插值
    return 100.0 * (saturate - value) / (saturate - neutral)


def score_metrics(metrics: FundFlowMetrics) -> float:
    """把资金面原始指标合成为 0-100 分。

    缺失（None）的指标跳过；全部缺失返回中性 50。
    """
    scores = []

    if metrics.main_net_inflow_ratio is not None:
        # neutral=0（净流出即满分）, saturate=0.05（5% 净流入即 0 分）
        scores.append(_ratio_score(metrics.main_net_inflow_ratio, neutral=0.0, saturate=0.05))

    if metrics.north_inflow is not None:
        # 北向净流入：0 即满分，+500(百万) 即 0 分
        scores.append(_ratio_score(metrics.north_inflow, neutral=0.0, saturate=500.0))

    if metrics.price_gain_ratio is not None:
        # 涨幅：0 即满分，+0.30(涨30%) 即 0 分；下跌同样高分
        scores.append(_ratio_score(metrics.price_gain_ratio, neutral=0.0, saturate=0.30))

    if metrics.turnover_rate is not None:
        # 换手率：0 即满分，0.15(15%) 即 0 分
        scores.append(_ratio_score(metrics.turnover_rate, neutral=0.0, saturate=0.15))

    if metrics.share_change_ratio is not None:
        # 份额变化：0 即满分，+0.30(增30%) 即 0 分
        scores.append(_ratio_score(metrics.share_change_ratio, neutral=0.0, saturate=0.30))

    if not scores:
        return 50.0

    avg = sum(scores) / len(scores)
    return float(max(0.0, min(100.0, avg)))


def passes_threshold(metrics: FundFlowMetrics, thresholds: dict) -> bool:
    """判定是否"主力尚未大举介入"。

    仅对存在的指标判定；缺失指标跳过（不淘汰）。
    全部缺失时返回 True（不因数据缺失而淘汰，留给 LLM 档评判）。
    """
    checks = []

    if metrics.main_net_inflow_ratio is not None:
        lim = thresholds["main_net_inflow_ratio"]
        checks.append(metrics.main_net_inflow_ratio <= lim)

    if metrics.price_gain_ratio is not None:
        lim = thresholds["price_gain_ratio"]
        checks.append(metrics.price_gain_ratio <= lim)

    if metrics.turnover_rate is not None:
        lim = thresholds["turnover_rate"]
        checks.append(metrics.turnover_rate <= lim)

    if not checks:
        return True
    return all(checks)