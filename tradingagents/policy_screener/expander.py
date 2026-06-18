"""主题 → 候选标的池展开器。

akshare 板块成分调用被隔离在 fetch_board_cons 中；
expand_themes 接收可注入的获取函数，便于测试与降级。
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from .models import Candidate
from .themes import ThemeConfig


class AShareMarket:
    """A 股市场代码推断工具。"""

    @staticmethod
    def market_of(code: str) -> str:
        """6 位代码 → 交易所代码 'sh' / 'sz'。"""
        code = code.strip()
        if code.startswith(("60", "68", "11", "13", "50", "51", "56")):
            return "sh"
        if code.startswith(("00", "30", "12", "15", "16")):
            return "sz"
        # 兜底：沪市
        return "sh"

    @staticmethod
    def code_for(code: str) -> Tuple[str, str]:
        """6 位代码 → (code, market)。"""
        return code, AShareMarket.market_of(code)

    @staticmethod
    def suffix_for(code: str) -> str:
        """6 位代码 → yfinance 式后缀 '.SS' / '.SZ'。"""
        return ".SS" if AShareMarket.market_of(code) == "sh" else ".SZ"


# 板块成分获取函数签名：sector_name -> [(code6, name), ...]
ConsFetcher = Callable[[str], List[Tuple[str, str]]]


def fetch_board_cons(sector: str) -> List[Tuple[str, str]]:
    """从 akshare 拉取概念板块成分股。

    返回 [(6位代码, 股票名称), ...]。拉取失败返回空列表（交由上层降级）。
    """
    try:
        import akshare as ak  # noqa: WPS433 — 延迟导入，避免无 akshare 时模块加载失败
        df = ak.stock_board_concept_cons_em(symbol=sector)
        if df is None or df.empty:
            return []
        out = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if code and name:
                out.append((code, name))
        return out
    except Exception:
        return []


def expand_themes(config: ThemeConfig, cons_fetcher: ConsFetcher = fetch_board_cons) -> List[Candidate]:
    """展开启用主题为候选标的池。

    Args:
        config: 已加载并过滤的主题配置。
        cons_fetcher: 板块成分获取函数（测试可注入 mock）。

    Returns:
        去重后的候选标的列表（股票带交易所后缀，基金保留原码）。
    """
    candidates: List[Candidate] = []
    seen: set = set()  # 已收录 (ticker) 去重

    for theme_name in config.enabled_theme_names():
        theme = config.get_theme(theme_name)

        # 股票：板块成分
        for sector in theme.get("sectors", []):
            for code, name in cons_fetcher(sector):
                ticker = f"{code}{AShareMarket.suffix_for(code)}"
                if ticker in seen:
                    continue
                seen.add(ticker)
                candidates.append(Candidate(
                    ticker=ticker, name=name, theme=theme_name,
                    is_fund=False, sector=sector,
                ))

        # 基金/ETF：直接取映射表代码
        for fund_code in theme.get("funds", []):
            fund_code = str(fund_code).strip()
            if not fund_code or fund_code in seen:
                continue
            seen.add(fund_code)
            candidates.append(Candidate(
                ticker=fund_code, name=f"基金{fund_code}", theme=theme_name,
                is_fund=True, sector=theme.get("sectors", [""])[0] if theme.get("sectors") else "",
            ))

    return candidates