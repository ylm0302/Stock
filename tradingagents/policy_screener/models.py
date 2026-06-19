"""policy_screener 共享数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Candidate:
    """筛选器候选标的。"""

    ticker: str            # 代码，如 "600519.SS"（股票）或 "159995"（基金/ETF）
    name: str             # 标的名称
    theme: str            # 所属政策主题（如"新质生产力"）
    is_fund: bool         # True=基金/ETF，False=股票
    sector: str           # 行业/板块


@dataclass
class FundFlowMetrics:
    """单只标的的资金面原始指标。

    所有数值字段默认 None：表示该指标缺失（akshare 拉取失败或字段不存在）。
    打分纯函数会对缺失指标跳过，而非置零。
    """

    ticker: str
    main_net_inflow_ratio: Optional[float] = None   # 近N日主力净流入合计 / 流通市值
    north_inflow: Optional[float] = None             # 近N日北向净流入（百万元）
    price_gain_ratio: Optional[float] = None         # 区间涨跌幅
    turnover_rate: Optional[float] = None            # 日均换手率
    is_fund: bool = False
    share_change_ratio: Optional[float] = None      # 基金份额变化率（best-effort，常为 None）
    data_source: str = "akshare"                     # "akshare" | "baostock" | "none"
    fetch_error: Optional[str] = None               # 非空表示该标的拉取失败
    current_price: Optional[float] = None           # 最新收盘价（元）


@dataclass
class ScoredCandidate(Candidate):
    """打分后的候选标的。"""

    relevance_score: float = 0.0          # 政策相关度 0-100
    fund_flow_score: float = 0.0          # 量化资金面分 0-100
    llm_qualitative_score: float = 0.0   # LLM 定性分 0-100
    composite_score: float = 0.0          # 综合分
    metrics: dict = field(default_factory=dict)  # 原始指标，供报告展示
    reason: str = ""                      # 一句话推荐理由

    # ── 新增字段 ──────────────────────────────────────────────────
    current_price: Optional[float] = None  # 当前价格（元），None=未获取
    debate_bull: str = ""                  # 多方观点（LLM 多空辩论）
    debate_bear: str = ""                  # 空方观点
    buy_verdict: str = ""                  # 综合结论（是否建议买入 + 理由）
    buy_willing_stars: int = 0             # 买入意愿星级 1-5（0=未评级）
