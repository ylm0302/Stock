"""Markdown 报告生成器（纯函数）。"""

from __future__ import annotations

from typing import Dict, List, Optional

from .models import ScoredCandidate


def render_hotspot_report(
    ranked: List[ScoredCandidate],
    hotspots: List[dict],
    news_summary: str,
    date: str,
    deep_results: Dict[str, Optional[str]],
) -> str:
    """渲染「新闻热点自动推荐」报告。

    与 render_report 相比，额外展示：
    - 新闻热点摘要（LLM 识别的主题 + 原因）
    - 每条推荐附带与热点的关联说明
    """
    stocks = [s for s in ranked if not s.is_fund]
    funds  = [s for s in ranked if s.is_fund]
    themes = list({s.theme for s in ranked})

    lines = [
        f"# 📰 新闻热点自动推荐报告 ({date})",
        "",
        "## 🔥 当前识别热点",
        "",
    ]

    if hotspots:
        for h in hotspots:
            theme   = h.get("theme", "")
            reason  = h.get("reason", "")
            boards  = h.get("matched_boards", [])
            kw_str  = "、".join(h.get("keywords", []))
            board_str = "、".join(boards) if boards else "—"
            lines.append(f"### 🏷 {theme}")
            lines.append(f"- **政策逻辑**：{reason}")
            lines.append(f"- **关键词**：{kw_str}")
            lines.append(f"- **匹配板块**：{board_str}")
            lines.append("")
    else:
        lines.append("> 未能识别到明确热点，已使用内置默认板块。")
        lines.append("")

    lines += [
        "---",
        "",
        "## 📋 筛选原则",
        "- **国家政策支撑**：仅纳入有政策主题的板块",
        "- **主力尚未大举介入**：主力净流入/市值 ≤ 1%，区间涨幅 ≤ 15%，日均换手 ≤ 5%",
        "- **数据来源**：akshare 实时行情 + LLM 定性评估",
        "",
    ]

    if not ranked:
        lines.append("> ⚠️ 本轮未筛选出符合条件的标的，可稍后重试或检查数据源。")
        return "\n".join(lines)

    # ── 推荐股票 ──
    lines.append("## 📈 推荐股票")
    lines.append("")
    lines.append("| 代码 | 名称 | 所属热点 | 综合分 | 主力净流入/市值 | 区间涨幅 | 换手率 | 推荐理由 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    if stocks:
        lines.extend(_stock_row(s) for s in stocks)
    else:
        lines.append("| — | — | — | — | — | — | — | 当前暂无符合条件的股票 |")
    lines.append("")

    # ── 推荐基金/ETF ──
    lines.append("## 💰 推荐基金/ETF")
    lines.append("")
    lines.append("| 代码 | 名称 | 所属热点 | 综合分 | 份额变化 | 区间涨幅 | 推荐理由 |")
    lines.append("|---|---|---|---|---|---|---|")
    if funds:
        lines.extend(_fund_row(s) for s in funds)
    else:
        lines.append("| — | — | — | — | — | — | 当前暂无符合条件的基金 |")
    lines.append("")

    # ── 深度配置建议 ──
    deep_items = [(s, deep_results[s.ticker]) for s in ranked if s.ticker in deep_results]
    if deep_items:
        lines.append("## 🔬 深度配置建议（Top 标的）")
        lines.append("")
        for s, text in deep_items:
            lines.append(f"### {s.ticker} — {s.name}（综合分 {s.composite_score:.0f}）")
            if text is None:
                lines.append("> ⚠️ 深度分析失败，跳过配置建议。")
            else:
                lines.append(text)
            lines.append("")

    lines += [
        "---",
        f"*报告生成时间：{date}　数据来源：东财/财新/akshare　LLM 辅助分析*",
    ]

    return "\n".join(lines)


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