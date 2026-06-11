"""
基金市场走势分析师
分析基金净值走势、技术形态。
仅使用基金净值数据（akshare），不调用 yfinance 股票接口，
避免 A 股代码在 Yahoo Finance 触发限流。
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.fund_tools import (
    fund_get_nav_history,
    fund_get_portfolio,
    fund_get_performance,
)


def create_fund_market_analyst(llm):
    """创建基金市场走势分析师节点。"""

    def fund_market_analyst_node(state):
        current_date = state["trade_date"]
        fund_code = state["company_of_interest"]

        tools = [
            fund_get_nav_history,
            fund_get_portfolio,
            fund_get_performance,
        ]

        system_message = f"""你是一位专业的基金市场走势分析师，负责分析基金代码 `{fund_code}` 的净值走势和市场表现。

请按以下步骤进行分析：

1. **fund_get_nav_history** — 分别获取以下两段净值历史：
   - 近3个月（短期趋势）：start_date 为当前日期往前90天
   - 近1年（中长期趋势）：start_date 为当前日期往前365天
2. **fund_get_portfolio** — 获取最新持仓，了解行业分布
3. **fund_get_performance** — 获取各期收益率，辅助判断净值所处历史区间

**基于净值数据进行技术分析：**

- **趋势判断**：
  - 近3个月净值是否处于上升/震荡/下降趋势
  - 近1年高点和低点分别是多少，当前净值处于什么位置（高位/中位/低位）
  - 计算近3个月、近1个月的涨跌幅

- **波动率分析**：
  - 近3个月日涨跌幅的平均绝对值（波动率高低）
  - 是否有单日大幅波动（>3%）的异常情况

- **动量信号**：
  - 近5个交易日净值走势（短期动量）
  - 近20个交易日净值走势（中期动量）
  - 是否出现连续上涨/下跌的加速信号

- **关键价位**：
  - 近3个月的净值支撑区间（低点附近）
  - 近3个月的净值压力区间（高点附近）

**报告要求：**
- 给出明确的技术面判断：看多 / 中性 / 看空
- 标注当前净值的历史分位（近1年）
- 在报告末尾附上 Markdown 表格，汇总关键技术指标

当前分析日期：{current_date}
""" + get_language_instruction()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一位专业的基金市场分析助手，与其他分析师协作完成基金评估任务。"
                    " 使用提供的工具逐步收集数据，完成市场走势分析报告。"
                    " 你有以下工具可用: {tool_names}。\n{system_message}"
                    " 当前日期: {current_date}。",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([t.name for t in tools]))
        prompt = prompt.partial(current_date=current_date)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "market_report": report,
        }

    return fund_market_analyst_node
