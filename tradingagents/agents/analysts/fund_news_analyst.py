"""
基金新闻与宏观分析师
分析与基金投资方向相关的行业新闻、宏观经济政策，
以及基金重仓股的最新动态，替代原 news_analyst 的股票新闻逻辑。
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    get_language_instruction,
    get_news,
    get_global_news,
)
from tradingagents.agents.utils.fund_tools import (
    fund_get_basic_info,
    fund_get_portfolio,
)


def create_fund_news_analyst(llm):
    """创建基金新闻与宏观分析师节点。"""

    def fund_news_analyst_node(state):
        current_date = state["trade_date"]
        fund_code = state["company_of_interest"]

        tools = [
            fund_get_basic_info,
            fund_get_portfolio,
            get_news,
            get_global_news,
        ]

        system_message = f"""你是一位专业的基金宏观与新闻分析师，负责分析影响基金 `{fund_code}` 的宏观环境和行业动态。

请按以下步骤进行分析：

1. **fund_get_basic_info** — 了解基金的投资方向和主要投资领域
2. **fund_get_portfolio** — 获取重仓股，确定需要重点关注的行业和个股
3. **get_news** — 搜索以下相关新闻（每类搜索1-2次）：
   - 基金所属行业的最新动态（如"消费行业政策"、"科技股监管"等）
   - 主要重仓股的近期新闻
   - 基金公司或基金经理的相关新闻
4. **get_global_news** — 获取宏观经济新闻，关注：
   - 货币政策（央行降息/加息、流动性）
   - 监管政策（证监会、行业监管）
   - 宏观经济数据（GDP、CPI、PMI）
   - 国际市场风险（地缘政治、汇率）

**分析重点：**
- 宏观政策对基金投资方向的利好/利空影响
- 行业景气度变化（上行/平稳/下行）
- 重仓股是否有重大利好或利空事件
- 市场情绪和资金流向（北向资金、公募仓位）
- 近期是否有影响基金净值的重大催化剂

**报告要求：**
- 区分短期（1个月内）和中期（3-6个月）影响
- 明确标注利好/利空/中性
- 在报告末尾附上 Markdown 表格，汇总关键新闻事件及其影响

当前分析日期：{current_date}
""" + get_language_instruction()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一位专业的基金宏观与新闻分析助手，与其他分析师协作完成基金评估任务。"
                    " 使用提供的工具逐步收集数据，完成新闻与宏观分析报告。"
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
            "news_report": report,
        }

    return fund_news_analyst_node
