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