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
    """从 akshare 拉取概念板块成分股，带名称容错。

    1. 先用精确名拉成分股；拉空则进入容错。
    2. 容错：拉取东财全部概念板块名，用关键词模糊匹配最接近的一个，再拉成分股。
    返回 [(6位代码, 股票名称), ...]。失败返回空列表（交由上层降级）。
    """
    try:
        import akshare as ak  # noqa: WPS433 — 延迟导入，避免无 akshare 时模块加载失败
        result = _try_fetch_cons(ak, sector)
        if result:
            return result
        # 精确名拉空 → 模糊匹配
        matched = _fuzzy_match_board(ak, sector)
        if matched and matched != sector:
            return _try_fetch_cons(ak, matched)
        return []
    except Exception:
        return []


def _try_fetch_cons(ak, sector: str) -> List[Tuple[str, str]]:
    """用精确板块名拉成分股。"""
    try:
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


def _fuzzy_match_board(ak, sector: str) -> str:
    """在东财全部概念板块名中，找与 sector 最接近的一个。"""
    try:
        df = ak.stock_board_concept_name_em()
        if df is None or df.empty:
            return ""
        names = df["板块名称"].astype(str).tolist()
        # 1) sector 本身就是某板块名
        if sector in names:
            return sector
        # 2) 任意板块名包含 sector，或 sector 包含板块名
        for n in names:
            if sector in n or n in sector:
                return n
        # 3) 按字符重叠度排序（取最像的）
        def _overlap(n: str) -> int:
            return sum(1 for ch in sector if ch in n)
        best = max(names, key=_overlap, default="")
        # 至少要有一半字符重叠，避免乱匹配
        if best and _overlap(best) >= len(sector) / 2:
            return best
        return ""
    except Exception:
        return ""


def expand_themes(config, cons_fetcher: ConsFetcher = fetch_board_cons) -> List[Candidate]:
    """展开启用板块为候选标的池。

    Args:
        config: 已加载并过滤的板块配置（BoardConfig 或 ThemeConfig）。
        cons_fetcher: 板块成分获取函数（测试可注入 mock）。

    Returns:
        去重后的候选标的列表（股票带交易所后缀，基金保留原码）。
    """
    candidates: List[Candidate] = []
    seen: set = set()  # 已收录 (ticker) 去重

    for board_name in config.enabled_board_names():
        board = config.get_board(board_name) if hasattr(config, "get_board") else None
        if board is None:
            # 旧 ThemeConfig 兼容
            theme = config.get_theme(board_name)
            sectors = theme.get("sectors", [])
            funds = theme.get("funds", [])
            keywords = theme.get("keywords", [])
        else:
            sectors = board.sectors
            funds = board.funds
            keywords = board.keywords

        # 股票（动态）：完全依赖 akshare 拉取板块成分，不使用任何预置静态列表
        for sector in sectors:
            cons = cons_fetcher(sector)
            for code, name in cons:
                ticker = f"{code}{AShareMarket.suffix_for(code)}"
                if ticker in seen:
                    continue
                seen.add(ticker)
                candidates.append(Candidate(
                    ticker=ticker, name=name, theme=board_name,
                    is_fund=False, sector=sector,
                ))

        # 基金/ETF：直接取映射表代码
        for fund_code in funds:
            fund_code = str(fund_code).strip()
            if not fund_code or fund_code in seen:
                continue
            seen.add(fund_code)
            candidates.append(Candidate(
                ticker=fund_code, name=f"基金{fund_code}", theme=board_name,
                is_fund=True, sector=sectors[0] if sectors else "",
            ))

    return candidates