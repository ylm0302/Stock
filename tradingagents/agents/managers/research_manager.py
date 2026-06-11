"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])
        asset_type = state.get("asset_type", "stock")
        history = state["investment_debate_state"].get("history", "")
        investment_debate_state = state["investment_debate_state"]

        # 基金模式使用基金配置语义
        if asset_type == "fund":
            rating_scale = """**配置建议等级**（从以下选项中选择一个）：
- **积极配置（Buy）**: 对基金前景有强烈信心，建议大幅增加配置
- **标准配置（Overweight）**: 基金表现良好，建议适度增加配置
- **维持配置（Hold）**: 基金表现平稳，建议维持当前配置
- **谨慎配置（Underweight）**: 基金存在风险，建议适度降低配置
- **赎回（Sell）**: 基金风险较大，建议赎回或避免配置

作为研究经理，请综合多空辩论，给出明确的基金配置建议。当辩论中有一方明显占优时，请给出明确立场；仅在双方论据真正均衡时才选择"维持配置"。"""
        else:
            rating_scale = """**Rating Scale** (use exactly one):
- **Buy**: Strong conviction in the bull thesis; recommend taking or growing the position
- **Overweight**: Constructive view; recommend gradually increasing exposure
- **Hold**: Balanced view; recommend maintaining the current position
- **Underweight**: Cautious view; recommend trimming exposure
- **Sell**: Strong conviction in the bear thesis; recommend exiting or avoiding the position

Commit to a clear stance whenever the debate's strongest arguments warrant one; reserve Hold for situations where the evidence on both sides is genuinely balanced."""

        prompt = f"""As the Research Manager and debate facilitator, your role is to critically evaluate this round of debate and deliver a clear, actionable investment plan for the trader.

{instrument_context}

---

{rating_scale}

---

**Debate History:**
{history}""" + get_language_instruction()

        investment_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
