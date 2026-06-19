"""资金面打分器。

分两层：
  - 纯函数层（本文件上半部）：score_metrics / passes_threshold，可精确测试。
  - 数据拉取层（本文件下半部）：fetch_metrics。
    优先 akshare；若 akshare 网络不通，自动降级到 baostock。

打分语义：指标越接近"未介入"端，分越高（0-100，缺失指标跳过）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from .models import FundFlowMetrics

logger = logging.getLogger(__name__)


# ── 纯函数：单指标 → 0-100 ──────────────────────────────────────

def _ratio_score(value: float, neutral: float, saturate: float) -> float:
    """线性把 ratio 映射到 0-100：值 ≤ neutral 得 100，值 ≥ saturate 得 0。

    value 越低（主力未介入）→ 分越高。
    """
    if value <= neutral:
        return 100.0
    if value >= saturate:
        return 0.0
    return 100.0 * (saturate - value) / (saturate - neutral)


def score_metrics(metrics: FundFlowMetrics) -> float:
    """把资金面原始指标合成为 0-100 分。

    缺失（None）的指标跳过；全部缺失返回中性 50。
    """
    scores = []

    if metrics.main_net_inflow_ratio is not None:
        scores.append(_ratio_score(metrics.main_net_inflow_ratio, neutral=0.0, saturate=0.05))

    if metrics.north_inflow is not None:
        scores.append(_ratio_score(metrics.north_inflow, neutral=0.0, saturate=500.0))

    if metrics.price_gain_ratio is not None:
        scores.append(_ratio_score(metrics.price_gain_ratio, neutral=0.0, saturate=0.30))

    if metrics.turnover_rate is not None:
        scores.append(_ratio_score(metrics.turnover_rate, neutral=0.0, saturate=0.15))

    if metrics.share_change_ratio is not None:
        scores.append(_ratio_score(metrics.share_change_ratio, neutral=0.0, saturate=0.30))

    if not scores:
        return 50.0

    return float(max(0.0, min(100.0, sum(scores) / len(scores))))


def passes_threshold(metrics: FundFlowMetrics, thresholds: dict) -> bool:
    """判定是否"主力尚未大举介入"。

    仅对存在的指标判定；缺失指标跳过（不淘汰）。
    全部缺失时返回 True（不因数据缺失而淘汰，留给 LLM 档评判）。
    """
    checks = []

    if metrics.main_net_inflow_ratio is not None:
        checks.append(metrics.main_net_inflow_ratio <= thresholds["main_net_inflow_ratio"])

    if metrics.price_gain_ratio is not None:
        checks.append(metrics.price_gain_ratio <= thresholds["price_gain_ratio"])

    if metrics.turnover_rate is not None:
        checks.append(metrics.turnover_rate <= thresholds["turnover_rate"])

    if not checks:
        return True
    return all(checks)


# ── 工具函数 ─────────────────────────────────────────────────────

def _strip_suffix(ticker: str) -> str:
    return ticker.split(".")[0]


def _to_dash_date(date_str: str) -> str:
    """'20260618' → '2026-06-18'（兼容已有横线格式）。"""
    d = date_str.replace("-", "")
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def _lookback_start(end_date: str, lookback: int) -> str:
    """从 end_date 往前推 lookback * 2 个自然日（保证覆盖足够交易日）。"""
    end_dt = datetime.strptime(_to_dash_date(end_date), "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=lookback * 2)
    return start_dt.strftime("%Y-%m-%d")


# ── baostock 可用性缓存（避免每次都尝试登录）─────────────────────
_BS_AVAILABLE: bool | None = None   # None=未检测, True=可用, False=不可用


def _bs_login() -> bool:
    """尝试登录 baostock，返回是否成功。结果缓存在 _BS_AVAILABLE。"""
    global _BS_AVAILABLE
    if _BS_AVAILABLE is not None:
        return _BS_AVAILABLE
    try:
        import baostock as bs
        lg = bs.login()
        _BS_AVAILABLE = (lg.error_code == "0")
        if not _BS_AVAILABLE:
            logger.warning("baostock 登录失败: %s", lg.error_msg)
    except Exception as e:
        logger.warning("baostock 不可用: %s", e)
        _BS_AVAILABLE = False
    return _BS_AVAILABLE


def _bs_code(ticker: str) -> str:
    """'600519.SS' → 'sh.600519'；'300750.SZ' → 'sz.300750'。"""
    code = _strip_suffix(ticker)
    prefix = "sh" if ticker.endswith(".SS") else "sz"
    return f"{prefix}.{code}"


# ── baostock 拉取：涨幅 + 换手率 ─────────────────────────────────

def _fetch_via_baostock(ticker: str, end_date: str, lookback: int) -> FundFlowMetrics:
    """用 baostock 拉取涨幅和换手率（akshare 不通时的降级数据源）。

    baostock 无主力资金流数据，只能补充 price_gain_ratio 和 turnover_rate。
    """
    import baostock as bs

    bs_code = _bs_code(ticker)
    start_date = _lookback_start(end_date, lookback)
    end_date_fmt = _to_dash_date(end_date)

    gain = None
    turnover = None
    errors = []

    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,close,turn,pctChg",
            start_date=start_date,
            end_date=end_date_fmt,
            frequency="d",
            adjustflag="3",   # 后复权
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())

        if rows:
            df = pd.DataFrame(rows, columns=["date", "close", "turn", "pctChg"])
            df = df.tail(lookback)

            closes = pd.to_numeric(df["close"], errors="coerce").dropna()
            if len(closes) >= 2:
                gain = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])

            turns = pd.to_numeric(df["turn"], errors="coerce").dropna()
            if len(turns) > 0:
                # baostock turn 已是百分数（如 0.82 表示 0.82%）
                turnover = float(turns.mean()) / 100.0
        else:
            errors.append(f"baostock:no rows for {bs_code}")
    except Exception as e:
        errors.append(f"baostock:{e}")

    return FundFlowMetrics(
        ticker=ticker,
        price_gain_ratio=gain,
        turnover_rate=turnover,
        is_fund=False,
        data_source="baostock",
        fetch_error="; ".join(errors) if errors else None,
    )


def _fetch_fund_via_baostock(ticker: str, end_date: str, lookback: int) -> FundFlowMetrics:
    """用 baostock 拉取 ETF 日线（基金降级）。"""
    # baostock ETF 代码格式与股票相同
    return _fetch_via_baostock(ticker, end_date, lookback)


# ── 主入口：akshare 优先，baostock 降级 ──────────────────────────

def fetch_metrics(ticker: str, end_date: str, lookback: int, is_fund: bool) -> FundFlowMetrics:
    """拉取单只标的近 lookback 日资金面指标。

    策略：
    1. 优先 akshare（数据更全：含主力资金流、北向）
    2. akshare 失败且 baostock 可用 → 降级到 baostock（涨幅 + 换手率）
    3. 全部失败 → 返回空 FundFlowMetrics（中性分，不淘汰）
    """
    if is_fund:
        return _fetch_fund_metrics(ticker, end_date, lookback)
    return _fetch_stock_metrics(ticker, end_date, lookback)


def _fetch_stock_metrics(ticker: str, end_date: str, lookback: int) -> FundFlowMetrics:
    code = _strip_suffix(ticker)
    market = "sh" if ticker.endswith(".SS") else "sz"

    main_ratio = None
    north = None
    gain = None
    turnover = None
    ak_errors = []
    use_baostock = False

    # ── 尝试 akshare ──────────────────────────────────────────────
    try:
        import akshare as ak

        # 1) 个股资金流（主力净流入占比）
        try:
            df = ak.stock_individual_fund_flow(stock=code, market=market)
            if df is not None and not df.empty and "主力净流入-净占比" in df.columns:
                recent = df.tail(lookback)
                main_ratio = float(
                    pd.to_numeric(recent["主力净流入-净占比"], errors="coerce").sum()
                ) / 100.0
        except Exception as e:
            ak_errors.append(f"fund_flow:{e}")

        # 2) 个股日线（涨幅、换手率）
        try:
            int_end = end_date.replace("-", "")
            df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                    start_date=int_end, end_date=int_end, adjust="")
            if df is None or df.empty or len(df) < 2:
                df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")
            if df is not None and not df.empty and "收盘" in df.columns:
                recent = df.tail(lookback)
                closes = pd.to_numeric(recent["收盘"], errors="coerce").dropna()
                if len(closes) >= 2:
                    gain = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])
                if "换手率" in recent.columns:
                    turnover = float(
                        pd.to_numeric(recent["换手率"], errors="coerce").mean()
                    ) / 100.0
            else:
                ak_errors.append("hist:empty")
                use_baostock = True
        except Exception as e:
            ak_errors.append(f"hist:{e}")
            use_baostock = True

        # 3) 北向持股
        try:
            df = ak.stock_hsgt_individual_em(symbol=code)
            if df is not None and not df.empty and "今日增持资金" in df.columns:
                recent = df.tail(lookback)
                north = float(pd.to_numeric(recent["今日增持资金"], errors="coerce").sum())
        except Exception as e:
            ak_errors.append(f"hsgt:{e}")

    except Exception as e:
        ak_errors.append(f"akshare_import:{e}")
        use_baostock = True

    # ── akshare 日线失败时降级到 baostock 补充 gain/turnover ─────
    if use_baostock and (gain is None or turnover is None):
        if _bs_login():
            logger.info("akshare 日线失败，降级到 baostock: %s", ticker)
            bs_m = _fetch_via_baostock(ticker, end_date, lookback)
            if gain is None:
                gain = bs_m.price_gain_ratio
            if turnover is None:
                turnover = bs_m.turnover_rate
            if bs_m.fetch_error:
                ak_errors.append(bs_m.fetch_error)
        else:
            ak_errors.append("baostock:unavailable")

    all_errors = "; ".join(ak_errors) if ak_errors else None
    return FundFlowMetrics(
        ticker=ticker,
        main_net_inflow_ratio=main_ratio,
        north_inflow=north,
        price_gain_ratio=gain,
        turnover_rate=turnover,
        is_fund=False,
        fetch_error=all_errors,
    )


def _fetch_fund_metrics(ticker: str, end_date: str, lookback: int) -> FundFlowMetrics:
    code = _strip_suffix(ticker)
    gain = None
    turnover = None
    ak_errors = []
    use_baostock = False

    # ── 尝试 akshare ──────────────────────────────────────────────
    try:
        import akshare as ak
        df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="")
        if df is not None and not df.empty and "收盘" in df.columns:
            recent = df.tail(lookback)
            closes = pd.to_numeric(recent["收盘"], errors="coerce").dropna()
            if len(closes) >= 2:
                gain = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])
            if "换手率" in recent.columns:
                turnover = float(
                    pd.to_numeric(recent["换手率"], errors="coerce").mean()
                ) / 100.0
        else:
            ak_errors.append("etf_hist:empty")
            use_baostock = True
    except Exception as e:
        ak_errors.append(f"etf_hist:{e}")
        use_baostock = True

    # ── 降级到 baostock ───────────────────────────────────────────
    if use_baostock and (gain is None or turnover is None):
        if _bs_login():
            logger.info("akshare ETF 失败，降级到 baostock: %s", ticker)
            bs_m = _fetch_fund_via_baostock(ticker, end_date, lookback)
            if gain is None:
                gain = bs_m.price_gain_ratio
            if turnover is None:
                turnover = bs_m.turnover_rate
            if bs_m.fetch_error:
                ak_errors.append(bs_m.fetch_error)
        else:
            ak_errors.append("baostock:unavailable")

    return FundFlowMetrics(
        ticker=ticker,
        price_gain_ratio=gain,
        turnover_rate=turnover,
        is_fund=True,
        fetch_error="; ".join(ak_errors) if ak_errors else None,
    )
