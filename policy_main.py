"""
政策扶持标的推荐筛选器入口
按"国家政策扶持 + 主力资金未介入"筛选 A 股股票与基金/ETF，
输出 Markdown 推荐池报告，可选对 Top 标的跑多 Agent 深度配置建议。

运行示例：
    python policy_main.py
    python policy_main.py --themes 新质生产力,低空经济 --date 2026-06-18 --deep

使用前请确保：
1. 安装 akshare：pip install akshare
2. 配置 LLM API Key（见 .env.example）
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.policy_screener.runner import PolicyScreenerRunner, build_llm


def main():
    parser = argparse.ArgumentParser(description="政策扶持标的推荐筛选器")
    parser.add_argument("--themes", type=str, default="",
                        help="主题名，逗号分隔，如 '新质生产力,低空经济'；留空启用全部")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"),
                        help="分析日期 yyyy-mm-dd")
    parser.add_argument("--deep", action="store_true",
                        help="对 Top N 跑多 Agent 深度配置建议（需 API Key）")
    parser.add_argument("--out", type=str, default=None,
                        help="报告输出路径，默认 reports/policy_<date>.md")
    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = os.environ.get("TRADINGAGENTS_LLM_PROVIDER", "deepseek")
    config["deep_think_llm"] = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", "deepseek-reasoner")
    config["quick_think_llm"] = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", "deepseek-chat")
    config["output_language"] = "Chinese"

    themes = [t.strip() for t in args.themes.split(",") if t.strip()]

    llm = build_llm(config)
    graph = None
    if args.deep and llm is not None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            debug=True, config=config,
        )

    runner = PolicyScreenerRunner(config, llm=llm, graph=graph)
    report = runner.run(themes=themes, date=args.date, deep_analyze=args.deep)

    out_path = args.out or os.path.join("reports", f"policy_{args.date}.md")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n报告已保存至 {out_path}")


if __name__ == "__main__":
    main()