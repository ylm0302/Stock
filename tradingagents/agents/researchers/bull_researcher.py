from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        asset_type = state.get("asset_type", "stock")

        if asset_type == "fund":
            target_label = "基金"
            fundamentals_label = "基金基本面报告（持仓、规模、费率、基金经理、业绩）"
            role_desc = "你是一位看多分析师，负责为配置该基金提供有力的论据。"
            focus_points = """
- **业绩优势**：强调基金的历史超额收益、同类排名靠前、基金经理能力圈
- **持仓质量**：重仓股的成长性、行业景气度、估值合理性
- **规模与流动性**：规模适中、申赎便利、无大额赎回压力
- **宏观顺风**：政策支持、行业趋势、市场情绪向好
- **反驳空方**：针对空方的具体论点，用数据和逻辑逐一反驳"""
        else:
            target_label = "stock" if asset_type == "stock" else "asset"
            fundamentals_label = (
                "Company fundamentals report"
                if asset_type == "stock"
                else "Asset fundamentals report (may be unavailable for crypto)"
            )
            role_desc = "You are a Bull Analyst advocating for investing in the asset."
            focus_points = """
- Growth Potential: Highlight the company's market opportunities, revenue projections, and scalability.
- Competitive Advantages: Emphasize factors like unique products, strong branding, or dominant market positioning.
- Positive Indicators: Use financial health, industry trends, and recent positive news as evidence.
- Bear Counterpoints: Critically analyze the bear argument with specific data and sound reasoning."""

        if asset_type == "fund":
            prompt = f"""{role_desc}你的任务是基于研究数据，为配置该{target_label}构建有力的论据。

重点关注：
{focus_points}

可用资料：
市场走势报告：{market_research_report}
投资者情绪报告：{sentiment_report}
宏观新闻报告：{news_report}
{fundamentals_label}：{fundamentals_report}
辩论历史：{history}
空方最新论点：{current_response}

请以对话方式呈现你的论点，直接回应空方的具体观点，展示看多立场的优势。
""" + get_language_instruction()
        else:
            prompt = f"""You are a Bull Analyst advocating for investing in the {target_label}. Your task is to build a strong, evidence-based case emphasizing growth potential, competitive advantages, and positive market indicators. Leverage the provided research and data to address concerns and counter bearish arguments effectively.

Key points to focus on:
{focus_points}
- Engagement: Present your argument in a conversational style, engaging directly with the bear analyst's points and debating effectively rather than just listing data.

Resources available:
Market research report: {market_research_report}
Social media sentiment report: {sentiment_report}
Latest world affairs news: {news_report}
{fundamentals_label}: {fundamentals_report}
Conversation history of the debate: {history}
Last bear argument: {current_response}
Use this information to deliver a compelling bull argument, refute the bear's concerns, and engage in a dynamic debate that demonstrates the strengths of the bull position.
""" + get_language_instruction()

        response = llm.invoke(prompt)
        argument = f"Bull Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
