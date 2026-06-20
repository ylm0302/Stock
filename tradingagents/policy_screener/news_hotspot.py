"""财经新闻热点分析器。

从实时财经新闻中提取热点主题，自动匹配 sector_boards.yaml 中的板块，
供 PolicyScreenerRunner 无需用户手选即可完成自动推荐。

设计原则：不内置任何默认热点；若 API 不可用直接返回空，
由调用方在日志中说明原因，让用户知道真实状态。
"""

from __future__ import annotations

import json
import logging
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── 财经新闻抓取 ─────────────────────────────────────────────────────

def fetch_cn_hotspot_news(limit: int = 30) -> Tuple[str, str]:
    """抓取国内财经热点新闻。

    依次尝试多个数据源，返回第一个成功的结果。

    Returns:
        (news_text, source_name)
        - news_text: 拼接好的新闻正文，供 LLM 分析
        - source_name: 实际使用的数据源名称，用于日志
    """

    # ── 1) 东财 7×24 快讯 ─────────────────────────────────────────
    try:
        import akshare as ak
        df = ak.stock_zh_a_alerts_cls()
        if df is not None and not df.empty:
            col = next((c for c in ["标题", "title", "内容", "content"] if c in df.columns), None)
            if col:
                items = df[col].astype(str).head(limit).tolist()
                text = "【东财7×24快讯】\n" + "\n".join(f"- {t}" for t in items)
                logger.info("东财快讯获取成功，共 %d 条", len(items))
                return text, f"东财7×24快讯（{len(items)}条）"
    except Exception as e:
        logger.warning("东财快讯失败: %s", str(e))

    # ── 2) 财新宏观新闻 ───────────────────────────────────────────
    try:
        import akshare as ak
        df = ak.stock_news_main_cx()
        if df is not None and not df.empty:
            col = next((c for c in ["summary", "标题", "title"] if c in df.columns), None)
            if col:
                items = df[col].astype(str).head(limit).tolist()
                text = "【财新宏观新闻】\n" + "\n".join(f"- {t}" for t in items)
                logger.info("财新宏观新闻获取成功，共 %d 条", len(items))
                return text, f"财新宏观（{len(items)}条）"
    except Exception as e:
        logger.warning("财新宏观新闻失败: %s", str(e))

    # ── 3) 东财个股新闻（用上证指数作为宏观代理）────────────────────
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol="000001")
        if df is not None and not df.empty:
            col = next((c for c in ["新闻标题", "title"] if c in df.columns), None)
            if col:
                items = df[col].astype(str).head(limit).tolist()
                text = "【东财市场新闻】\n" + "\n".join(f"- {t}" for t in items)
                logger.info("东财市场新闻获取成功，共 %d 条", len(items))
                return text, f"东财市场新闻（{len(items)}条）"
    except Exception as e:
        logger.warning("东财市场新闻失败: %s", str(e))

    # ── 全部失败 ──────────────────────────────────────────────────
    logger.error("所有新闻源均不可用，无法获取实时财经新闻")
    return "", "无法获取新闻（所有数据源均失败）"


# ── LLM 热点分析 ─────────────────────────────────────────────────────

_HOTSPOT_SYSTEM = """你是 A 股资深行业分析师，擅长从财经新闻中识别当前市场热点板块。

任务：阅读以下近期财经新闻，结合国家政策导向，识别出 3~6 个当前最受市场关注、且有政策支撑的 A 股投资主题板块。

输出要求：
1. 只输出 JSON 数组，格式：[{"theme":"板块名","reason":"不超过20字的原因","keywords":["关键词1","关键词2"]}]
2. 板块名优先使用 A 股常见概念板块名（如"半导体"、"新能源车"、"AI算力"、"创新药"等）
3. 必须有国家政策支撑，纯市场炒作的题材不纳入
4. reason 字段说明为何当前值得关注（政策 + 热点双重支撑）
5. 如果新闻内容不足以判断热点，返回空数组 []"""


def extract_hotspots_with_llm(
    news_text: str,
    llm,
    all_board_names: List[str],
) -> Tuple[List[dict], str]:
    """用 LLM 分析新闻，提取热点主题。

    不使用任何内置默认值 — 若 LLM 不可用或新闻为空，返回空列表。

    Returns:
        (hotspots, reason_msg)
        - hotspots: LLM 识别的热点列表，可能为空
        - reason_msg: 说明成功/失败原因的文字，用于日志
    """
    if llm is None:
        msg = "LLM 未配置，无法分析热点。请在左侧配置 API Key 后重试。"
        logger.warning(msg)
        return [], msg

    if not news_text.strip():
        msg = "新闻内容为空，无法分析热点。请检查网络或数据源是否可用。"
        logger.warning(msg)
        return [], msg

    board_hint = "、".join(all_board_names[:60])
    user_prompt = (
        f"以下是已定义的 A 股板块名（优先从中匹配）：\n{board_hint}\n\n"
        f"近期财经新闻如下：\n{news_text[:3000]}\n\n"
        "请从新闻中识别 3~6 个当前最热点且有国家政策支撑的 A 股板块，输出 JSON 数组。"
        "如新闻内容不足以支撑判断，请返回空数组 []。"
    )

    try:
        resp = llm.invoke([
            ("system", _HOTSPOT_SYSTEM),
            ("human", user_prompt),
        ])
        content = getattr(resp, "content", str(resp))

        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end > start:
            hotspots = json.loads(content[start:end + 1])
            if isinstance(hotspots, list):
                themes = [h.get("theme", "") for h in hotspots if h.get("theme")]
                if themes:
                    msg = f"LLM 成功识别 {len(themes)} 个热点：{'、'.join(themes)}"
                    logger.info(msg)
                    return hotspots, msg
                else:
                    msg = "LLM 返回空数组，当前新闻未发现明确热点板块"
                    logger.info(msg)
                    return [], msg
        msg = "LLM 返回格式无法解析（非 JSON 数组）"
        logger.warning("LLM 返回内容: %s", content[:200])
        return [], msg
    except Exception as e:
        msg = f"LLM 调用失败：{e}"
        logger.error("LLM 调用失败: %s", str(e))
        return [], msg


# ── 板块名模糊匹配 ────────────────────────────────────────────────────

def match_boards(
    hotspots: List[dict],
    all_board_names: List[str],
) -> Tuple[List[str], List[dict]]:
    """将 LLM 提取的热点 theme 名映射到 sector_boards.yaml 的真实板块名。

    匹配策略（优先级递减）：
    1. 精确匹配
    2. 任意包含关系（theme in board_name 或 board_name in theme）
    3. 关键词列表中的词命中某板块名

    Returns:
        (matched_board_names, hotspots_with_boards)
    """
    matched: List[str] = []
    result: List[dict] = []

    for hotspot in hotspots:
        theme    = hotspot.get("theme", "")
        keywords = hotspot.get("keywords", [])
        found: List[str] = []

        for bn in all_board_names:
            if bn == theme:
                found.append(bn)
                continue
            if theme in bn or bn in theme:
                found.append(bn)
                continue
            for kw in keywords:
                if kw and (kw in bn or bn in kw):
                    found.append(bn)
                    break

        # 去重，最多取前 3 个
        seen_set: set = set()
        deduped = []
        for b in found:
            if b not in seen_set:
                seen_set.add(b)
                deduped.append(b)
        found = deduped[:3]

        if not found:
            logger.debug("热点 '%s' 未找到匹配板块", theme)
            continue

        for b in found:
            if b not in matched:
                matched.append(b)

        result.append({**hotspot, "matched_boards": found})

    return matched, result
