"""财经新闻热点分析器。

从实时财经新闻中提取热点主题，自动匹配 sector_boards.yaml 中的板块，
供 PolicyScreenerRunner 无需用户手选即可完成自动推荐。
"""

from __future__ import annotations

import json
import logging
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 财经新闻抓取 ─────────────────────────────────────────────────────

def fetch_cn_hotspot_news(limit: int = 30) -> str:
    """抓取国内财经热点新闻。

    依次尝试：东财快讯 → 财新宏观 → 空字符串降级。
    返回拼接好的新闻文本，供 LLM 分析。
    """
    texts: List[str] = []

    # 1) 东财 7×24 快讯
    try:
        import akshare as ak
        df = ak.stock_zh_a_alerts_cls()
        if df is not None and not df.empty:
            col = next((c for c in ["标题", "title", "内容", "content"] if c in df.columns), None)
            if col:
                items = df[col].astype(str).head(limit).tolist()
                texts.append("【东财快讯】\n" + "\n".join(f"- {t}" for t in items))
    except Exception as e:
        logger.debug("东财快讯失败: %s", e)

    # 2) 财新宏观新闻
    if len(texts) == 0:
        try:
            import akshare as ak
            df = ak.stock_news_main_cx()
            if df is not None and not df.empty:
                col = next((c for c in ["summary", "标题", "title"] if c in df.columns), None)
                if col:
                    items = df[col].astype(str).head(limit).tolist()
                    texts.append("【财新宏观】\n" + "\n".join(f"- {t}" for t in items))
        except Exception as e:
            logger.debug("财新新闻失败: %s", e)

    # 3) 同花顺宏观新闻
    if len(texts) == 0:
        try:
            import akshare as ak
            df = ak.stock_news_em(symbol="000001")
            if df is not None and not df.empty:
                col = next((c for c in ["新闻标题", "title"] if c in df.columns), None)
                if col:
                    items = df[col].astype(str).head(limit).tolist()
                    texts.append("【市场新闻】\n" + "\n".join(f"- {t}" for t in items))
        except Exception as e:
            logger.debug("同花顺新闻失败: %s", e)

    return "\n\n".join(texts) if texts else ""


# ── LLM 热点分析 ─────────────────────────────────────────────────────

_HOTSPOT_SYSTEM = """你是 A 股资深行业分析师，擅长从财经新闻中识别当前市场热点板块。

任务：阅读以下近期财经新闻，结合国家政策导向，识别出 3~6 个当前最受市场关注、且有政策支撑的 A 股投资主题板块。

输出要求：
1. 只输出 JSON 数组，格式：[{"theme":"板块名","reason":"不超过20字的原因","keywords":["关键词1","关键词2"]}]
2. 板块名优先使用 A 股常见概念板块名（如"半导体"、"新能源车"、"AI算力"、"创新药"等）
3. 必须有国家政策支撑，纯市场炒作的题材不纳入
4. reason 字段说明为何当前值得关注（政策 + 热点双重支撑）"""

_HOTSPOT_FALLBACK = [
    {"theme": "半导体", "reason": "国产替代持续推进，政策密集扶持", "keywords": ["芯片", "半导体", "集成电路"]},
    {"theme": "新能源车", "reason": "国补持续，渗透率仍在爬升", "keywords": ["新能源", "电动车", "锂电"]},
    {"theme": "AI算力", "reason": "大模型建设高峰，算力需求旺盛", "keywords": ["算力", "AI", "大模型"]},
    {"theme": "创新药", "reason": "医药政策优化，出海逻辑强劲", "keywords": ["创新药", "生物医药", "License-out"]},
]


def extract_hotspots_with_llm(news_text: str, llm, all_board_names: List[str]) -> List[dict]:
    """用 LLM 分析新闻，提取热点主题并映射到已知板块。

    Args:
        news_text: 拼接好的财经新闻文本。
        llm: langchain LLM 对象；None 时返回默认热点。
        all_board_names: sector_boards.yaml 中所有板块名，供 LLM 参考匹配。

    Returns:
        [{"theme": 板块名, "reason": 原因, "keywords": [...]}]
    """
    if llm is None:
        logger.info("LLM 不可用，使用内置默认热点板块")
        return _HOTSPOT_FALLBACK

    if not news_text.strip():
        logger.info("新闻为空，使用内置默认热点板块")
        return _HOTSPOT_FALLBACK

    board_hint = "、".join(all_board_names[:60])  # 最多列60个，避免超出 token
    user_prompt = (
        f"以下是 sector_boards.yaml 中已定义的板块名（优先从中匹配）：\n{board_hint}\n\n"
        f"近期财经新闻如下：\n{news_text[:3000]}\n\n"
        "请从新闻中识别 3~6 个当前最热点且有国家政策支撑的 A 股板块，输出 JSON 数组。"
    )

    try:
        resp = llm.invoke([
            ("system", _HOTSPOT_SYSTEM),
            ("human", user_prompt),
        ])
        content = getattr(resp, "content", str(resp))
        # 截取 JSON 数组
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end > start:
            hotspots = json.loads(content[start:end + 1])
            if isinstance(hotspots, list) and hotspots:
                logger.info("LLM 识别热点板块: %s", [h.get("theme") for h in hotspots])
                return hotspots
    except Exception as e:
        logger.warning("LLM 热点分析失败: %s，使用默认热点", e)

    return _HOTSPOT_FALLBACK


# ── 板块名模糊匹配 ────────────────────────────────────────────────────

def match_boards(hotspots: List[dict], all_board_names: List[str]) -> Tuple[List[str], List[dict]]:
    """将 LLM 提取的热点 theme 名映射到 sector_boards.yaml 的真实板块名。

    匹配策略（优先级递减）：
    1. 精确匹配
    2. 任意包含关系（theme in board_name 或 board_name in theme）
    3. 关键词列表中的词命中某板块名

    Returns:
        matched_board_names: 匹配到的板块名列表（已去重）
        hotspot_with_board: 每个热点附带 matched_board 字段
    """
    matched: List[str] = []
    result: List[dict] = []

    for hotspot in hotspots:
        theme = hotspot.get("theme", "")
        keywords = hotspot.get("keywords", [])
        found: List[str] = []

        for bn in all_board_names:
            # 精确
            if bn == theme:
                found.append(bn)
                continue
            # 包含
            if theme in bn or bn in theme:
                found.append(bn)
                continue
            # 关键词命中
            for kw in keywords:
                if kw and (kw in bn or bn in kw):
                    found.append(bn)
                    break

        # 去重后取前 3 个匹配板块
        seen = set()
        deduped = []
        for b in found:
            if b not in seen:
                seen.add(b)
                deduped.append(b)
        found = deduped[:3]

        if not found:
            # 未能匹配到板块，跳过
            logger.debug("热点 '%s' 未找到匹配板块", theme)
            continue

        for b in found:
            if b not in matched:
                matched.append(b)

        result.append({**hotspot, "matched_boards": found})

    return matched, result
