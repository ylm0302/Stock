"""
基金基本面分析师
分析基金的持仓、规模、费率、基金经理历史、业绩等核心指标，
替代原股票 fundamentals_analyst 中针对公司财报的分析逻辑。
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import get_language_instruction
from tradingagents.agents.utils.fund_tools import (
    fund_get_basic_info,
    fund_get_portfolio,
    fund_get_performance,
    fund_get_manager,
    fund_get_asset_allocation,
    fund_get_fee,
    fund_get_comparison,
)


def create_fund_fundamentals_analyst(llm):
    """创建基金基本面分析师节点。"""

    def fund_fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        fund_code = state["company_of_interest"]

        tools = [
            fund_get_basic_info,
            fund_get_portfolio,
            fund_get_performance,
            fund_get_manager,
            fund_get_asset_allocation,
            fund_get_fee,
            fund_get_comparison,
        ]

        system_message = f"""你是一位专业的公募基金研究员，负责对基金代码 `{fund_code}` 进行全面的基本面分析。

请按以下步骤调用工具，收集完整信息后撰写分析报告：

1. **fund_get_basic_info** — 获取基金名称、类型、成立日期、基金公司、投资目标
2. **fund_get_performance** — 获取各期收益率和同类排名，评估历史业绩
3. **fund_get_manager** — 分析基金经理背景、任职年限、历史管理业绩
4. **fund_get_portfolio** — 分析前十大重仓股/债券，判断持仓集中度和行业分布
5. **fund_get_asset_allocation** — 分析股债配置比例变化趋势和规模变动
6. **fund_get_fee** — 评估持有成本（管理费、申购赎回费）
7. **fund_get_comparison** — 与同类基金横向比较，判断相对竞争力

**报告要求：**
- 对每个维度给出明确的评价（优/良/中/差）和支撑数据
- 重点分析：基金经理稳定性、持仓集中度风险、规模是否过大影响操作灵活性
- 识别潜在风险：持仓行业集中、规模快速缩水、基金经理变更等
- 给出综合评分（1-10分）和配置建议（积极配置/标准配置/谨慎配置/不建议配置）
- 在报告末尾附上 Markdown 表格，汇总关键指标

当前分析日期：{current_date}
""" + get_language_instruction()

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是一位专业的基金研究助手，与其他分析师协作完成基金评估任务。"
                    " 使用提供的工具逐步收集数据，完成分析报告。"
                    " 如果某个工具调用失败，记录失败原因并继续分析其他维度。"
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
            "fundamentals_report": report,
        }

    return fund_fundamentals_analyst_node
