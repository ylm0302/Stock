from tradingagents.policy_screener.models import FundFlowMetrics
from tradingagents.policy_screener.fund_flow_scorer import score_metrics, passes_threshold

THRESHOLDS = {
    "main_net_inflow_ratio": 0.01,
    "price_gain_ratio": 0.15,
    "turnover_rate": 0.05,
}


# ── score_metrics ──────────────────────────────────────────────

def test_score_low_inflow_low_gain_high_turnover_is_high():
    """主力未流入 + 未拉升 + 换手适中 → 高分。"""
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=-0.005,  # 净流出
        price_gain_ratio=0.03,        # 微涨
        turnover_rate=0.02,           # 低换手
    )
    score = score_metrics(m)
    assert 70 <= score <= 100


def test_score_high_inflow_high_gain_is_low():
    """主力大举流入 + 已大涨 → 低分。"""
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.05,   # 5% 净流入，远超阈值
        price_gain_ratio=0.30,        # 涨 30%
        turnover_rate=0.12,           # 高换手
    )
    score = score_metrics(m)
    assert 0 <= score <= 30


def test_score_clamped_to_0_100():
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=-1.0,  # 极端净流出
        price_gain_ratio=-0.5,       # 大跌
        turnover_rate=0.0,
    )
    score = score_metrics(m)
    assert score == 100.0


def test_score_missing_metrics_returns_neutral():
    m = FundFlowMetrics(ticker="X")  # 全 None
    assert score_metrics(m) == 50.0


def test_score_partial_metrics_uses_available():
    # 只有涨幅一个指标：未拉升 → 高分
    m = FundFlowMetrics(ticker="X", price_gain_ratio=0.02)
    score = score_metrics(m)
    assert score > 60


# ── passes_threshold ────────────────────────────────────────────

def test_threshold_pass_when_all_under_threshold():
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.005,   # < 0.01
        price_gain_ratio=0.10,         # < 0.15
        turnover_rate=0.03,            # < 0.05
    )
    assert passes_threshold(m, THRESHOLDS) is True


def test_threshold_fail_when_gain_too_high():
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.005,
        price_gain_ratio=0.20,         # > 0.15
        turnover_rate=0.03,
    )
    assert passes_threshold(m, THRESHOLDS) is False


def test_threshold_fail_when_inflow_too_high():
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.02,    # > 0.01
        price_gain_ratio=0.10,
        turnover_rate=0.03,
    )
    assert passes_threshold(m, THRESHOLDS) is False


def test_threshold_missing_metric_ignored():
    """缺失的指标不参与判定（不因缺失而淘汰）。"""
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.005,
        price_gain_ratio=0.10,
        turnover_rate=None,            # 换手率缺失
    )
    assert passes_threshold(m, THRESHOLDS) is True


def test_threshold_all_missing_passes():
    """指标全缺失（akshare 不可用降级）时，不因资金面被淘汰。"""
    m = FundFlowMetrics(ticker="X")
    assert passes_threshold(m, THRESHOLDS) is True


# ── fetch_metrics ─────────────────────────────────────────────────

from unittest.mock import patch, MagicMock
import pandas as pd
from tradingagents.policy_screener.fund_flow_scorer import fetch_metrics


def _stock_fund_flow_df():
    return pd.DataFrame({
        "日期": ["20260610", "20260611"],
        "主力净流入-净占比": [0.2, -0.3],   # 近2日合计 ≈ -0.1%（近未介入）
    })


def _stock_hist_df():
    return pd.DataFrame({
        "日期": ["20260601", "20260610"],
        "收盘": [10.0, 10.2],
        "换手率": [2.0, 3.0],
        "涨跌幅": [0.0, 2.0],
    })


def _hsgt_df():
    return pd.DataFrame({
        "持股日期": ["20260610", "20260611"],
        "今日增持资金": [100.0, -50.0],   # 百万元
    })


def test_fetch_stock_metrics_aggregates_three_sources():
    with patch("akshare.stock_individual_fund_flow", return_value=_stock_fund_flow_df()), \
         patch("akshare.stock_zh_a_hist", return_value=_stock_hist_df()), \
         patch("akshare.stock_hsgt_individual_em", return_value=_hsgt_df()):
        m = fetch_metrics("600584.SS", "2026-06-18", lookback=10, is_fund=False)
    assert m.ticker == "600584.SS"
    assert m.is_fund is False
    assert m.main_net_inflow_ratio is not None
    assert m.price_gain_ratio is not None       # (10.2-10)/10 = 0.02
    assert abs(m.price_gain_ratio - 0.02) < 1e-9
    assert m.turnover_rate is not None         # 均值 2.5% = 0.025
    assert abs(m.turnover_rate - 0.025) < 1e-9
    assert m.fetch_error is None


def test_fetch_stock_metrics_degrades_on_failure():
    """akshare 抛异常时，metrics 字段为空但带 fetch_error，不抛。"""
    with patch("akshare.stock_individual_fund_flow", side_effect=RuntimeError("timeout")), \
         patch("akshare.stock_zh_a_hist", side_effect=RuntimeError("timeout")), \
         patch("akshare.stock_hsgt_individual_em", side_effect=RuntimeError("timeout")):
        m = fetch_metrics("600584.SS", "2026-06-18", lookback=10, is_fund=False)
    assert m.main_net_inflow_ratio is None
    assert m.price_gain_ratio is None
    assert m.fetch_error is not None
    assert "timeout" in m.fetch_error


def test_fetch_fund_metrics_uses_etf_hist():
    etf_df = pd.DataFrame({
        "日期": ["20260601", "20260610"],
        "收盘": [1.0, 1.02],
        "换手率": [1.5, 2.5],
        "涨跌幅": [0.0, 2.0],
    })
    with patch("akshare.fund_etf_hist_em", return_value=etf_df):
        m = fetch_metrics("159995", "2026-06-18", lookback=10, is_fund=True)
    assert m.is_fund is True
    assert m.main_net_inflow_ratio is None      # 基金无主力净流入口径
    assert m.price_gain_ratio is not None
    assert m.turnover_rate is not None