"""
基金预测入口示例
使用 TradingAgents 框架对国内公募基金进行配置建议分析

使用前请确保：
1. 安装 akshare：pip install akshare
2. 配置 LLM API Key（见 .env.example）
3. 基金代码格式：6位数字，如 "000001"（华夏成长）

运行示例：
    python fund_main.py
"""

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# ── 配置 ──────────────────────────────────────────────────────────────────────
config = DEFAULT_CONFIG.copy()

# LLM 设置（根据你的 API Key 选择）
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-v4-pro"   # DeepSeek-R1，用于复杂推理
config["quick_think_llm"] = "deepseek-v4-flash"       # DeepSeek-V3，用于快速分析

# 基金分析专项配置
config["output_language"] = "Chinese"      # 报告输出语言：中文
config["max_debate_rounds"] = 1            # 多空辩论轮数（1-3，越多越深入但耗时更长）
config["max_risk_discuss_rounds"] = 1      # 风险讨论轮数
config["fund_benchmark_ticker"] = "510300.SS"  # 业绩基准：沪深300ETF

# ── 初始化 ────────────────────────────────────────────────────────────────────
ta = TradingAgentsGraph(
    selected_analysts=["market", "social", "news", "fundamentals"],
    debug=True,
    config=config,
)

# ── 运行基金分析 ───────────────────────────────────────────────────────────────
# 示例基金：
#   "000001" — 华夏成长混合
#   "110022" — 易方达消费行业股票
#   "161725" — 招商中证白酒指数
#   "270002" — 广发稳增债券
#   "000961" — 天弘沪深300ETF联接A

FUND_CODE = "110022"       # 易方达消费行业股票
ANALYSIS_DATE = "2025-01-15"  # 分析日期（yyyy-mm-dd）

print(f"\n{'='*60}")
print(f"  基金配置分析")
print(f"  基金代码：{FUND_CODE}")
print(f"  分析日期：{ANALYSIS_DATE}")
print(f"{'='*60}\n")

_, decision = ta.propagate(
    company_name=FUND_CODE,
    trade_date=ANALYSIS_DATE,
    asset_type="fund",          # ← 关键：指定为基金模式
)

print("\n" + "="*60)
print("  最终配置建议")
print("="*60)
print(decision)
