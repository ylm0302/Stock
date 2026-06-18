from tradingagents.policy_screener.models import ScoredCandidate, FundFlowMetrics
from tradingagents.policy_screener.reporter import render_report


def _s(ticker, name, score, is_fund=False, gain=0.05):
    return ScoredCandidate(
        ticker=ticker, name=name, theme="新质生产力", is_fund=is_fund, sector="半导体",
        relevance_score=80, fund_flow_score=75, llm_qualitative_score=70,
        composite_score=score,
        metrics={"price_gain_ratio": gain, "turnover_rate": 0.03, "main_net_inflow_ratio": 0.002},
        reason="主力未介入",
    )


def test_report_has_title_and_date():
    md = render_report([], themes=["新质生产力"], date="2026-06-18", deep_results={})
    assert "# 政策扶持标的推荐池 (2026-06-18)" in md
    assert "新质生产力" in md


def test_report_shows_stock_and_fund_tables():
    stock = _s("600584.SS", "长电科技", 82)
    fund = _s("159995", "芯片ETF", 78, is_fund=True)
    md = render_report([stock, fund], themes=["新质生产力"], date="2026-06-18", deep_results={})
    assert "## 推荐股票" in md
    assert "长电科技" in md
    assert "## 推荐基金/ETF" in md
    assert "芯片ETF" in md


def test_report_includes_composite_score():
    md = render_report([_s("600584.SS", "长电科技", 82)], themes=["T"], date="2026-06-18", deep_results={})
    assert "82" in md


def test_report_includes_deep_analysis_when_present():
    stock = _s("600584.SS", "长电科技", 82)
    deep = {"600584.SS": "建议逐步建仓，仓位 5%。"}
    md = render_report([stock], themes=["T"], date="2026-06-18", deep_results=deep)
    assert "## 深度配置建议" in md
    assert "逐步建仓" in md


def test_report_marks_deep_analysis_failed():
    stock = _s("600584.SS", "长电科技", 82)
    deep = {"600584.SS": None}  # None 表示该标的深度分析失败
    md = render_report([stock], themes=["T"], date="2026-06-18", deep_results=deep)
    assert "深度分析失败" in md


def test_report_empty_pool_message():
    md = render_report([], themes=["T"], date="2026-06-18", deep_results={})
    assert "未筛选出符合条件" in md