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