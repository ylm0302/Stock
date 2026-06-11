"""
基金分析专用 LangChain 工具集
供基金分析师 Agent 调用
"""

from __future__ import annotations

from typing import Annotated
from langchain_core.tools import tool

from tradingagents.dataflows.fund_data import (
    get_fund_info,
    get_fund_nav_history,
    get_fund_portfolio,
    get_fund_performance,
    get_fund_manager,
    get_fund_asset_allocation,
    get_fund_fee,
    get_fund_comparison,
)


@tool
def fund_get_basic_info(
    fund_code: Annotated[str, "基金代码，如 '000001'（华夏成长）或 '110022'（易方达消费行业）"],
    curr_date: Annotated[str, "当前日期 yyyy-mm-dd"] = None,
) -> str:
    """获取基金基本信息：基金名称、类型、成立日期、基金公司、基金规模、投资目标等。"""
    return get_fund_info(fund_code, curr_date)


@tool
def fund_get_nav_history(
    fund_code: Annotated[str, "基金代码"],
    start_date: Annotated[str, "开始日期 yyyy-mm-dd"],
    end_date: Annotated[str, "结束日期 yyyy-mm-dd"],
) -> str:
    """获取基金净值历史（单位净值和累计净值），用于分析净值走势和收益表现。"""
    return get_fund_nav_history(fund_code, start_date, end_date)


@tool
def fund_get_portfolio(
    fund_code: Annotated[str, "基金代码"],
    curr_date: Annotated[str, "当前日期 yyyy-mm-dd，用于获取最近一期持仓报告"] = None,
) -> str:
    """获取基金最新持仓：前十大重仓股（股票型/混合型）或前五大重仓债券（债券型），包含持仓比例。"""
    return get_fund_portfolio(fund_code, curr_date)


@tool
def fund_get_performance(
    fund_code: Annotated[str, "基金代码"],
    curr_date: Annotated[str, "当前日期 yyyy-mm-dd"] = None,
) -> str:
    """获取基金业绩指标：近1/3/6月、近1/2/3年收益率，以及同类基金排名百分位。"""
    return get_fund_performance(fund_code, curr_date)


@tool
def fund_get_manager(
    fund_code: Annotated[str, "基金代码"],
    curr_date: Annotated[str, "当前日期 yyyy-mm-dd"] = None,
) -> str:
    """获取基金经理信息：姓名、任职时间、历史管理基金列表、任职期间回报率等。"""
    return get_fund_manager(fund_code, curr_date)


@tool
def fund_get_asset_allocation(
    fund_code: Annotated[str, "基金代码"],
    curr_date: Annotated[str, "当前日期 yyyy-mm-dd"] = None,
) -> str:
    """获取基金资产配置比例（股票/债券/现金/其他）及规模变化趋势（最近4期季报）。"""
    return get_fund_asset_allocation(fund_code, curr_date)


@tool
def fund_get_fee(
    fund_code: Annotated[str, "基金代码"],
) -> str:
    """获取基金费率信息：管理费率、托管费率、申购费率、赎回费率等，用于评估持有成本。"""
    return get_fund_fee(fund_code)


@tool
def fund_get_comparison(
    fund_code: Annotated[str, "基金代码"],
    curr_date: Annotated[str, "当前日期 yyyy-mm-dd"] = None,
) -> str:
    """获取同类基金排名和百分比，用于横向比较该基金在同类产品中的相对表现。"""
    return get_fund_comparison(fund_code, curr_date)
