from unittest.mock import patch, MagicMock

from tradingagents.policy_screener.runner import PolicyScreenerRunner
from tradingagents.default_config import DEFAULT_CONFIG


def _cfg():
    c = DEFAULT_CONFIG.copy()
    c["policy_thresholds"] = {"main_net_inflow_ratio": 0.01, "price_gain_ratio": 0.15, "turnover_rate": 0.05}
    c["policy_weights"] = {"relevance": 0.30, "fund_flow": 0.45, "llm_qualitative": 0.25}
    c["policy_lookback_days"] = 10
    c["policy_top_n"] = 10
    c["policy_deep_analyze_top"] = 0   # 不跑深度，避免依赖 graph
    return c


def _fake_cons(sector):
    # 返回两只股票
    return [("600584", "长电科技"), ("002049", "紫光国微")]


def _fake_metrics_stock(ticker, end_date, lookback, is_fund):
    from tradingagents.policy_screener.models import FundFlowMetrics
    return FundFlowMetrics(
        ticker=ticker, main_net_inflow_ratio=0.002, price_gain_ratio=0.05,
        turnover_rate=0.03, is_fund=is_fund,
    )


def _fake_metrics_fund(ticker, end_date, lookback, is_fund):
    from tradingagents.policy_screener.models import FundFlowMetrics
    return FundFlowMetrics(ticker=ticker, price_gain_ratio=0.04, turnover_rate=0.02, is_fund=True)


def _fake_qualify(candidate, llm):
    return (70, "机构调研增加")


def test_runner_produces_report_with_candidates(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  新质生产力:\n    keywords: [半导体]\n    sectors: [半导体]\n    funds: [159995]\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_themes_file"] = str(themes_path)

    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_board_cons", _fake_cons)

    def metrics_router(ticker, end_date, lookback, is_fund):
        return _fake_metrics_fund(ticker, end_date, lookback, is_fund) if is_fund else _fake_metrics_stock(ticker, end_date, lookback, is_fund)
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", metrics_router)
    monkeypatch.setattr("tradingagents.policy_screener.runner.qualify", _fake_qualify)

    runner = PolicyScreenerRunner(cfg, llm=MagicMock())
    report = runner.run(themes=["新质生产力"], date="2026-06-18", deep_analyze=False)

    assert "# 政策扶持标的推荐池 (2026-06-18)" in report
    assert "长电科技" in report
    assert "159995" in report


def test_runner_filters_threshold_violators(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_themes_file"] = str(themes_path)

    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_board_cons", lambda s: [("600584", "长电科技")])

    def hot_metrics(ticker, end_date, lookback, is_fund):
        from tradingagents.policy_screener.models import FundFlowMetrics
        return FundFlowMetrics(ticker=ticker, price_gain_ratio=0.30, turnover_rate=0.12, main_net_inflow_ratio=0.05, is_fund=False)
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", hot_metrics)
    monkeypatch.setattr("tradingagents.policy_screener.runner.qualify", _fake_qualify)

    runner = PolicyScreenerRunner(cfg, llm=MagicMock())
    report = runner.run(themes=["T"], date="2026-06-18", deep_analyze=False)
    assert "未筛选出符合条件" in report


def test_runner_degrades_when_llm_none(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_themes_file"] = str(themes_path)
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_board_cons", lambda s: [("600584", "长电科技")])
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", _fake_metrics_stock)

    runner = PolicyScreenerRunner(cfg, llm=None)
    report = runner.run(themes=["T"], date="2026-06-18", deep_analyze=False)
    assert "长电科技" in report  # LLM 降级为中性分，仍能产出报告


def test_runner_deep_analyze_calls_propagate(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_deep_analyze_top"] = 1
    cfg["policy_themes_file"] = str(themes_path)
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_board_cons", lambda s: [("600584", "长电科技")])
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", _fake_metrics_stock)
    monkeypatch.setattr("tradingagents.policy_screener.runner.qualify", _fake_qualify)

    fake_graph = MagicMock()
    fake_graph.propagate.return_value = (None, "建议建仓 5%。")

    runner = PolicyScreenerRunner(cfg, llm=MagicMock(), graph=fake_graph)
    report = runner.run(themes=["T"], date="2026-06-18", deep_analyze=True)
    assert "建议建仓" in report
    fake_graph.propagate.assert_called()


def test_runner_deep_analyze_failure_isolated(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_deep_analyze_top"] = 1
    cfg["policy_themes_file"] = str(themes_path)
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_board_cons", lambda s: [("600584", "长电科技")])
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", _fake_metrics_stock)
    monkeypatch.setattr("tradingagents.policy_screener.runner.qualify", _fake_qualify)

    fake_graph = MagicMock()
    fake_graph.propagate.side_effect = RuntimeError("boom")

    runner = PolicyScreenerRunner(cfg, llm=MagicMock(), graph=fake_graph)
    report = runner.run(themes=["T"], date="2026-06-18", deep_analyze=True)
    # 推荐池仍在，深度分析标记失败
    assert "长电科技" in report
    assert "深度分析失败" in report