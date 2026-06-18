"""政策扶持标的推荐筛选器 CLI 子命令。

通过函数入口 run_policy_recommend 暴露，便于测试与被 cli/main.py 集成。
"""

from __future__ import annotations

from typing import List, Optional

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.policy_screener.runner import PolicyScreenerRunner


def _build_llm(config: dict):
    """按 config 构造 LLM；失败返回 None。"""
    try:
        from tradingagents.llm_clients.factory import create_llm_client
        provider = config["llm_provider"]
        model = config["quick_think_llm"]
        client = create_llm_client(provider, model, config.get("backend_url"))
        return client.get_llm()
    except Exception:
        return None


def run_policy_recommend(
    themes: List[str],
    date: str,
    deep: bool = False,
    config_overrides: Optional[dict] = None,
) -> str:
    """运行政策推荐筛选，打印报告并返回报告文本。"""
    config = DEFAULT_CONFIG.copy()
    config["output_language"] = "Chinese"
    if config_overrides:
        config.update(config_overrides)

    llm = _build_llm(config)
    graph = None
    if deep and llm is not None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            debug=True, config=config,
        )

    runner = PolicyScreenerRunner(config, llm=llm, graph=graph)
    report = runner.run(themes=themes, date=date, deep_analyze=deep)
    print(report)
    return report