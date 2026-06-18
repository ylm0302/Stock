"""Markdown 报告生成器（纯函数）。"""

from __future__ import annotations

from typing import Dict, List, Optional

from .models import ScoredCandidate


def _fmt_pct(x) -> str:
    if x is None:
        return "-"
    return f"{x*100:.2f}%"


def _stock_row(s: ScoredCandidate) -> str:
    m = s.metrics
    return (
        f"| {s.ticker} | {s.name} | {s.theme} | {s.composite_score:.0f} | "
        f"{_fmt_pct(m.get('main_net_inflow_ratio'))} | "
        f"{_fmt_pct(m.get('price_gain_ratio'))} | "
        f"{_fmt_pct(m.get('turnover_rate'))} | {s.reason} |"
    )


def _fund_row(s: ScoredCandidate) -> str:
    m = s.metrics
    return (
        f"| {s.ticker} | {s.name} | {s.theme} | {s.composite_score:.0f} | "
        f"{_fmt_pct(m.get('share_change_ratio'))} | "
        f"{_fmt_pct(m.get('price_gain_ratio'))} | {s.reason} |"
    )


def render_report(
    ranked: List[ScoredCandidate],
    themes: List[str],
    date: str,
    deep_results: Dict[str, Optional[str]],
) -> str:
    """渲染 Markdown 推荐池报告。

    Args:
        ranked: 排序后的推荐标的。
        themes: 本次启用的主题名列表。
        date: 分析日期（yyyy-mm-dd）。
        deep_results: ticker -> 深度配置建议文本（None 表示该标的深度分析失败）。
    """
    stocks = [s for s in ranked if not s.is_fund]
    funds = [s for s in ranked if s.is_fund]

    lines = [
        f"# 政策扶持标的推荐池 ({date})",
        "",
        "## 筛选条件",
        f"- 主题：{', '.join(themes)}",
        "- 资金面：主力介入度低（净流入/市值 ≤1%，涨幅 ≤15%，换手 ≤5%）",
        "- 数据源：akshare + LLM 双轨",
        "",
    ]

    if not ranked:
        lines.append("> 本轮未筛选出符合条件的标的。可放宽阈值或更换主题后重试。")
        return "\n".join(lines)

    # 推荐股票
    lines.append("## 推荐股票")
    lines.append("| 代码 | 名称 | 主题 | 综合分 | 近期主力净流入/市值 | 区间涨幅 | 换手率 | 推荐理由 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    if stocks:
        lines.extend(_stock_row(s) for s in stocks)
    else:
        lines.append("| - | - | - | - | - | - | - | 无 |")
    lines.append("")

    # 推荐基金/ETF
    lines.append("## 推荐基金/ETF")
    lines.append("| 代码 | 名称 | 主题 | 综合分 | 份额变化 | 区间涨幅 | 推荐理由 |")
    lines.append("|---|---|---|---|---|---|---|")
    if funds:
        lines.extend(_fund_row(s) for s in funds)
    else:
        lines.append("| - | - | - | - | - | - | 无 |")
    lines.append("")

    # 深度配置建议
    deep_items = [(s, deep_results.get(s.ticker, "__MISSING__")) for s in ranked if s.ticker in deep_results]
    if deep_items:
        lines.append("## 深度配置建议")
        lines.append("")
        for s, text in deep_items:
            lines.append(f"### {s.ticker} —— {s.name}（综合分 {s.composite_score:.0f}）")
            if text is None:
                lines.append("> ⚠️ 深度分析失败，跳过配置建议。")
            else:
                lines.append(text)
            lines.append("")

    return "\n".join(lines)