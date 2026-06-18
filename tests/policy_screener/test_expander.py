from tradingagents.policy_screener.models import Candidate
from tradingagents.policy_screener.themes import ThemeConfig
from tradingagents.policy_screener.expander import expand_themes, fetch_board_cons, AShareMarket


def _cfg():
    return ThemeConfig({
        "新质生产力": {
            "keywords": ["半导体"],
            "sectors": ["半导体"],
            "funds": ["159995"],
        },
        "低空经济": {
            "keywords": ["低空经济"],
            "sectors": ["低空经济"],
            "funds": [],
        },
    })


def _fake_cons_fetcher(records):
    """返回一个模拟的板块成分获取函数：sector -> [(code, name), ...]。"""
    def _f(sector: str):
        return records.get(sector, [])
    return _f


def test_expand_stocks_and_funds():
    fetcher = _fake_cons_fetcher({
        "半导体": [("600584", "长电科技"), ("002049", "紫光国微")],
    })
    cands = expand_themes(_cfg(), fetcher)
    # 2 只股票 + 1 只基金
    assert len(cands) == 3
    tickers = {c.ticker for c in cands}
    assert "600584.SS" in tickers      # 600 开头 → .SS
    assert "002049.SZ" in tickers     # 002 开头 → .SZ
    assert "159995" in tickers        # 基金保留原码


def test_expand_marks_fund_flag():
    fetcher = _fake_cons_fetcher({"半导体": [("600584", "长电科技")]})
    cands = expand_themes(_cfg(), fetcher)
    by_code = {c.ticker: c for c in cands}
    assert by_code["600584.SS"].is_fund is False
    assert by_code["159995"].is_fund is True


def test_expand_attaches_theme_and_sector():
    fetcher = _fake_cons_fetcher({"半导体": [("600584", "长电科技")]})
    cands = expand_themes(_cfg(), fetcher)
    stock = next(c for c in cands if c.ticker == "600584.SS")
    assert stock.theme == "新质生产力"
    assert stock.sector == "半导体"
    assert stock.name == "长电科技"


def test_expand_dedupes_across_themes():
    # 同一股票出现在两个主题的板块里，应去重
    cfg = ThemeConfig({
        "T1": {"keywords": ["k"], "sectors": ["共享板块"], "funds": []},
        "T2": {"keywords": ["k"], "sectors": ["共享板块"], "funds": []},
    })
    fetcher = _fake_cons_fetcher({"共享板块": [("600584", "长电科技")]})
    cands = expand_themes(cfg, fetcher)
    codes = [c.ticker for c in cands if not c.is_fund]
    assert codes.count("600584.SS") == 1


def test_expand_skips_empty_sector():
    cfg = ThemeConfig({"T": {"keywords": ["k"], "sectors": ["无成分"], "funds": []}})
    fetcher = _fake_cons_fetcher({})  # 任何板块都返回空
    cands = expand_themes(cfg, fetcher)
    assert cands == []


def test_market_code_inference():
    assert AShareMarket.code_for("600584") == ("600584", "sh")
    assert AShareMarket.code_for("002049") == ("002049", "sz")
    assert AShareMarket.code_for("300750") == ("300750", "sz")
    assert AShareMarket.code_for("688981") == ("688981", "sh")


def test_market_suffix_for_codes():
    assert AShareMarket.suffix_for("600584") == ".SS"
    assert AShareMarket.suffix_for("002049") == ".SZ"
    assert AShareMarket.suffix_for("688981") == ".SS"