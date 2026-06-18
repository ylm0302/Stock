from tradingagents.policy_screener.models import (
    Candidate,
    ScoredCandidate,
    FundFlowMetrics,
)


def test_candidate_basic_fields():
    c = Candidate(ticker="600519.SS", name="贵州茅台", theme="新质生产力", is_fund=False, sector="白酒")
    assert c.ticker == "600519.SS"
    assert c.is_fund is False


def test_scored_candidate_inherits_candidate():
    s = ScoredCandidate(
        ticker="159995", name="芯片ETF", theme="新质生产力",
        is_fund=True, sector="半导体",
        relevance_score=90.0, fund_flow_score=80.0, llm_qualitative_score=70.0,
        composite_score=82.5, metrics={"price_gain_ratio": 0.05}, reason="主力未介入",
    )
    assert s.composite_score == 82.5
    assert s.metrics["price_gain_ratio"] == 0.05
    # 继承自 Candidate
    assert s.theme == "新质生产力"
    assert s.is_fund is True


def test_scored_candidate_reason_defaults_to_empty():
    s = ScoredCandidate(
        ticker="000001", name="X", theme="T", is_fund=False, sector="S",
        relevance_score=50, fund_flow_score=50, llm_qualitative_score=50, composite_score=50,
        metrics={},
    )
    assert s.reason == ""


def test_fund_flow_metrics_defaults_none():
    m = FundFlowMetrics(ticker="600519.SS")
    assert m.main_net_inflow_ratio is None  # 缺失即 None，而非 NaN
    assert m.price_gain_ratio is None
    assert m.is_fund is False
    assert m.data_source == "akshare"
    assert m.fetch_error is None


def test_fund_flow_metrics_carries_error():
    m = FundFlowMetrics(ticker="X", fetch_error="timeout")
    assert m.fetch_error == "timeout"
    assert m.data_source == "akshare"
