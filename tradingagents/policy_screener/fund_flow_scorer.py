"""资金面打分器。

分两层：
  - 纯函数层（本文件上半部）：score_metrics / passes_threshold，可精确测试。
  - akshare 拉取层（本文件下半部 + runner 调用）：fetch_metrics。

打分语义：指标越接近"未介入"端，分越高（0-100，缺失指标跳过）。
"""

from __future__ import annotations

import pandas as pd

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


# ── akshare 拉取层 ──────────────────────────────────────────────

def _to_int_date(date_str: str) -> str:
    """'2026-06-18' → '20260618'。"""
    return date_str.replace("-", "")


def _strip_suffix(ticker: str) -> str:
    return ticker.split(".")[0]


def fetch_metrics(ticker: str, end_date: str, lookback: int, is_fund: bool) -> FundFlowMetrics:
    """从 akshare 拉取单只标的近 lookback 日资金面指标。

    任何异常都被吞掉并记入 fetch_error，绝不抛出（降级由调用方处理）。
    """
    if is_fund:
        return _fetch_fund_metrics(ticker, end_date, lookback)
    return _fetch_stock_metrics(ticker, end_date, lookback)


def _fetch_stock_metrics(ticker: str, end_date: str, lookback: int) -> FundFlowMetrics:
    import akshare as ak

    code = _strip_suffix(ticker)
    market = "sh" if ticker.endswith(".SS") else "sz"
    int_end = _to_int_date(end_date)

    main_ratio = None
    north = None
    gain = None
    turnover = None
    errors = []

    # 1) 个股资金流（主力净流入占比）
    try:
        df = ak.stock_individual_fund_flow(stock=code, market=market)
        if df is not None and not df.empty and "主力净流入-净占比" in df.columns:
            recent = df.tail(lookback)
            # 净占比是百分数（如 0.2 表示 0.2%），转成小数
            main_ratio = float(pd.to_numeric(recent["主力净流入-净占比"], errors="coerce").sum()) / 100.0
    except Exception as e:
        errors.append(f"fund_flow:{e}")

    # 2) 个股日线（涨幅、换手率）
    try:
        # 近 lookback*2 个自然日，确保有足够交易日
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                               start_date=int_end, end_date=int_end, adjust="")
        # 上面 start==end 可能只取到一天；放宽窗口重取
        if df is None or df.empty or len(df) < 2:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")
        if df is not None and not df.empty and "收盘" in df.columns:
            recent = df.tail(lookback)
            closes = pd.to_numeric(recent["收盘"], errors="coerce").dropna()
            if len(closes) >= 2:
                gain = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])
            if "换手率" in recent.columns:
                turnover = float(pd.to_numeric(recent["换手率"], errors="coerce").mean()) / 100.0
    except Exception as e:
        errors.append(f"hist:{e}")

    # 3) 北向个股持股
    try:
        df = ak.stock_hsgt_individual_em(symbol=code)
        if df is not None and not df.empty and "今日增持资金" in df.columns:
            recent = df.tail(lookback)
            north = float(pd.to_numeric(recent["今日增持资金"], errors="coerce").sum())
    except Exception as e:
        errors.append(f"hsgt:{e}")

    return FundFlowMetrics(
        ticker=ticker,
        main_net_inflow_ratio=main_ratio,
        north_inflow=north,
        price_gain_ratio=gain,
        turnover_rate=turnover,
        is_fund=False,
        fetch_error="; ".join(errors) if errors else None,
    )


def _fetch_fund_metrics(ticker: str, end_date: str, lookback: int) -> FundFlowMetrics:
    import akshare as ak

    code = _strip_suffix(ticker)
    gain = None
    turnover = None
    errors = []

    try:
        df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="")
        if df is not None and not df.empty and "收盘" in df.columns:
            recent = df.tail(lookback)
            closes = pd.to_numeric(recent["收盘"], errors="coerce").dropna()
            if len(closes) >= 2:
                gain = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])
            if "换手率" in recent.columns:
                turnover = float(pd.to_numeric(recent["换手率"], errors="coerce").mean()) / 100.0
    except Exception as e:
        errors.append(f"etf_hist:{e}")

    return FundFlowMetrics(
        ticker=ticker,
        price_gain_ratio=gain,
        turnover_rate=turnover,
        is_fund=True,
        # 基金无主力净流入/北向口径，main_net_inflow_ratio 保持 None
        fetch_error="; ".join(errors) if errors else None,
    )