"""Markdown 报告生成器（纯函数）。"""

from __future__ import annotations

from typing import Dict, List, Optional

from .models import ScoredCandidate


# ── 工具函数 ─────────────────────────────────────────────────────

def _fmt_pct(x) -> str:
    if x is None:
        return "-"
    return f"{x * 100:.2f}%"


def _fmt_price(x) -> str:
    if x is None:
        return "-"
    return f"¥{x:.2f}"


def _stars(n: int) -> str:
    """整数 1-5 → ⭐⭐⭐ 字符串。0 返回 '未评级'。"""
    if not n:
        return "未评级"
    return "⭐" * max(1, min(5, n))


# ── 热点报告（主力程报告）─────────────────────────────────────────

def render_hotspot_report(
    ranked: List[ScoredCandidate],
    hotspots: List[dict],
    news_summary: str,
    date: str,
    deep_results: Dict[str, Optional[str]],
) -> str:
    """渲染「新闻热点自动推荐」报告，含多空辩论和买入意愿星级。"""

    stocks = [s for s in ranked if not s.is_fund]
    funds  = [s for s in ranked if s.is_fund]

    lines = [
        f"# 📰 新闻热点自动推荐报告 ({date})",
        "",
        "## 🔥 当前识别热点",
        "",
    ]

    if hotspots:
        for h in hotspots:
            theme     = h.get("theme", "")
            reason    = h.get("reason", "")
            boards    = h.get("matched_boards", [])
            kw_str    = "、".join(h.get("keywords", []))
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
        "- **价格可及**：优先筛选普通投资者可购买价位的标的",
        "- **多空辩论**：LLM 从多空两个视角评估，给出买入意愿星级（1-5⭐）",
        "- **数据来源**：akshare / baostock 实时行情 + LLM 辅助分析",
        "",
    ]

    if not ranked:
        lines.append("> ⚠️ 本轮未筛选出符合条件的标的，可稍后重试或检查数据源。")
        return "\n".join(lines)

    # ── 推荐股票 ──────────────────────────────────────────────────
    lines += ["## 📈 推荐股票", ""]
    if stocks:
        for s in stocks:
            lines.extend(_detail_block(s))
    else:
        lines.append("> 当前暂无符合条件的股票（可能已全部被涨幅/价格过滤）")
    lines.append("")

    # ── 推荐基金/ETF ──────────────────────────────────────────────
    lines += ["## 💰 推荐基金 / ETF", ""]
    if funds:
        for s in funds:
            lines.extend(_detail_block(s))
    else:
        lines.append("> 当前暂无符合条件的基金")
    lines.append("")

    # ── 深度配置建议（可选）──────────────────────────────────────
    deep_items = [(s, deep_results[s.ticker]) for s in ranked if s.ticker in deep_results]
    if deep_items:
        lines += ["## 🔬 深度配置建议（Top 标的）", ""]
        for s, text in deep_items:
            lines.append(f"### {s.ticker} — {s.name}（综合分 {s.composite_score:.0f}）")
            if text is None:
                lines.append("> ⚠️ 深度分析失败，跳过配置建议。")
            else:
                lines.append(text)
            lines.append("")

    lines += [
        "---",
        f"*报告生成时间：{date}　数据来源：东财 / 财新 / akshare / baostock　LLM 辅助分析*",
    ]
    return "\n".join(lines)


