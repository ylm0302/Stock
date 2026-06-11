from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        asset_type = state.get("asset_type", "stock")

        if asset_type == "fund":
            target_label = "基金"
            fundamentals_label = "基金基本面报告（持仓、规模、费率、基金经理、业绩）"
            role_desc = "你是一位看空分析师，负责指出配置该基金的风险和不利因素。"
            focus_points = """
- **业绩风险**：历史业绩不稳定、同类排名下滑、超额收益衰减
- **持仓风险**：重仓股集中度过高、行业景气度下行、估值偏贵
- **规模风险**：规模过大影响操作灵活性、大额赎回压力、规模快速缩水
- **管理风险**：基金经理变更、投资风格漂移、基金公司治理问题
- **宏观逆风**：政策收紧、行业监管、市场情绪恶化
- **反驳多方**：针对多方的具体论点，用数据和逻辑逐一反驳"""
        else:
            target_label = "stock" if asset_type == "stock" else "asset"
            fundamentals_label = (
                "Company fundamentals report"
                if asset_type == "stock"
                else "Asset fundamentals report (may be unavailable for crypto)"
            )
            role_desc = "You are a Bear Analyst making the case against investing in the asset."
            focus_points = """
- Risks and Challenges: Highlight factors like market saturation, financial instability, or macroeconomic threats.
- Competitive Weaknesses: Emphasize vulnerabilities such as weaker market positioning or threats from competitors.
- Negative Indicators: Use evidence from financial data, market trends, or recent adverse news.
- Bull Counterpoints: Critically analyze the bull argument with specific data and sound reasoning."""

        if asset_type == "fund":
            prompt = f"""{role_desc}你的任务是基于研究数据，指出配置该{target_label}的风险和不利因素。

重点关注：
{focus_points}

可用资料：
市场走势报告：{market_research_report}
投资者情绪报告：{sentiment_report}
宏观新闻报告：{news_report}
{fundamentals_label}：{fundamentals_report}
辩论历史：{history}
多方最新论点：{current_response}

请以对话方式呈现你的论点，直接回应多方的具体观点，揭示其过于乐观的假设和被忽视的风险。
""" + get_language_instruction()
        else:
            prompt = f"""You are a Bear Analyst making the case against investing in the {target_label}. Your goal is to present a well-reasoned argument emphasizing risks, challenges, and negative indicators. Leverage the provided research and data to highlight potential downsides and counter bullish arguments effectively.

Key points to focus on:
{focus_points}
- Engagement: Present your argument in a conversational style, directly engaging with the bull analyst's points and debating effectively rather than simply listing facts.

Resources available:
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bull argument: {current_response}
Use this information to deliver a compelling bear argument, refute the bull's claims, and engage in a dynamic debate that demonstrates the risks and weaknesses of investing in the {target_label}.
""" + get_language_instruction()

        response = llm.invoke(prompt)
        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
