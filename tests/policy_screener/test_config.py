from tradingagents.default_config import DEFAULT_CONFIG


def test_policy_config_keys_present():
    """policy_* 配置项应在 DEFAULT_CONFIG 中存在。"""
    assert DEFAULT_CONFIG["policy_themes_file"].endswith("policy_themes.yaml")
    assert DEFAULT_CONFIG["policy_lookback_days"] == 10
    assert DEFAULT_CONFIG["policy_top_n"] == 10
    assert DEFAULT_CONFIG["policy_deep_analyze_top"] == 3


def test_policy_thresholds_defaults():
    t = DEFAULT_CONFIG["policy_thresholds"]
    assert t["main_net_inflow_ratio"] == 0.01
    assert t["price_gain_ratio"] == 0.15
    assert t["turnover_rate"] == 0.05


def test_policy_weights_sum_to_one():
    w = DEFAULT_CONFIG["policy_weights"]
    total = w["relevance"] + w["fund_flow"] + w["llm_qualitative"]
    assert abs(total - 1.0) < 1e-9


def test_env_override_lookback_days(monkeypatch):
    """policy_lookback_days 应支持 TRADINGAGENTS_ 环境变量覆盖。"""
    # 重新导入以触发 _apply_env_overrides
    monkeypatch.setenv("TRADINGAGENTS_POLICY_LOOKBACK_DAYS", "20")
    import importlib
    from tradingagents import default_config as dc
    importlib.reload(dc)
    try:
        assert dc.DEFAULT_CONFIG["policy_lookback_days"] == 20
    finally:
        importlib.reload(dc)  # 还原
