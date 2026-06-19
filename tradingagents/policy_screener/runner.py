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
from .llm_qualifier import qualify
from .models import Candidate, ScoredCandidate
from .news_hotspot import extract_hotspots_with_llm, fetch_cn_hotspot_news, match_boards
from .ranker import rank_candidates
from .reporter import render_hotspot_report, render_report
from .themes import load_themes

logger = logging.getLogger(__name__)


def build_llm(config: dict):
    """按 config 构造 LLM；失败返回 None。"""
    try:
        from tradingagents.llm_clients.factory import create_llm_client
        provider = config["llm_provider"]
        model = config["quick_think_llm"]
        client = create_llm_client(provider, model, config.get("backend_url"))
        return client.get_llm()
    except Exception:
        return None


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
        news_text = fetch_cn_hotspot_news(limit=40)
        if news_text:
            emit("news", f"已获取 {len(news_text.splitlines())} 条新闻")
        else:
            emit("news", "新闻抓取失败，将使用内置默认热点板块")

        # ── Step 2: LLM 分析热点 → 提取主题 ─────────────────────
        emit("hotspot", "LLM 正在分析热点主题，结合国家政策筛选板块…")
        all_theme_cfg = load_themes(cfg["policy_themes_file"], enabled=[])
        all_board_names = all_theme_cfg.enabled_board_names()

        hotspots = extract_hotspots_with_llm(news_text, self.llm, all_board_names)
        matched_boards, hotspots_with_boards = match_boards(hotspots, all_board_names)

        if matched_boards:
            board_str = "、".join(matched_boards[:8])
            emit("hotspot", f"识别到 {len(hotspots_with_boards)} 个热点，匹配板块：{board_str}{'…' if len(matched_boards) > 8 else ''}")
        else:
            # 完全匹配失败时用全部板块（保底）
            emit("hotspot", "未能匹配已知板块，将扫描全部板块（可能较慢）")
            matched_boards = all_board_names[:20]  # 最多取前 20 个避免太慢

        # ── Step 3: 展开候选池 ────────────────────────────────────
        emit("expand", f"正在展开 {len(matched_boards)} 个热点板块的成分标的…")
        theme_cfg = load_themes(cfg["policy_themes_file"], enabled=matched_boards)
        candidates = expand_themes(theme_cfg, cons_fetcher=fetch_board_cons)
        emit("expand", f"候选标的池共 {len(candidates)} 只")

        if not candidates:
            emit("expand", "候选池为空，请检查板块配置或 akshare 连接")
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
            ))
            # 每处理 10 只推一次进度
            if (i + 1) % 10 == 0 or (i + 1) == len(candidates):
                emit("score", f"已评分 {i + 1}/{len(candidates)} 只")

        # ── Step 5: 排序 ─────────────────────────────────────────
        emit("rank", "正在按主力介入度 + 政策相关性综合排名…")
        ranked = rank_candidates(
            scored, cfg["policy_thresholds"], cfg["policy_weights"], cfg["policy_top_n"],
        )
        emit("rank", f"通过筛选：{len(ranked)} 只（股票 {sum(1 for s in ranked if not s.is_fund)} 只 / 基金 {sum(1 for s in ranked if s.is_fund)} 只）")

        # ── Step 6: 深度分析（可选） ──────────────────────────────
        deep_results: Dict[str, Optional[str]] = {}
        if deep_analyze and self.graph is not None and ranked:
            top_k = cfg["policy_deep_analyze_top"]
            emit("deep", f"对 Top {min(top_k, len(ranked))} 只标的进行深度 Agent 分析…")
            for s in ranked[:top_k]:
                emit("deep", f"深度分析 {s.ticker}（{s.name}）…")
                deep_results[s.ticker] = self._deep_analyze(s, date)

        # ── Step 7: 生成报告 ──────────────────────────────────────
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