"""
基金情绪分析师
分析基金投资者情绪、市场热度、资金流向等，
替代原 sentiment_analyst 中针对个股社交媒体的分析逻辑。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_language_instruction,
    get_news,
    get_global_news,
)
from tradingagents.agents.utils.fund_tools import (
    fund_get_nav_history,
    fund_get_performance,
    fund_get_comparison,
    fund_get_portfolio,
)


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def _thirty_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d")


def create_fund_sentiment_analyst(llm):
    """创建基金情绪分析师节点。"""

    def fund_sentiment_analyst_node(state):
        current_date = state["trade_date"]
        fund_code = state["company_of_interest"]
        start_date = _seven_days_back(current_date)
        start_date_30 = _thirty_days_back(current_date)

        tools = [
            fund_get_nav_history,
            fund_get_performance,
            fund_get_comparison,
            fund_get_portfolio,
            get_news,
            get_global_news,
        ]

        system_message = f"""你是一位专业的基金投资者情绪分析师，负责分析基金 `{fund_code}` 的市场情绪和资金流向。

请按以下步骤进行分析：

1. **fund_get_nav_history** — 获取近30天净值历史，分析净值波动和资金申赎信号
2. **fund_get_performance** — 获取近期业绩排名，判断基金是否处于"热门"或"冷门"状态
3. **fund_get_comparison** — 获取同类排名百分位，判断相对吸引力
4. **get_news** — 搜索以下情绪相关信息：
   - "公募基金申购赎回" 或 "基金净申购"
   - "基金市场情绪" 或 "基金热度"
   - 基金所属行业的投资者情绪
5. **fund_get_portfolio** — （可选）获取基金前十大重仓股及其持仓比例
6. **get_global_news** — （可选）获取宏观市场新闻和行业动态，了解影响基金投资领域的政策、经济数据和市场情绪变化。

注意：get_news 接受的是股票代码/搜索关键词。如果针对重仓股查新闻，请用 A 股代码格式（如 "600036.SS"），不要传入基金代码 "{fund_code}"。

**分析重点：**

**净值动量信号：**
- 近7天/30天净值涨跌幅（正动量 vs 负动量）
- 净值是否创近期新高/新低
- 净值波动率是否异常放大（可能预示大额申赎）

**排名与相对吸引力：**
- 同类排名是否持续上升（吸引资金流入）
- 排名是否大幅下滑（触发赎回压力）
- 是否处于同类前25%（优质区间）

**市场情绪指标：**
- 公募基金整体仓位水平（高仓位 = 乐观情绪）
- 行业主题基金的热度（如新能源、AI、消费等）
- 是否有大V/机构推荐该基金或同类基金

**风险信号：**
- 规模快速缩水（大额赎回压力）
- 同类基金普遍下跌（系统性风险）
- 基金经理变更引发的情绪波动

**报告要求：**
- 给出综合情绪判断：乐观/中性/悲观
- 区分散户情绪和机构情绪（如有数据）
- 在报告末尾附上 Markdown 表格，汇总情绪信号

当前分析日期：{current_date}，参考区间：{start_date_30} 至 {current_date}
""" + get_language_instruction()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一位专业的基金情绪分析助手，与其他分析师协作完成基金评估任务。"
                    " 使用提供的工具逐步收集数据，完成情绪分析报告。"
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
            "sentiment_report": report,
        }

    return fund_sentiment_analyst_node