def _detail_block(s: ScoredCandidate) -> List[str]:
    """生成单只标的的详情卡片（Markdown 块）。"""
    m       = s.metrics
    stars   = _stars(s.buy_willing_stars)
    price   = _fmt_price(s.current_price)
    gain    = _fmt_pct(m.get("price_gain_ratio"))
    inflow  = _fmt_pct(m.get("main_net_inflow_ratio"))
    turn    = _fmt_pct(m.get("turnover_rate"))
    label   = "基金/ETF" if s.is_fund else "股票"

    lines = [
        f"### {s.ticker} · {s.name} &nbsp; {stars}",
        "",
        f"| 项目 | 数据 |",
        f"|---|---|",
        f"| 类型 | {label} |",
        f"| 所属热点 | {s.theme} |",
        f"| 综合分 | {s.composite_score:.0f} / 100 |",
        f"| 当前价格 | {price} |",
        f"| 区间涨幅 | {gain} |",
        f"| 主力净流入/市值 | {inflow} |",
        f"| 日均换手率 | {turn} |",
        f"| 买入意愿 | {stars} |",
        "",
    ]

    # 推荐理由
    if s.reason:
        lines.append(f"> 💡 **推荐理由**：{s.reason}")
        lines.append("")

    # 多空辩论
    if s.debate_bull or s.debate_bear:
        lines += [
            "**多空辩论**",
            "",
            f"- 🟢 **多方**：{s.debate_bull or '—'}",
            f"- 🔴 **空方**：{s.debate_bear or '—'}",
            "",
        ]

    # 买入结论
    if s.buy_verdict:
        lines.append(f"**📊 综合结论**：{s.buy_verdict}")
        lines.append("")

    lines.append("---")
    lines.append("")
    return lines


# ── 常规政策推荐报告（保留兼容旧接口）────────────────────────────

def render_report(
    ranked: List[ScoredCandidate],
    themes: List[str],
    date: str,
    deep_results: Dict[str, Optional[str]],
) -> str:
    """渲染常规政策推荐报告（手动选板块的旧流程）。"""
    stocks = [s for s in ranked if not s.is_fund]
    funds  = [s for s in ranked if s.is_fund]

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

    lines.append("## 推荐股票")
    lines.append("| 代码 | 名称 | 主题 | 综合分 | 价格 | 近期主力净流入/市值 | 区间涨幅 | 换手率 | 买入意愿 | 推荐理由 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    if stocks:
        lines.extend(_table_row(s) for s in stocks)
    else:
        lines.append("| - | - | - | - | - | - | - | - | - | 无 |")
    lines.append("")

    lines.append("## 推荐基金/ETF")
    lines.append("| 代码 | 名称 | 主题 | 综合分 | 价格 | 份额变化 | 区间涨幅 | 买入意愿 | 推荐理由 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    if funds:
        lines.extend(_fund_table_row(s) for s in funds)
    else:
        lines.append("| - | - | - | - | - | - | - | - | 无 |")
    lines.append("")

    deep_items = [(s, deep_results.get(s.ticker)) for s in ranked if s.ticker in deep_results]
    if deep_items:
        lines.append("## 深度配置建议")
        lines.append("")
        for s, text in deep_items:
            lines.append(f"### {s.ticker} —— {s.name}（综合分 {s.composite_score:.0f}）")
            lines.append(text if text else "> ⚠️ 深度分析失败，跳过配置建议。")
            lines.append("")

    return "\n".join(lines)


def _table_row(s: ScoredCandidate) -> str:
    m = s.metrics
    return (
        f"| {s.ticker} | {s.name} | {s.theme} | {s.composite_score:.0f} | "
        f"{_fmt_price(s.current_price)} | "
        f"{_fmt_pct(m.get('main_net_inflow_ratio'))} | "
        f"{_fmt_pct(m.get('price_gain_ratio'))} | "
        f"{_fmt_pct(m.get('turnover_rate'))} | "
        f"{_stars(s.buy_willing_stars)} | {s.reason} |"
    )


def _fund_table_row(s: ScoredCandidate) -> str:
    m = s.metrics
    return (
        f"| {s.ticker} | {s.name} | {s.theme} | {s.composite_score:.0f} | "
        f"{_fmt_price(s.current_price)} | "
        f"{_fmt_pct(m.get('share_change_ratio'))} | "
        f"{_fmt_pct(m.get('price_gain_ratio'))} | "
        f"{_stars(s.buy_willing_stars)} | {s.reason} |"
    )
