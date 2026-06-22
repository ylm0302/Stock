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
    # 注：stock_zh_a_alerts_cls 在某些 akshare 版本中已移除，跳过此数据源
    # try:
    #     import akshare as ak
    #     df = ak.stock_zh_a_alerts_cls()
    #     if df is not None and not df.empty:
    #         col = next((c for c in ["标题", "title", "内容", "content"] if c in df.columns), None)
    #         if col:
    #             items = df[col].astype(str).head(limit).tolist()
    #             text = "【东财7×24快讯】\n" + "\n".join(f"- {t}" for t in items)
    #             logger.info("东财快讯获取成功，共 %d 条", len(items))
    #             return text, f"东财7×24快讯（{len(items)}条）"
    # except Exception as e:
    #     logger.warning("东财快讯失败: %s", str(e))

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

_HOTSPOT_SYSTEM = """你是 A 股资深投资顾问，擅长从财经新闻中识别短期可操作的投资机会。

任务：阅读以下近期财经新闻，结合国家政策导向和市场资金流向，识别出 3~6 个当前最具短期操作价值的 A 股投资主题。

重点关注：
1. **政策催化**：有国家政策刚刚发布或即将落地的板块
2. **资金关注**：新闻显示主力资金正在流入或市场关注度快速提升
3. **短期弹性**：适合 1-3 个月操作的标的，优先考虑有催化剂的板块
4. **基金+股票**：同时关注相关 ETF/基金和个股机会

输出要求：
1. 只输出 JSON 数组，格式：[{"theme":"板块名","reason":"不超过25字的短期机会","keywords":["关键词1","关键词2"],"urgency":"高/中/低"}]
2. 板块名优先使用 A 股常见概念板块名（如"半导体"、"新能源车"、"AI算力"、"创新药"等）
3. reason 字段说明短期操作逻辑（政策催化剂 + 资金动向 + 时间窗口）
4. urgency 字段表示操作紧迫度：高=立即关注，中=近期布局，低=中长期观察
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
        "请从新闻中识别 3~6 个最具短期操作价值的 A 股板块，重点关注：\n"
        "1. 政策催化（新政策发布或落地）\n"
        "2. 资金关注（主力资金流入）\n"
        "3. 短期弹性（1-3个月操作窗口）\n"
        "4. 基金+股票双重机会\n\n"
        "输出 JSON 数组，包含 urgency 字段表示操作紧迫度。"
        "如新闻内容不足以支撑判断，请返回空数组 []。"
    )

    try:
        # 禁用 langchain 的缓存和详细日志，避免内部调试输出触发 ASCII 编码错误
        import logging
        import os
        import locale

        # 强制设置 UTF-8 locale，避免 HTTP 客户端库使用 ASCII 编码
        # 这是最后一道防线：即使 sys.stdout/stderr 已经配置为 UTF-8，
        # 某些底层库（如 httpx）仍可能从 locale 读取编码
        old_locale = None
        try:
            old_locale = locale.getlocale()
            # 尝试设置为 UTF-8 locale（macOS/Linux 通常支持）
            for loc in ['en_US.UTF-8', 'C.UTF-8', 'zh_CN.UTF-8']:
                try:
                    locale.setlocale(locale.LC_ALL, loc)
                    logger.debug(f"成功设置 locale 为 {loc}")
                    break
                except locale.Error:
                    continue
        except Exception as e:
            logger.debug(f"设置 locale 失败（非致命）: {e}")

        # 临时禁用 langchain 缓存
        old_cache = os.environ.get("LANGCHAIN_CACHE")
        os.environ["LANGCHAIN_CACHE"] = ""

        # 禁用 langchain 详细日志
        langchain_logger = logging.getLogger("langchain")
        langchain_core_logger = logging.getLogger("langchain_core")
        old_langchain_level = langchain_logger.level
        old_core_level = langchain_core_logger.level
        langchain_logger.setLevel(logging.CRITICAL)
        langchain_core_logger.setLevel(logging.CRITICAL)

        try:
            # 在调用前强制确保所有字符串都是 UTF-8 可编码的
            logger.debug("准备调用 LLM，检查 prompt 编码...")
            try:
                _HOTSPOT_SYSTEM.encode('utf-8')
                user_prompt.encode('utf-8')
                logger.debug("Prompt 编码检查通过")
            except UnicodeEncodeError as enc_err:
                logger.error(f"Prompt 编码检查失败: {enc_err}")
                raise

            # 传递 config 禁用缓存
            logger.debug("开始调用 llm.invoke()...")
            resp = llm.invoke(
                [
                    ("system", _HOTSPOT_SYSTEM),
                    ("human", user_prompt),
                ],
                config={"metadata": {"__cache_enabled": False}}
            )
            logger.debug("LLM 调用完成")
        finally:
            # 恢复设置
            if old_cache is not None:
                os.environ["LANGCHAIN_CACHE"] = old_cache
            langchain_logger.setLevel(old_langchain_level)
            langchain_core_logger.setLevel(old_core_level)
            # 恢复原始 locale
            if old_locale is not None:
                try:
                    locale.setlocale(locale.LC_ALL, old_locale)
                except Exception:
                    pass

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
        import traceback
        msg = f"LLM 调用失败：{e}"

        # 无论什么错误，都先输出完整 traceback
        logger.error("=" * 60)
        logger.error("LLM 调用异常，完整 traceback:")
        logger.error(traceback.format_exc())
        logger.error("=" * 60)

        # 特殊处理 UnicodeEncodeError，打印详细诊断
        if isinstance(e, UnicodeEncodeError):
            logger.error("捕获到 UnicodeEncodeError - 编码错误详情:")
            logger.error(f"  错误类型: {type(e).__name__}")
            logger.error(f"  编码方式: {e.encoding}")
            logger.error(f"  错误位置: position {e.start}-{e.end}")
            logger.error(f"  问题字符: {repr(e.object[max(0, e.start-10):e.end+10])}")

            # 尝试定位是哪个变量导致的编码问题
            try:
                logger.error("诊断信息:")
                logger.error(f"  news_text 长度: {len(news_text)}")
                logger.error(f"  board_hint 长度: {len(board_hint)}")
                logger.error(f"  user_prompt 长度: {len(user_prompt)}")
                logger.error(f"  系统 prompt 长度: {len(_HOTSPOT_SYSTEM)}")

                # 测试编码
                test_items = [
                    ("news_text", news_text[:100]),
                    ("board_hint", board_hint[:100]),
                    ("user_prompt", user_prompt[:100]),
                    ("_HOTSPOT_SYSTEM", _HOTSPOT_SYSTEM[:100]),
                ]
                for name, content in test_items:
                    try:
                        content.encode('utf-8')
                        logger.error(f"  {name}: UTF-8 编码正常")
                    except Exception as enc_err:
                        logger.error(f"  {name}: UTF-8 编码失败 - {enc_err}")
            except Exception as diag_err:
                logger.error(f"诊断失败: {diag_err}")

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
