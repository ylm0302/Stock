"""编排器：串起展开 → 打分 → 排序 → (深度分析) → 报告。

外部依赖（akshare/LLM/propagate）通过模块级函数引用，
测试可用 monkeypatch 替换。本模块不直接 import akshare。
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from .expander import expand_themes, fetch_board_cons
# 从子模块引用 fetch_metrics / qualify，便于测试 monkeypatch 替换
from .fund_flow_scorer import fetch_metrics, score_metrics
from .llm_qualifier import debate_and_verdict, qualify
from .models import Candidate, ScoredCandidate
from .news_hotspot import extract_hotspots_with_llm, fetch_cn_hotspot_news, match_boards
from .ranker import rank_candidates
from .reporter import render_hotspot_report, render_report
from .themes import load_themes

logger = logging.getLogger(__name__)


def build_llm(config: dict):
    """按 config 构造 LLM；失败时抛出 RuntimeError 说明原因。"""
    from tradingagents.llm_clients.factory import create_llm_client
    provider = config.get("llm_provider", "")
    model    = config.get("quick_think_llm", "")

    if not provider:
        raise RuntimeError("llm_provider 未设置，请在左侧选择 LLM 提供商")
    if not model:
        raise RuntimeError(f"快速思考模型名称为空（provider={provider}），请检查配置")

    # 检查 API Key 环境变量是否已设置
    from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
    import os
    env_var = PROVIDER_API_KEY_ENV.get(provider.lower())
    if env_var:
        key_in_env = os.environ.get(env_var, "")
        key_in_cfg = config.get("_api_key", "")
        if not key_in_env and not key_in_cfg:
            raise RuntimeError(
                f"API Key 未设置：{env_var} 为空。"
                f"请在左侧面板填写 {provider} 的 API Key 后重试。"
            )

    try:
        client = create_llm_client(provider, model, config.get("backend_url"))
        return client.get_llm()
    except Exception as e:
        raise RuntimeError(f"LLM 客户端创建失败（{provider}/{model}）：{e}") from e


class PolicyScreenerRunner:
    """政策筛选器编排器。"""

    def __init__(self, config: dict, llm=None, graph=None):
        """
        Args:
            config: DEFAULT_CONFIG 或其副本。
            llm: 已配置的 langchain LLM 对象；None 则 LLM 档降级。
            graph: 已初始化的 TradingAgentsGraph；None 则不跑深度分析。
        """
        self.config = config
        self.llm = llm
        self.graph = graph

    def run(
        self,
        themes: List[str],
        date: str,
        deep_analyze: bool = False,
    ) -> str:
        """运行完整筛选流程，返回 Markdown 报告。"""
        cfg = self.config
        theme_cfg = load_themes(cfg["policy_themes_file"], enabled=themes)
        active_theme_names = theme_cfg.enabled_theme_names()

        # 1. 展开候选池
        candidates = expand_themes(theme_cfg, cons_fetcher=fetch_board_cons)
        logger.info("展开得到 %d 个候选标的", len(candidates))

        # 2. 打分
        scored: List[ScoredCandidate] = []
        for cand in candidates:
            ff_score, metrics = self._score_fund_flow(cand, date)
            llm_score, reason = qualify(cand, self.llm)
            rel_score = self._relevance_score(cand)
            scored.append(ScoredCandidate(
                ticker=cand.ticker, name=cand.name, theme=cand.theme,
                is_fund=cand.is_fund, sector=cand.sector,
                relevance_score=rel_score,
                fund_flow_score=ff_score,
                llm_qualitative_score=llm_score,
                composite_score=0.0,
                metrics=metrics,
                reason=reason,
            ))

        # 3. 排序
        ranked = rank_candidates(
            scored, cfg["policy_thresholds"], cfg["policy_weights"], cfg["policy_top_n"],
        )

        # 4. 深度分析（可选）
        deep_results: Dict[str, Optional[str]] = {}
        if deep_analyze and self.graph is not None and ranked:
            top_k = cfg["policy_deep_analyze_top"]
            for s in ranked[:top_k]:
                deep_results[s.ticker] = self._deep_analyze(s, date)

        # 5. 报告
        return render_report(ranked, active_theme_names, date, deep_results)

    def _score_fund_flow(self, cand: Candidate, date: str):
        """拉取资金面指标并打分。akshare 失败时降级（返回中性分 + 标记）。"""
        try:
            metrics = fetch_metrics(
                cand.ticker, date, self.config["policy_lookback_days"], cand.is_fund,
            )
        except Exception as e:
            logger.warning("拉取 %s 资金面失败: %s", cand.ticker, e)
            from .models import FundFlowMetrics
            metrics = FundFlowMetrics(ticker=cand.ticker, is_fund=cand.is_fund, fetch_error=str(e))
        return score_metrics(metrics), metrics.__dict__

    def _relevance_score(self, cand: Candidate) -> float:
        """政策相关度：命中主题得基础分；简单返回 80（多主题命中未来可扩展）。"""
        return 80.0

    def _deep_analyze(self, scored: ScoredCandidate, date: str) -> Optional[str]:
        """对单只 Top 标的跑 propagate；失败返回 None（报告标记失败）。"""
        try:
            asset_type = "fund" if scored.is_fund else "stock"
            _, decision = self.graph.propagate(
                company_name=scored.ticker, trade_date=date, asset_type=asset_type,
            )
            return decision
        except Exception as e:
            logger.warning("深度分析 %s 失败: %s", scored.ticker, e)
            return None

    # ── 自动热点推荐（核心新增方法） ────────────────────────────────

    def run_auto(
        self,
        date: str,
        deep_analyze: bool = False,
        progress_cb: Optional[Callable[[str, str], None]] = None,
    ) -> tuple[str, list]:
        """根据实时财经新闻自动识别热点，无需用户选板块。

        Args:
            date: 分析日期（yyyy-mm-dd）。
            deep_analyze: 是否对 Top 标的跑深度 Agent 分析。
            progress_cb: 进度回调 (stage: str, message: str)，用于 SSE 推流。
                         stage 取值：'news'|'hotspot'|'expand'|'score'|'rank'|'report'

        Returns:
            (markdown_report, hotspots_with_boards)
        """
        def emit(stage: str, msg: str):
            logger.info("[%s] %s", stage, msg)
            if progress_cb:
                try:
                    progress_cb(stage, msg)
                except Exception:
                    pass

        cfg = self.config

        # ── Step 1: 拉取财经热点新闻 ──────────────────────────────
        emit("news", "正在抓取实时财经热点新闻…")
        news_text, news_source = fetch_cn_hotspot_news(limit=30)
        if news_text:
            # 统计实际新闻条数（以"- "开头的行）
            news_count = sum(1 for line in news_text.splitlines() if line.startswith("- "))
            emit("news", f"新闻获取成功：{news_source}，有效条目 {news_count} 条")

            # 输出新闻详情（前10条，避免日志过长）
            news_lines = [line for line in news_text.splitlines() if line.startswith("- ")]
            for i, line in enumerate(news_lines[:10], 1):
                emit("news", f"  [{i}] {line[2:]}")  # 去掉前面的 "- "
            if news_count > 10:
                emit("news", f"  ... 还有 {news_count - 10} 条新闻")
        else:
            emit("news", f"⚠️ {news_source}")

        # ── Step 2: LLM 分析热点 → 提取主题 ─────────────────────
        emit("hotspot", "LLM 正在分析热点主题，结合国家政策筛选板块…")

        # 输出 LLM 配置信息
        llm_provider = cfg.get("llm_provider", "unknown")
        llm_model = cfg.get("quick_think_llm", "unknown")
        emit("hotspot", f"📋 LLM 配置: {llm_provider}/{llm_model}")

        # 检查 API Key 状态
        from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
        import os
        env_var = PROVIDER_API_KEY_ENV.get(llm_provider.lower())
        if env_var:
            api_key = os.environ.get(env_var, "")
            if api_key:
                # 不显示具体密钥内容，避免编码问题
                emit("hotspot", f"🔑 API Key: {env_var} 已设置")
            else:
                emit("hotspot", f"❌ API Key: {env_var} 未设置！")

        all_theme_cfg = load_themes(cfg["policy_themes_file"], enabled=[])
        all_board_names = all_theme_cfg.enabled_board_names()
        emit("hotspot", f"板块库共 {len(all_board_names)} 个板块可供匹配")
        emit("hotspot", f"📊 板块列表（前10个）: {', '.join(all_board_names[:10])}")

        hotspots, hotspot_msg = extract_hotspots_with_llm(news_text, self.llm, all_board_names)
        emit("hotspot", hotspot_msg)

        matched_boards, hotspots_with_boards = match_boards(hotspots, all_board_names)

        if matched_boards:
            board_str = "、".join(matched_boards)
            emit("hotspot", f"最终匹配到 {len(matched_boards)} 个板块：{board_str}")
        else:
            # 无法匹配任何板块，直接终止，不用保底
            emit("hotspot", "❌ 未匹配到任何板块，无法继续。请检查 LLM 配置或网络连接。")
            report = render_hotspot_report([], [], news_text[:500], date, {})
            return report, []

        # ── Step 3: 展开候选池 ────────────────────────────────────
        emit("expand", f"正在从 akshare 拉取 {len(matched_boards)} 个板块的成分股…")
        theme_cfg = load_themes(cfg["policy_themes_file"], enabled=matched_boards)
        candidates = expand_themes(theme_cfg, cons_fetcher=fetch_board_cons)

        stocks_cnt = sum(1 for c in candidates if not c.is_fund)
        funds_cnt  = sum(1 for c in candidates if c.is_fund)
        emit("expand", f"展开完成：股票 {stocks_cnt} 只 / 基金/ETF {funds_cnt} 只，共 {len(candidates)} 只")

        if not candidates:
            emit("expand", "❌ 候选池为空 — akshare 板块成分接口不可用且 YAML 无预置股票。请检查网络代理设置。")
            report = render_hotspot_report([], hotspots_with_boards, news_text[:500], date, {})
            return report, hotspots_with_boards

        # ── Step 4: 逐标的打分 ───────────────────────────────────
        emit("score", f"开始对 {len(candidates)} 只标的进行资金面 + LLM 评分…")
        scored: List[ScoredCandidate] = []
        for i, cand in enumerate(candidates):
            ff_score, metrics = self._score_fund_flow(cand, date)
            llm_score, reason = qualify(cand, self.llm)
            rel_score = self._relevance_score_hotspot(cand, hotspots_with_boards)
            scored.append(ScoredCandidate(
                ticker=cand.ticker, name=cand.name, theme=cand.theme,
                is_fund=cand.is_fund, sector=cand.sector,
                relevance_score=rel_score,
                fund_flow_score=ff_score,
                llm_qualitative_score=llm_score,
                composite_score=0.0,
                metrics=metrics,
                reason=reason,
                current_price=metrics.get("current_price"),
            ))
            # 每处理 10 只推一次进度
            if (i + 1) % 10 == 0 or (i + 1) == len(candidates):
                emit("score", f"已评分 {i + 1}/{len(candidates)} 只")

        # ── Step 5: 排序 ─────────────────────────────────────────
        emit("rank", "正在按主力介入度 + 政策相关性综合排名…")
        max_price = cfg.get("policy_max_price")
        ranked = rank_candidates(
            scored, cfg["policy_thresholds"], cfg["policy_weights"], cfg["policy_top_n"],
            max_price=max_price,
        )
        price_note = f"（价格 ≤ {max_price} 元）" if max_price else ""
        emit("rank", f"通过筛选{price_note}：{len(ranked)} 只（股票 {sum(1 for s in ranked if not s.is_fund)} 只 / 基金 {sum(1 for s in ranked if s.is_fund)} 只）")

        # ── Step 6: 多空辩论 + 买入星级 ──────────────────────────
        if ranked:
            emit("debate", f"LLM 对 {len(ranked)} 只标的进行多空辩论，评定买入意愿星级…")
            for i, s in enumerate(ranked):
                price = s.metrics.get("current_price")
                bull, bear, verdict, stars = debate_and_verdict(s, self.llm, price=price)
                s.debate_bull = bull
                s.debate_bear = bear
                s.buy_verdict = verdict
                s.buy_willing_stars = stars
                s.current_price = price
                if (i + 1) % 3 == 0 or (i + 1) == len(ranked):
                    emit("debate", f"辩论完成 {i + 1}/{len(ranked)} 只")

        # ── Step 7: 深度分析（可选） ──────────────────────────────
        deep_results: Dict[str, Optional[str]] = {}
        if deep_analyze and self.graph is not None and ranked:
            top_k = cfg["policy_deep_analyze_top"]
            emit("deep", f"对 Top {min(top_k, len(ranked))} 只标的进行深度 Agent 分析…")
            for s in ranked[:top_k]:
                emit("deep", f"深度分析 {s.ticker}（{s.name}）…")
                deep_results[s.ticker] = self._deep_analyze(s, date)

        # ── Step 8: 生成报告 ──────────────────────────────────────
        emit("report", "正在生成推荐报告…")
        report = render_hotspot_report(ranked, hotspots_with_boards, news_text[:500], date, deep_results)
        emit("report", "报告生成完毕 ✅")

        return report, hotspots_with_boards

    def _relevance_score_hotspot(self, cand: Candidate, hotspots_with_boards: list) -> float:
        """根据热点匹配程度计算政策相关度分（0-100）。

        标的所属 theme 命中多个热点得分更高。
        """
        match_count = 0
        for h in hotspots_with_boards:
            if cand.theme in h.get("matched_boards", []):
                match_count += 1
        if match_count == 0:
            return 60.0   # 基础分
        return min(100.0, 70.0 + match_count * 10.0)