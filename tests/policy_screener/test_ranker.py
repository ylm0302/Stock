from tradingagents.policy_screener.models import Candidate, ScoredCandidate, FundFlowMetrics
from tradingagents.policy_screener.ranker import rank_candidates, composite_score

THRESHOLDS = {"main_net_inflow_ratio": 0.01, "price_gain_ratio": 0.15, "turnover_rate": 0.05}
WEIGHTS = {"relevance": 0.30, "fund_flow": 0.45, "llm_qualitative": 0.25}


def _scored(ticker, rel, ff, llm, gain=0.05, inflow=0.002, turnover=0.03):
    return ScoredCandidate(
        ticker=ticker, name=ticker, theme="T", is_fund=False, sector="S",
        relevance_score=rel, fund_flow_score=ff, llm_qualitative_score=llm,
        composite_score=0.0,
        metrics=FundFlowMetrics(ticker=ticker, price_gain_ratio=gain,
                               main_net_inflow_ratio=inflow, turnover_rate=turnover).__dict__,
    )


def test_composite_score_weighted_average():
    s = _scored("A", rel=100, ff=80, llm=60)
    assert abs(composite_score(s, WEIGHTS) - (0.30*100 + 0.45*80 + 0.25*60)) < 1e-9


def test_rank_orders_by_composite_desc():
    a = _scored("A", 50, 50, 50)
    b = _scored("B", 90, 90, 90)
    c = _scored("C", 60, 60, 60)
    ranked = rank_candidates([a, b, c], THRESHOLDS, WEIGHTS, top_n=10)
    assert [r.ticker for r in ranked] == ["B", "C", "A"]


def test_rank_filters_out_threshold_violators():
    # B 涨幅 30% 超阈值，应被剔除
    a = _scored("A", 50, 50, 50, gain=0.05)
    b = _scored("B", 90, 90, 90, gain=0.30)
    ranked = rank_candidates([a, b], THRESHOLDS, WEIGHTS, top_n=10)
    tickers = [r.ticker for r in ranked]
    assert "A" in tickers
    assert "B" not in tickers


def test_rank_respects_top_n():
    items = [_scored(f"T{i}", i, i, i) for i in range(5)]
    ranked = rank_candidates(items, THRESHOLDS, WEIGHTS, top_n=3)
    assert len(ranked) == 3
    assert ranked[0].ticker == "T4"  # 最高分在前


def test_rank_preserves_composite_score_on_result():
    a = _scored("A", 60, 60, 60)
    ranked = rank_candidates([a], THRESHOLDS, WEIGHTS, top_n=10)
    assert ranked[0].composite_score == composite_score(a, WEIGHTS)