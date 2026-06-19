"""Baostock-based stock data fetching — A 股行情降级数据源。

当 yfinance 被限速时自动接管 get_stock_data / get_indicators 请求。
baostock 服务器在中国大陆稳定可用，无需 API Key。

支持 A 股(.SS/.SZ)；非 A 股 ticker 直接返回不支持提示。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Annotated

logger = logging.getLogger(__name__)

# baostock 可用性缓存，避免每次调用都登录
_BS_SESSION: bool | None = None  # None=未初始化, True=已登录, False=不可用


def _ensure_login() -> bool:
    """确保 baostock 已登录，返回是否可用。"""
    global _BS_SESSION
    if _BS_SESSION is True:
        return True
    if _BS_SESSION is False:
        return False
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code == "0":
            _BS_SESSION = True
            logger.info("baostock 登录成功（降级数据源）")
            return True
        else:
            _BS_SESSION = False
            logger.warning("baostock 登录失败: %s", lg.error_msg)
            return False
    except Exception as e:
        _BS_SESSION = False
        logger.warning("baostock 不可用: %s", e)
        return False


def _to_bs_code(symbol: str) -> str | None:
    """将 ticker 转换为 baostock 格式 (sh.600519 / sz.300750)。

    支持格式：600519、600519.SS、600519.SZ、sh.600519 等。
    非 A 股返回 None。
    """
    s = symbol.upper().strip()
    # 已是 baostock 格式
    if s.startswith("SH.") or s.startswith("SZ."):
        return s.lower()
    # yfinance 格式
    if s.endswith(".SS"):
        return "sh." + s[:-3]
    if s.endswith(".SZ"):
        return "sz." + s[:-3]
    # 纯 6 位代码
    if s.isdigit() and len(s) == 6:
        prefix = "sh" if s.startswith(("60", "68", "11", "50", "51")) else "sz"
        return f"{prefix}.{s}"
    return None


def get_stock_data_baostock(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """用 baostock 获取 A 股日线行情数据（yfinance 限速时的降级实现）。

    返回格式与 yfinance 版兼容（CSV 字符串 + 注释头）。
    """
    bs_code = _to_bs_code(symbol)
    if bs_code is None:
        return (
            f"baostock 不支持非 A 股标的 '{symbol}'。"
            f"请使用 yfinance 或 alpha_vantage 获取该标的数据。"
        )

    if not _ensure_login():
        raise RuntimeError("baostock 不可用，无法获取行情数据")

    try:
        import baostock as bs

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,turn,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",   # 前复权
        )

        if rs.error_code != "0":
            raise RuntimeError(f"baostock 查询失败: {rs.error_msg}")

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

        # 构造与 yfinance CSV 兼容的输出
        header = (
            f"# Stock data for {symbol.upper()} from {start_date} to {end_date}"
            f" [source: baostock]\n"
            f"# Total records: {len(rows)}\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        csv_lines = ["Date,Open,High,Low,Close,Volume,Turnover,PctChg"]
        for row in rows:
            csv_lines.append(",".join(row))

        return header + "\n".join(csv_lines)

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"baostock get_stock_data 失败: {e}") from e


def get_indicators_baostock(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """用 baostock 获取技术指标（日线 + 换手率/涨跌幅）。"""
    # 与 get_stock_data 返回相同格式，agent 可从中提取技术面信息
    return get_stock_data_baostock(symbol, start_date, end_date)
