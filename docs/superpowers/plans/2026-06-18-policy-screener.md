# 政策扶持标的推荐筛选器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `tradingagents/policy_screener/` 子包，按"国家政策扶持 + 主力资金未介入"双条件筛选 A 股股票与国内基金/ETF，输出 Markdown 推荐池报告，并可选对 Top N 复用现有 `TradingAgentsGraph.propagate()` 出配置建议。

**Architecture:** 方案 A —— 独立筛选器与现有分析流程解耦。筛选器内部拆为 4 个职责单一的单元：主题展开(expander) → 资金面量化打分(fund_flow_scorer) + LLM 定性打分(llm_qualifier) → 综合排序(ranker) → 报告(reporter)，由 runner 编排。所有打分/排序为纯函数、可独立测试；akshare 与 LLM 在测试中全部 mock。资金面采用 akshare 量化 + LLM 定性双轨；逐层降级保证单点失败不致整体崩溃。

**Tech Stack:** Python 3.13、akshare(1.18.x，已依赖)、PyYAML(6.x，akshare 传递依赖)、langchain(项目已依赖，用于 LLM 调用)、pytest(项目已配置)。不引入新第三方依赖。

---

## 设计依据与 akshare 接口确认（实施参考）

以下 akshare 函数名与列名已在 v1.18.63 实测确认，计划中所有代码以此为准：

- **概念板块成分股**：`ak.stock_board_concept_cons_em(symbol="板块名")` → 列 `代码`、`名称`、`换手率`。板块名必须与 `ak.stock_board_concept_name_em()` 返回的名称严格一致，否则抛 IndexError。
- **个股资金流**：`ak.stock_individual_fund_flow(stock="600094", market="sh")` → 列 `日期`、`主力净流入-净额`、`主力净流入-净占比`。返回历史全量逐日，需自行取最近 N 日。
- **个股日线**：`ak.stock_zh_a_hist(symbol="002008", period="daily", start_date="YYYYMMDD", end_date="YYYYMMDD", adjust="")` → 列 `日期`、`收盘`、`换手率`、`涨跌幅`。
- **北向个股持股**：`ak.stock_hsgt_individual_em(symbol="002008")` → 列 `持股日期`、`今日增持资金`、`持股数量占A股百分比`。
- **ETF 日线**：`ak.fund_etf_hist_em(symbol="159707", period="daily", start_date, end_date)` → 列 `日期`、`收盘`、`换手率`、`涨跌幅`、`成交额`。
- **市场代码推断**：`60`/`68` 开头 → `sh`，`00`/`30` 开头 → `sz`。

**重要能力边界**：akshare 无"单只 ETF 近 N 日逐日份额序列"接口。因此基金/ETF 的"主力未介入"改用日线代理信号：区间涨幅未拉升 + 日均换手率未过热 + 成交额未放量。份额变化作为 best-effort（尝试交易所快照，失败则降级，不影响评分）。

---

## File Structure

新建/修改文件清单：

```
tradingagents/policy_screener/        # 新子包
├── __init__.py                       # 导出公开 API
├── models.py                         # 数据类：Candidate / ScoredCandidate / FundFlowMetrics
├── themes.py                         # policy_themes.yaml 加载与校验
├── expander.py                       # 主题 → 候选标的池（调 akshare 板块成分）
├── fund_flow_scorer.py               # akshare 拉取指标 + 纯函数打分
├── llm_qualifier.py                  # LLM 定性打分（降级安全）
├── ranker.py                         # 加权 + 阈值过滤 + 排序
├── reporter.py                       # Markdown 报告生成（纯函数）
├── runner.py                         # 编排 PolicyScreenerRunner.run()
└── data/
    └── policy_themes.yaml            # 预置可编辑主题映射表

policy_main.py                        # 根目录 Python 入口（仿 main.py）
cli/policy.py                         # CLI 子命令入口

tests/policy_screener/                # 测试包
├── __init__.py
├── conftest.py                       # 共享 fixture（构造的 metrics/candidates）
├── test_models.py
├── test_themes.py
├── test_expander.py
├── test_fund_flow_scorer.py
├── test_llm_qualifier.py
├── test_ranker.py
├── test_reporter.py
└── test_runner.py
```

修改的现有文件：
- `tradingagents/default_config.py`（新增 `policy_*` 配置项 + env override）

**职责边界**：每个文件单一职责，互不读取彼此内部实现。`models.py` 定义所有跨模块共享的数据类；`themes.py`/`expander.py`/`scorer`/`qualifier`/`ranker`/`reporter` 各自输入/输出明确数据类型；`runner.py` 是唯一持有编排逻辑、唯一调用 akshare/LLM/propagate 副作用的协调者（其余打分函数保持纯函数）。

**运行测试**：项目已配置 `testpaths=["tests"]`，根目录运行 `pytest tests/policy_screener/ -v`。`tests/conftest.py` 的 autouse fixture 会注入占位 API key，故测试无需真实凭证。

---

## Task 1: 在 default_config 注册筛选器配置

**Files:**
- Modify: `tradingagents/default_config.py`（`_ENV_OVERRIDES` 与 `DEFAULT_CONFIG` 两处）

- [ ] **Step 1: 写失败测试 — 配置项存在且类型正确**

Create `tests/policy_screener/__init__.py`（空文件）。

Create `tests/policy_screener/test_config.py`:

```python
from tradingagents.default_config import DEFAULT_CONFIG


def test_policy_config_keys_present():
    """policy_* 配置项应在 DEFAULT_CONFIG 中存在。"""
    assert DEFAULT_CONFIG["policy_themes_file"].endswith("policy_themes.yaml")
    assert DEFAULT_CONFIG["policy_enabled_themes"] == []
    assert DEFAULT_CONFIG["policy_lookback_days"] == 10
    assert DEFAULT_CONFIG["policy_top_n"] == 10
    assert DEFAULT_CONFIG["policy_deep_analyze_top"] == 3


def test_policy_thresholds_defaults():
    t = DEFAULT_CONFIG["policy_thresholds"]
    assert t["main_net_inflow_ratio"] == 0.01
    assert t["price_gain_ratio"] == 0.15
    assert t["turnover_rate"] == 0.05


def test_policy_weights_sum_to_one():
    w = DEFAULT_CONFIG["policy_weights"]
    total = w["relevance"] + w["fund_flow"] + w["llm_qualitative"]
    assert abs(total - 1.0) < 1e-9


def test_env_override_lookback_days(monkeypatch):
    """policy_lookback_days 应支持 TRADINGAGENTS_ 环境变量覆盖。"""
    # 重新导入以触发 _apply_env_overrides
    monkeypatch.setenv("TRADINGAGENTS_POLICY_LOOKBACK_DAYS", "20")
    import importlib
    from tradingagents import default_config as dc
    importlib.reload(dc)
    try:
        assert dc.DEFAULT_CONFIG["policy_lookback_days"] == 20
    finally:
        importlib.reload(dc)  # 还原
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_config.py -v`
Expected: FAIL（`KeyError: 'policy_themes_file'` 等，配置项尚未定义）

- [ ] **Step 3: 实现 — 注册 env override**

Edit `tradingagents/default_config.py`，在 `_ENV_OVERRIDES` 字典末尾（`"TRADINGAGENTS_BENCHMARK_TICKER"` 那一行之后）新增三行：

```python
    "TRADINGAGENTS_POLICY_LOOKBACK_DAYS":   "policy_lookback_days",
    "TRADINGAGENTS_POLICY_TOP_N":           "policy_top_n",
    "TRADINGAGENTS_POLICY_DEEP_ANALYZE_TOP": "policy_deep_analyze_top",
```

- [ ] **Step 4: 实现 — 在 DEFAULT_CONFIG 末尾新增配置块**

仍在 `tradingagents/default_config.py`，在 `DEFAULT_CONFIG` 字典的 `"fund_nav_lookback_days": 90,` 那一行之后、字典结束的 `})` 之前，新增：

```python
    # 政策扶持标的推荐筛选器（policy_screener）配置
    # 预置主题映射表路径（相对项目根，用户可改）
    "policy_themes_file": "tradingagents/policy_screener/data/policy_themes.yaml",
    # 启用的主题名列表；空列表 = 启用映射表中的全部主题
    "policy_enabled_themes": [],
    "policy_lookback_days": 10,            # 资金面回看天数
    "policy_top_n": 10,                    # 推荐池保留数量
    "policy_deep_analyze_top": 3,          # 对前 N 个跑深度 Agent
    # "主力未介入"判定阈值（标的需同时满足才进推荐池）
    "policy_thresholds": {
        "main_net_inflow_ratio": 0.01,     # 主力净流入合计 / 流通市值 ≤ 1%
        "price_gain_ratio": 0.15,          # 区间涨幅 ≤ 15%
        "turnover_rate": 0.05,             # 日均换手率 ≤ 5%
    },
    # 综合分权重，三者之和应为 1.0
    "policy_weights": {
        "relevance": 0.30,                 # 政策相关度
        "fund_flow": 0.45,                 # 资金面量化
        "llm_qualitative": 0.25,           # LLM 定性
    },
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_config.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add tradingagents/default_config.py tests/policy_screener/__init__.py tests/policy_screener/test_config.py
git commit -m "feat(policy-screener): register policy_* config keys"
```

---

## Task 2: 数据模型 models.py

定义全模块共享的数据类。其他所有任务依赖它，故最先实现。

**Files:**
- Create: `tradingagents/policy_screener/models.py`
- Test: `tests/policy_screener/test_models.py`

- [ ] **Step 1: 写失败测试**

Create `tests/policy_screener/test_models.py`:

```python
import math
from tradingagents.policy_screener.models import (
    Candidate,
    ScoredCandidate,
    FundFlowMetrics,
)


def test_candidate_basic_fields():
    c = Candidate(ticker="600519.SS", name="贵州茅台", theme="新质生产力", is_fund=False, sector="白酒")
    assert c.ticker == "600519.SS"
    assert c.is_fund is False


def test_scored_candidate_inherits_candidate():
    s = ScoredCandidate(
        ticker="159995", name="芯片ETF", theme="新质生产力",
        is_fund=True, sector="半导体",
        relevance_score=90.0, fund_flow_score=80.0, llm_qualitative_score=70.0,
        composite_score=82.5, metrics={"price_gain_ratio": 0.05}, reason="主力未介入",
    )
    assert s.composite_score == 82.5
    assert s.metrics["price_gain_ratio"] == 0.05
    # 继承自 Candidate
    assert s.theme == "新质生产力"
    assert s.is_fund is True


def test_scored_candidate_reason_defaults_to_empty():
    s = ScoredCandidate(
        ticker="000001", name="X", theme="T", is_fund=False, sector="S",
        relevance_score=50, fund_flow_score=50, llm_qualitative_score=50, composite_score=50,
        metrics={},
    )
    assert s.reason == ""


def test_fund_flow_metrics_defaults_none():
    m = FundFlowMetrics(ticker="600519.SS")
    assert m.main_net_inflow_ratio is None
    assert m.price_gain_ratio is None
    assert m.is_fund is False
    assert m.data_source == "akshare"
    assert m.fetch_error is None
    assert math.isnan(m.main_net_inflow_ratio) is False  # 即 None


def test_fund_flow_metrics_carries_error():
    m = FundFlowMetrics(ticker="X", fetch_error="timeout")
    assert m.fetch_error == "timeout"
    assert m.data_source == "akshare"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_models.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'tradingagents.policy_screener'`）

- [ ] **Step 3: 创建子包占位**

Create `tradingagents/policy_screener/__init__.py`（暂时空文件，Task 13 再填充导出）：

```python
"""政策扶持标的推荐筛选器子包。"""
```

- [ ] **Step 4: 实现 models.py**

Create `tradingagents/policy_screener/models.py`:

```python
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
    data_source: str = "akshare"                     # "akshare" | "none"（降级标记）
    fetch_error: Optional[str] = None               # 非空表示该标的拉取失败


@dataclass
class ScoredCandidate(Candidate):
    """打分后的候选标的。"""

    relevance_score: float = 0.0          # 政策相关度 0-100
    fund_flow_score: float = 0.0          # 量化资金面分 0-100
    llm_qualitative_score: float = 0.0     # LLM 定性分 0-100
    composite_score: float = 0.0          # 综合分
    metrics: dict = field(default_factory=dict)  # 原始指标，供报告展示
    reason: str = ""                      # 一句话推荐理由
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_models.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add tradingagents/policy_screener/__init__.py tradingagents/policy_screener/models.py tests/policy_screener/test_models.py
git commit -m "feat(policy-screener): add shared data models"
```

---

## Task 3: 主题映射表 themes.py + policy_themes.yaml

加载、校验预置主题表。这是筛选器的硬依赖——表缺失或格式错应报错退出。

**Files:**
- Create: `tradingagents/policy_screener/data/policy_themes.yaml`
- Create: `tradingagents/policy_screener/themes.py`
- Test: `tests/policy_screener/test_themes.py`

- [ ] **Step 1: 写失败测试**

Create `tests/policy_screener/test_themes.py`:

```python
import textwrap
from pathlib import Path

import pytest

from tradingagents.policy_screener.themes import ThemeConfig, load_themes


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "policy_themes.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_load_themes_parses_valid_file(tmp_path):
    p = _write_yaml(tmp_path, """
        themes:
          新质生产力:
            keywords: ["半导体", "人工智能"]
            sectors: ["半导体"]
            funds: ["159995"]
          低空经济:
            keywords: ["低空经济"]
            sectors: ["低空经济"]
            funds: []
    """)
    cfg = load_themes(str(p), enabled=[])
    assert isinstance(cfg, ThemeConfig)
    names = cfg.enabled_theme_names()
    assert "新质生产力" in names
    assert "低空经济" in names


def test_enabled_filter_restricts_themes(tmp_path):
    p = _write_yaml(tmp_path, """
        themes:
          A:
            keywords: ["a"]
            sectors: ["a"]
            funds: []
          B:
            keywords: ["b"]
            sectors: ["b"]
            funds: []
    """)
    cfg = load_themes(str(p), enabled=["A"])
    assert cfg.enabled_theme_names() == ["A"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_themes(str(tmp_path / "nope.yaml"), enabled=[])


def test_missing_top_level_themes_key_raises(tmp_path):
    p = _write_yaml(tmp_path, """
        wrong_key: {}
    """)
    with pytest.raises(ValueError, match="缺少顶级 'themes' 键"):
        load_themes(str(p), enabled=[])


def test_theme_missing_required_field_raises(tmp_path):
    p = _write_yaml(tmp_path, """
        themes:
          半导体:
            keywords: ["半导体"]
            # 缺 sectors
            funds: []
    """)
    with pytest.raises(ValueError, match="缺少字段 'sectors'"):
        load_themes(str(p), enabled=[])


def test_get_theme_returns_config():
    cfg = ThemeConfig({
        "半导体": {"keywords": ["k"], "sectors": ["s"], "funds": ["f"]},
    })
    t = cfg.get_theme("半导体")
    assert t["sectors"] == ["s"]


def test_get_theme_unknown_raises():
    cfg = ThemeConfig({"半导体": {"keywords": ["k"], "sectors": ["s"], "funds": []}})
    with pytest.raises(KeyError):
        cfg.get_theme("不存在")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_themes.py -v`
Expected: FAIL（`ModuleNotFoundError`，因 themes.py 未创建）

- [ ] **Step 3: 创建预置映射表**

Create `tradingagents/policy_screener/data/policy_themes.yaml`:

```yaml
# 政策主题 → 行业/板块/基金 映射表
# 用户可自行增删改主题。
# - sectors: 东财概念板块名，必须与 ak.stock_board_concept_name_em() 返回名严格一致
# - funds:   相关 ETF/基金代码（6位）
# - keywords: 主题关键词，供 LLM 定性分析参考
themes:
  新质生产力:
    keywords: ["半导体", "先进算力", "人工智能", "量子", "高端制造"]
    sectors: ["半导体", "人工智能"]
    funds: ["159995", "515050"]
  低空经济:
    keywords: ["低空经济", "eVTOL", "无人机", "通用航空"]
    sectors: ["低空经济"]
    funds: ["159357"]
  设备更新:
    keywords: ["设备更新", "大规模以旧换新", "工程机械", "通用设备"]
    sectors: ["工程机械", "通用设备"]
    funds: ["159766"]
  数据要素:
    keywords: ["数据要素", "数据交易", "数字经济"]
    sectors: ["数据要素"]
    funds: ["516160"]
  新能源:
    keywords: ["光伏", "风电", "储能", "新能源"]
    sectors: ["光伏设备", "风电设备"]
    funds: ["516160"]
```

- [ ] **Step 4: 实现 themes.py**

Create `tradingagents/policy_screener/themes.py`:

```python
"""政策主题映射表加载与校验。

映射表为 YAML 文件，结构见 data/policy_themes.yaml。
表缺失或格式错误是硬依赖故障，直接抛异常终止。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

# 每个主题必须包含的字段
_REQUIRED_FIELDS = ("keywords", "sectors", "funds")


class ThemeConfig:
    """已加载并校验的主题映射表。"""

    def __init__(self, themes: Dict[str, dict]):
        self._themes = themes

    def enabled_theme_names(self) -> List[str]:
        """返回全部主题名（enabled 过滤已在 load_themes 完成）。"""
        return list(self._themes.keys())

    def get_theme(self, name: str) -> dict:
        """取单个主题配置；不存在则 KeyError。"""
        if name not in self._themes:
            raise KeyError(f"未知主题: {name}")
        return self._themes[name]

    def all_themes(self) -> Dict[str, dict]:
        return self._themes


def _validate(theme_name: str, theme: dict) -> None:
    if not isinstance(theme, dict):
        raise ValueError(f"主题 '{theme_name}' 不是映射")
    for field in _REQUIRED_FIELDS:
        if field not in theme:
            raise ValueError(f"主题 '{theme_name}' 缺少字段 '{field}'")
        if not isinstance(theme[field], list):
            raise ValueError(f"主题 '{theme_name}' 字段 '{field}' 必须是列表")


def load_themes(path: str, enabled: List[str]) -> ThemeConfig:
    """加载并校验主题表。

    Args:
        path: YAML 文件路径。
        enabled: 启用的主题名列表；空列表表示启用全部。

    Returns:
        校验后的 ThemeConfig（仅含启用主题）。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 格式错误或缺字段。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"主题映射表不存在: {path}")

    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "themes" not in data:
        raise ValueError(f"主题表 {path} 缺少顶级 'themes' 键")

    all_themes = data["themes"]
    if not isinstance(all_themes, dict):
        raise ValueError(f"主题表 {path} 的 'themes' 必须是映射")

    # 校验全部主题（即便未启用，格式错也要尽早暴露）
    for name, theme in all_themes.items():
        _validate(name, theme)

    # 按 enabled 过滤；空列表 = 全部启用
    if enabled:
        unknown = [n for n in enabled if n not in all_themes]
        if unknown:
            raise ValueError(f"启用了未知主题: {unknown}")
        selected = {n: all_themes[n] for n in enabled}
    else:
        selected = all_themes

    return ThemeConfig(selected)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_themes.py -v`
Expected: 7 passed

- [ ] **Step 6: 提交**

```bash
git add tradingagents/policy_screener/themes.py tradingagents/policy_screener/data/policy_themes.yaml tests/policy_screener/test_themes.py
git commit -m "feat(policy-screener): add theme mapping loader and preset yaml"
```

---

## Task 4: 主题展开器 expander.py

把启用主题展开为候选标的池。akshare 板块成分调用在此模块，但**纯展开逻辑与 akshare 调用分离**：`expand_themes()` 接收一个可注入的板块成分获取函数，便于测试时 mock。

**Files:**
- Create: `tradingagents/policy_screener/expander.py`
- Test: `tests/policy_screener/test_expander.py`

- [ ] **Step 1: 写失败测试**

Create `tests/policy_screener/test_expander.py`:

```python
from tradingagents.policy_screener.models import Candidate
from tradingagents.policy_screener.themes import ThemeConfig
from tradingagents.policy_screener.expander import expand_themes, fetch_board_cons, AShareMarket


def _cfg():
    return ThemeConfig({
        "新质生产力": {
            "keywords": ["半导体"],
            "sectors": ["半导体"],
            "funds": ["159995"],
        },
        "低空经济": {
            "keywords": ["低空经济"],
            "sectors": ["低空经济"],
            "funds": [],
        },
    })


def _fake_cons_fetcher(records):
    """返回一个模拟的板块成分获取函数：sector -> [(code, name), ...]。"""
    def _f(sector: str):
        return records.get(sector, [])
    return _f


def test_expand_stocks_and_funds():
    fetcher = _fake_cons_fetcher({
        "半导体": [("600584", "长电科技"), ("002049", "紫光国微")],
    })
    cands = expand_themes(_cfg(), fetcher)
    # 2 只股票 + 1 只基金
    assert len(cands) == 3
    tickers = {c.ticker for c in cands}
    assert "600584.SS" in tickers      # 600 开头 → .SS
    assert "002049.SZ" in tickers     # 002 开头 → .SZ
    assert "159995" in tickers        # 基金保留原码


def test_expand_marks_fund_flag():
    fetcher = _fake_cons_fetcher({"半导体": [("600584", "长电科技")]})
    cands = expand_themes(_cfg(), fetcher)
    by_code = {c.ticker: c for c in cands}
    assert by_code["600584.SS"].is_fund is False
    assert by_code["159995"].is_fund is True


def test_expand_attaches_theme_and_sector():
    fetcher = _fake_cons_fetcher({"半导体": [("600584", "长电科技")]})
    cands = expand_themes(_cfg(), fetcher)
    stock = next(c for c in cands if c.ticker == "600584.SS")
    assert stock.theme == "新质生产力"
    assert stock.sector == "半导体"
    assert stock.name == "长电科技"


def test_expand_dedupes_across_themes():
    # 同一股票出现在两个主题的板块里，应去重
    cfg = ThemeConfig({
        "T1": {"keywords": ["k"], "sectors": ["共享板块"], "funds": []},
        "T2": {"keywords": ["k"], "sectors": ["共享板块"], "funds": []},
    })
    fetcher = _fake_cons_fetcher({"共享板块": [("600584", "长电科技")]})
    cands = expand_themes(cfg, fetcher)
    codes = [c.ticker for c in cands if not c.is_fund]
    assert codes.count("600584.SS") == 1


def test_expand_skips_empty_sector():
    cfg = ThemeConfig({"T": {"keywords": ["k"], "sectors": ["无成分"], "funds": []}})
    fetcher = _fake_cons_fetcher({})  # 任何板块都返回空
    cands = expand_themes(cfg, fetcher)
    assert cands == []


def test_market_code_inference():
    assert AShareMarket.code_for("600584") == ("600584", "sh")
    assert AShareMarket.code_for("002049") == ("002049", "sz")
    assert AShareMarket.code_for("300750") == ("300750", "sz")
    assert AShareMarket.code_for("688981") == ("688981", "sh")


def test_market_suffix_for_codes():
    assert AShareMarket.suffix_for("600584") == ".SS"
    assert AShareMarket.suffix_for("002049") == ".SZ"
    assert AShareMarket.suffix_for("688981") == ".SS"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_expander.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 expander.py**

Create `tradingagents/policy_screener/expander.py`:

```python
"""主题 → 候选标的池展开器。

akshare 板块成分调用被隔离在 fetch_board_cons 中；
expand_themes 接收可注入的获取函数，便于测试与降级。
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from .models import Candidate
from .themes import ThemeConfig


class AShareMarket:
    """A 股市场代码推断工具。"""

    @staticmethod
    def market_of(code: str) -> str:
        """6 位代码 → 交易所代码 'sh' / 'sz'。"""
        code = code.strip()
        if code.startswith(("60", "68", "11", "13", "50", "51", "56")):
            return "sh"
        if code.startswith(("00", "30", "12", "15", "16")):
            return "sz"
        # 兜底：沪市
        return "sh"

    @staticmethod
    def code_for(code: str) -> Tuple[str, str]:
        """6 位代码 → (code, market)。"""
        return code, AShareMarket.market_of(code)

    @staticmethod
    def suffix_for(code: str) -> str:
        """6 位代码 → yfinance 式后缀 '.SS' / '.SZ'。"""
        return ".SS" if AShareMarket.market_of(code) == "sh" else ".SZ"


# 板块成分获取函数签名：sector_name -> [(code6, name), ...]
ConsFetcher = Callable[[str], List[Tuple[str, str]]]


def fetch_board_cons(sector: str) -> List[Tuple[str, str]]:
    """从 akshare 拉取概念板块成分股。

    返回 [(6位代码, 股票名称), ...]。拉取失败返回空列表（交由上层降级）。
    """
    try:
        import akshare as ak  # noqa: WPS433 — 延迟导入，避免无 akshare 时模块加载失败
        df = ak.stock_board_concept_cons_em(symbol=sector)
        if df is None or df.empty:
            return []
        out = []
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            if code and name:
                out.append((code, name))
        return out
    except Exception:
        return []


def expand_themes(config: ThemeConfig, cons_fetcher: ConsFetcher = fetch_board_cons) -> List[Candidate]:
    """展开启用主题为候选标的池。

    Args:
        config: 已加载并过滤的主题配置。
        cons_fetcher: 板块成分获取函数（测试可注入 mock）。

    Returns:
        去重后的候选标的列表（股票带交易所后缀，基金保留原码）。
    """
    candidates: List[Candidate] = []
    seen: set = set()  # 已收录 (ticker) 去重

    for theme_name in config.enabled_theme_names():
        theme = config.get_theme(theme_name)

        # 股票：板块成分
        for sector in theme.get("sectors", []):
            for code, name in cons_fetcher(sector):
                ticker = f"{code}{AShareMarket.suffix_for(code)}"
                if ticker in seen:
                    continue
                seen.add(ticker)
                candidates.append(Candidate(
                    ticker=ticker, name=name, theme=theme_name,
                    is_fund=False, sector=sector,
                ))

        # 基金/ETF：直接取映射表代码
        for fund_code in theme.get("funds", []):
            fund_code = str(fund_code).strip()
            if not fund_code or fund_code in seen:
                continue
            seen.add(fund_code)
            candidates.append(Candidate(
                ticker=fund_code, name=f"基金{fund_code}", theme=theme_name,
                is_fund=True, sector=theme.get("sectors", [""])[0] if theme.get("sectors") else "",
            ))

    return candidates
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_expander.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add tradingagents/policy_screener/expander.py tests/policy_screener/test_expander.py
git commit -m "feat(policy-screener): theme expander with injectable board fetcher"
```

---

## Task 5: 资金面打分纯函数（含阈值过滤）

本任务实现**纯函数**部分：`score_metrics()` 把原始指标转为 0–100 分，`passes_threshold()` 判定是否"主力未介入"。不含 akshare 调用（下个任务）。这是打分逻辑的核心，必须用构造数据精确断言。

**打分逻辑说明**：每个指标用线性映射换算到 0–100，"未介入"程度越高分越高；缺失指标跳过；全部缺失时返回中性 50。

- [ ] **Step 1: 写失败测试**

Create `tests/policy_screener/test_fund_flow_scorer.py`（先只含纯函数测试，akshare 部分下个任务再加）:

```python
from tradingagents.policy_screener.models import FundFlowMetrics
from tradingagents.policy_screener.fund_flow_scorer import score_metrics, passes_threshold

THRESHOLDS = {
    "main_net_inflow_ratio": 0.01,
    "price_gain_ratio": 0.15,
    "turnover_rate": 0.05,
}


# ── score_metrics ──────────────────────────────────────────────

def test_score_low_inflow_low_gain_high_turnover_is_high():
    """主力未流入 + 未拉升 + 换手适中 → 高分。"""
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=-0.005,  # 净流出
        price_gain_ratio=0.03,        # 微涨
        turnover_rate=0.02,           # 低换手
    )
    score = score_metrics(m)
    assert 70 <= score <= 100


def test_score_high_inflow_high_gain_is_low():
    """主力大举流入 + 已大涨 → 低分。"""
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.05,   # 5% 净流入，远超阈值
        price_gain_ratio=0.30,        # 涨 30%
        turnover_rate=0.12,           # 高换手
    )
    score = score_metrics(m)
    assert 0 <= score <= 30


def test_score_clamped_to_0_100():
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=-1.0,  # 极端净流出
        price_gain_ratio=-0.5,       # 大跌
        turnover_rate=0.0,
    )
    score = score_metrics(m)
    assert score == 100.0


def test_score_missing_metrics_returns_neutral():
    m = FundFlowMetrics(ticker="X")  # 全 None
    assert score_metrics(m) == 50.0


def test_score_partial_metrics_uses_available():
    # 只有涨幅一个指标：未拉升 → 高分
    m = FundFlowMetrics(ticker="X", price_gain_ratio=0.02)
    score = score_metrics(m)
    assert score > 60


# ── passes_threshold ────────────────────────────────────────────

def test_threshold_pass_when_all_under_threshold():
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.005,   # < 0.01
        price_gain_ratio=0.10,         # < 0.15
        turnover_rate=0.03,            # < 0.05
    )
    assert passes_threshold(m, THRESHOLDS) is True


def test_threshold_fail_when_gain_too_high():
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.005,
        price_gain_ratio=0.20,         # > 0.15
        turnover_rate=0.03,
    )
    assert passes_threshold(m, THRESHOLDS) is False


def test_threshold_fail_when_inflow_too_high():
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.02,    # > 0.01
        price_gain_ratio=0.10,
        turnover_rate=0.03,
    )
    assert passes_threshold(m, THRESHOLDS) is False


def test_threshold_missing_metric_ignored():
    """缺失的指标不参与判定（不因缺失而淘汰）。"""
    m = FundFlowMetrics(
        ticker="X",
        main_net_inflow_ratio=0.005,
        price_gain_ratio=0.10,
        turnover_rate=None,            # 换手率缺失
    )
    assert passes_threshold(m, THRESHOLDS) is True


def test_threshold_all_missing_passes():
    """指标全缺失（akshare 不可用降级）时，不因资金面被淘汰。"""
    m = FundFlowMetrics(ticker="X")
    assert passes_threshold(m, THRESHOLDS) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_fund_flow_scorer.py -v`
Expected: FAIL（`ImportError: cannot import name 'score_metrics'`）

- [ ] **Step 3: 实现 fund_flow_scorer.py（纯函数部分）**

Create `tradingagents/policy_screener/fund_flow_scorer.py`:

```python
"""资金面打分器。

分两层：
  - 纯函数层（本文件上半部）：score_metrics / passes_threshold，可精确测试。
  - akshare 拉取层（本文件下半部 + runner 调用）：fetch_metrics。

打分语义：指标越接近"未介入"端，分越高（0-100，缺失指标跳过）。
"""

from __future__ import annotations

from typing import Optional

from .models import FundFlowMetrics


# ── 纯函数：单指标 → 0-100 ──────────────────────────────────────

def _ratio_score(value: float, neutral: float, saturate: float) -> float:
    """线性把 ratio 映射到 0-100：值 ≤ neutral 得 100，值 ≥ saturate 得 0。

    value 越低（主力未介入）→ 分越高。
    """
    if value <= neutral:
        return 100.0
    if value >= saturate:
        return 0.0
    # 线性插值
    return 100.0 * (saturate - value) / (saturate - neutral)


def score_metrics(metrics: FundFlowMetrics) -> float:
    """把资金面原始指标合成为 0-100 分。

    缺失（None）的指标跳过；全部缺失返回中性 50。
    """
    scores = []

    if metrics.main_net_inflow_ratio is not None:
        # neutral=0（净流出即满分）, saturate=0.05（5% 净流入即 0 分）
        scores.append(_ratio_score(metrics.main_net_inflow_ratio, neutral=0.0, saturate=0.05))

    if metrics.north_inflow is not None:
        # 北向净流入：0 即满分，+500(百万) 即 0 分
        scores.append(_ratio_score(metrics.north_inflow, neutral=0.0, saturate=500.0))

    if metrics.price_gain_ratio is not None:
        # 涨幅：0 即满分，+0.30(涨30%) 即 0 分；下跌同样高分
        scores.append(_ratio_score(metrics.price_gain_ratio, neutral=0.0, saturate=0.30))

    if metrics.turnover_rate is not None:
        # 换手率：0 即满分，0.15(15%) 即 0 分
        scores.append(_ratio_score(metrics.turnover_rate, neutral=0.0, saturate=0.15))

    if metrics.share_change_ratio is not None:
        # 份额变化：0 即满分，+0.30(增30%) 即 0 分
        scores.append(_ratio_score(metrics.share_change_ratio, neutral=0.0, saturate=0.30))

    if not scores:
        return 50.0

    avg = sum(scores) / len(scores)
    return float(max(0.0, min(100.0, avg)))


def passes_threshold(metrics: FundFlowMetrics, thresholds: dict) -> bool:
    """判定是否"主力尚未大举介入"。

    仅对存在的指标判定；缺失指标跳过（不淘汰）。
    全部缺失时返回 True（不因数据缺失而淘汰，留给 LLM 档评判）。
    """
    checks = []

    if metrics.main_net_inflow_ratio is not None:
        lim = thresholds["main_net_inflow_ratio"]
        checks.append(metrics.main_net_inflow_ratio <= lim)

    if metrics.price_gain_ratio is not None:
        lim = thresholds["price_gain_ratio"]
        checks.append(metrics.price_gain_ratio <= lim)

    if metrics.turnover_rate is not None:
        lim = thresholds["turnover_rate"]
        checks.append(metrics.turnover_rate <= lim)

    if not checks:
        return True
    return all(checks)


# ── akshare 拉取层 ──────────────────────────────────────────────
# （下方函数在 Task 6 实现）
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_fund_flow_scorer.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add tradingagents/policy_screener/fund_flow_scorer.py tests/policy_screener/test_fund_flow_scorer.py
git commit -m "feat(policy-screener): pure fund-flow scoring and threshold gate"
```

---

## Task 6: akshare 指标拉取 fetch_metrics

把 akshare 三个接口（个股资金流、日线、北向）的数据聚合为 `FundFlowMetrics`。基金/ETF 走 `fund_etf_hist_em`。全部异常吞掉、记入 `fetch_error`，绝不抛出（降级交给上层）。

**Files:**
- Modify: `tradingagents/policy_screener/fund_flow_scorer.py`（追加 fetch 函数）
- Test: `tests/policy_screener/test_fund_flow_scorer.py`（追加 fetch 测试）

- [ ] **Step 1: 写失败测试 — 追加到现有测试文件末尾**

在 `tests/policy_screener/test_fund_flow_scorer.py` 顶部新增导入：

```python
from unittest.mock import patch, MagicMock
import pandas as pd
from tradingagents.policy_screener.fund_flow_scorer import fetch_metrics
```

在文件末尾追加：

```python
def _stock_fund_flow_df():
    return pd.DataFrame({
        "日期": ["20260610", "20260611"],
        "主力净流入-净占比": [0.2, -0.3],   # 近2日合计 ≈ -0.1%（近未介入）
    })


def _stock_hist_df():
    return pd.DataFrame({
        "日期": ["20260601", "20260610"],
        "收盘": [10.0, 10.2],
        "换手率": [2.0, 3.0],
        "涨跌幅": [0.0, 2.0],
    })


def _hsgt_df():
    return pd.DataFrame({
        "持股日期": ["20260610", "20260611"],
        "今日增持资金": [100.0, -50.0],   # 百万元
    })


def test_fetch_stock_metrics_aggregates_three_sources():
    with patch("akshare.stock_individual_fund_flow", return_value=_stock_fund_flow_df()), \
         patch("akshare.stock_zh_a_hist", return_value=_stock_hist_df()), \
         patch("akshare.stock_hsgt_individual_em", return_value=_hsgt_df()):
        m = fetch_metrics("600584.SS", "2026-06-18", lookback=10, is_fund=False)
    assert m.ticker == "600584.SS"
    assert m.is_fund is False
    assert m.main_net_inflow_ratio is not None
    assert m.price_gain_ratio is not None       # (10.2-10)/10 = 0.02
    assert abs(m.price_gain_ratio - 0.02) < 1e-9
    assert m.turnover_rate is not None         # 均值 2.5% = 0.025
    assert abs(m.turnover_rate - 0.025) < 1e-9
    assert m.fetch_error is None


def test_fetch_stock_metrics_degrades_on_failure():
    """akshare 抛异常时，metrics 字段为空但带 fetch_error，不抛。"""
    with patch("akshare.stock_individual_fund_flow", side_effect=RuntimeError("timeout")), \
         patch("akshare.stock_zh_a_hist", side_effect=RuntimeError("timeout")), \
         patch("akshare.stock_hsgt_individual_em", side_effect=RuntimeError("timeout")):
        m = fetch_metrics("600584.SS", "2026-06-18", lookback=10, is_fund=False)
    assert m.main_net_inflow_ratio is None
    assert m.price_gain_ratio is None
    assert m.fetch_error is not None
    assert "timeout" in m.fetch_error


def test_fetch_fund_metrics_uses_etf_hist():
    etf_df = pd.DataFrame({
        "日期": ["20260601", "20260610"],
        "收盘": [1.0, 1.02],
        "换手率": [1.5, 2.5],
        "涨跌幅": [0.0, 2.0],
    })
    with patch("akshare.fund_etf_hist_em", return_value=etf_df):
        m = fetch_metrics("159995", "2026-06-18", lookback=10, is_fund=True)
    assert m.is_fund is True
    assert m.main_net_inflow_ratio is None      # 基金无主力净流入口径
    assert m.price_gain_ratio is not None
    assert m.turnover_rate is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_fund_flow_scorer.py -v`
Expected: FAIL（`ImportError: cannot import name 'fetch_metrics'`）

- [ ] **Step 3: 实现 — 追加 fetch 函数到 fund_flow_scorer.py**

Edit `tradingagents/policy_screener/fund_flow_scorer.py`，把文件末尾的占位注释：

```python
# ── akshare 拉取层 ──────────────────────────────────────────────
# （下方函数在 Task 6 实现）
```

替换为：

```python
# ── akshare 拉取层 ──────────────────────────────────────────────

def _to_int_date(date_str: str) -> str:
    """'2026-06-18' → '20260618'。"""
    return date_str.replace("-", "")


def _strip_suffix(ticker: str) -> str:
    return ticker.split(".")[0]


def fetch_metrics(ticker: str, end_date: str, lookback: int, is_fund: bool) -> FundFlowMetrics:
    """从 akshare 拉取单只标的近 lookback 日资金面指标。

    任何异常都被吞掉并记入 fetch_error，绝不抛出（降级由调用方处理）。
    """
    if is_fund:
        return _fetch_fund_metrics(ticker, end_date, lookback)
    return _fetch_stock_metrics(ticker, end_date, lookback)


def _fetch_stock_metrics(ticker: str, end_date: str, lookback: int) -> FundFlowMetrics:
    import akshare as ak

    code = _strip_suffix(ticker)
    market = "sh" if ticker.endswith(".SS") else "sz"
    int_end = _to_int_date(end_date)

    main_ratio = None
    north = None
    gain = None
    turnover = None
    errors = []

    # 1) 个股资金流（主力净流入占比）
    try:
        df = ak.stock_individual_fund_flow(stock=code, market=market)
        if df is not None and not df.empty and "主力净流入-净占比" in df.columns:
            recent = df.tail(lookback)
            # 净占比是百分数（如 0.2 表示 0.2%），转成小数
            main_ratio = float(pd.to_numeric(recent["主力净流入-净占比"], errors="coerce").sum()) / 100.0
    except Exception as e:
        errors.append(f"fund_flow:{e}")

    # 2) 个股日线（涨幅、换手率）
    try:
        # 近 lookback*2 个自然日，确保有足够交易日
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                               start_date=int_end, end_date=int_end, adjust="")
        # 上面的 start==end 可能只取到一天；放宽窗口重取
        if df is None or df.empty:
            df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="")
        if df is not None and not df.empty and "收盘" in df.columns:
            recent = df.tail(lookback)
            closes = pd.to_numeric(recent["收盘"], errors="coerce").dropna()
            if len(closes) >= 2:
                gain = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])
            if "换手率" in recent.columns:
                turnover = float(pd.to_numeric(recent["换手率"], errors="coerce").mean()) / 100.0
    except Exception as e:
        errors.append(f"hist:{e}")

    # 3) 北向个股持股
    try:
        df = ak.stock_hsgt_individual_em(symbol=code)
        if df is not None and not df.empty and "今日增持资金" in df.columns:
            recent = df.tail(lookback)
            north = float(pd.to_numeric(recent["今日增持资金"], errors="coerce").sum())
    except Exception as e:
        errors.append(f"hsgt:{e}")

    return FundFlowMetrics(
        ticker=ticker,
        main_net_inflow_ratio=main_ratio,
        north_inflow=north,
        price_gain_ratio=gain,
        turnover_rate=turnover,
        is_fund=False,
        fetch_error="; ".join(errors) if errors else None,
    )


def _fetch_fund_metrics(ticker: str, end_date: str, lookback: int) -> FundFlowMetrics:
    import akshare as ak

    code = _strip_suffix(ticker)
    gain = None
    turnover = None
    errors = []

    try:
        df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="")
        if df is not None and not df.empty and "收盘" in df.columns:
            recent = df.tail(lookback)
            closes = pd.to_numeric(recent["收盘"], errors="coerce").dropna()
            if len(closes) >= 2:
                gain = float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])
            if "换手率" in recent.columns:
                turnover = float(pd.to_numeric(recent["换手率"], errors="coerce").mean()) / 100.0
    except Exception as e:
        errors.append(f"etf_hist:{e}")

    return FundFlowMetrics(
        ticker=ticker,
        price_gain_ratio=gain,
        turnover_rate=turnover,
        is_fund=True,
        # 基金无主力净流入/北向口径，main_net_inflow_ratio 保持 None
        fetch_error="; ".join(errors) if errors else None,
    )
```

同时在文件顶部补一行导入 pandas（`score_metrics` 上方）：

```python
import pandas as pd
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_fund_flow_scorer.py -v`
Expected: 13 passed（10 纯函数 + 3 fetch）

- [ ] **Step 5: 提交**

```bash
git add tradingagents/policy_screener/fund_flow_scorer.py tests/policy_screener/test_fund_flow_scorer.py
git commit -m "feat(policy-screener): akshare fund-flow metrics fetch with graceful degradation"
```

---

## Task 7: LLM 定性打分 llm_qualifier.py

让 LLM 从标的名称+主题推断"机构关注但未重仓"等定性信号，输出 0–100 分 + 一句话理由。LLM 不可用时降级为中性分 50 + 默认理由，绝不抛异常。

**Files:**
- Create: `tradingagents/policy_screener/llm_qualifier.py`
- Test: `tests/policy_screener/test_llm_qualifier.py`

- [ ] **Step 1: 写失败测试**

Create `tests/policy_screener/test_llm_qualifier.py`:

```python
from unittest.mock import MagicMock, patch

from tradingagents.policy_screener.models import Candidate
from tradingagents.policy_screener.llm_qualifier import qualify, parse_llm_score


def _cand():
    return Candidate(ticker="600584.SS", name="长电科技", theme="新质生产力", is_fund=False, sector="半导体")


def test_parse_llm_score_valid_json():
    score, reason = parse_llm_score('{"score": 82, "reason": "机构调研增加但仓位低"}')
    assert score == 82
    assert "仓位低" in reason


def test_parse_llm_score_clamps():
    score, _ = parse_llm_score('{"score": 150, "reason": "x"}')
    assert score == 100
    score, _ = parse_llm_score('{"score": -10, "reason": "x"}')
    assert score == 0


def test_parse_llm_score_bad_json_returns_neutral():
    score, reason = parse_llm_score("这不是JSON")
    assert score == 50
    assert reason != ""


def test_qualify_calls_llm_and_returns_score():
    mock_llm = MagicMock()
    # llm.invoke 返回带 content 属性的对象（langchain AIMessage 风格）
    mock_llm.invoke.return_value = MagicMock(content='{"score": 75, "reason": "政策催化待落地"}')
    score, reason = qualify(_cand(), mock_llm)
    assert score == 75
    assert "催化" in reason
    mock_llm.invoke.assert_called_once()


def test_qualify_degrades_when_llm_none():
    """LLM 客户端为 None（不可用）时降级为中性分，不抛异常。"""
    score, reason = qualify(_cand(), None)
    assert score == 50
    assert reason != ""


def test_qualify_degrades_when_llm_raises():
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API error")
    score, reason = qualify(_cand(), mock_llm)
    assert score == 50
    assert reason != ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_llm_qualifier.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 llm_qualifier.py**

Create `tradingagents/policy_screener/llm_qualifier.py`:

```python
"""LLM 定性打分器。

让 LLM 从标的与政策主题的关联，推断"机构关注度上升但尚未重仓"等
定性信号，输出 0-100 分 + 一句话理由。

LLM 不可用（client 为 None 或调用抛异常）时降级为中性分 50。
不与现有 fund_news_analyst 混用：本模块只产出结构化分数，不写报告。
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

from .models import Candidate

_SYSTEM_PROMPT = (
    "你是一位擅长 A 股与公募基金的资深机构配置分析师。"
    "给定一只标的及其所属国家政策主题，判断当前'主力资金/机构资金"
    "尚未大规模介入'的程度（越未介入越高分），并给出一句话理由。"
    "只输出 JSON，格式：{\"score\": 0到100的整数, \"reason\": \"不超过30字\"}。"
)


def parse_llm_score(text: str) -> Tuple[int, str]:
    """从 LLM 文本解析 score/reason。

    解析失败或越界返回中性 (50, 默认理由)。
    """
    try:
        # 容错：可能文本含额外说明，尝试截取首个 {...}
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        obj = json.loads(text)
        score = int(round(float(obj["score"])))
        score = max(0, min(100, score))
        reason = str(obj.get("reason", "")).strip() or "无理由"
        return score, reason
    except Exception:
        return 50, "LLM 响应解析失败，采用中性分"


def qualify(candidate: Candidate, llm) -> Tuple[int, str]:
    """对单只候选标的做 LLM 定性打分。

    Args:
        candidate: 候选标的。
        llm: langchain 风格 LLM 对象（有 invoke 方法）。None 表示不可用。

    Returns:
        (score 0-100, reason 字符串)。LLM 不可用时返回 (50, 默认理由)。
    """
    if llm is None:
        return 50, "LLM 不可用，采用中性分"

    user_prompt = (
        f"标的：{candidate.name}（{candidate.ticker}），"
        f"所属政策主题：{candidate.theme}，板块：{candidate.sector}，"
        f"类型：{'基金/ETF' if candidate.is_fund else '股票'}。"
        f"请判断主力资金尚未大规模介入的程度并输出 JSON。"
    )

    try:
        messages = [
            ("system", _SYSTEM_PROMPT),
            ("human", user_prompt),
        ]
        resp = llm.invoke(messages)
        content = getattr(resp, "content", str(resp))
        return parse_llm_score(str(content))
    except Exception:
        return 50, "LLM 调用失败，采用中性分"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_llm_qualifier.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add tradingagents/policy_screener/llm_qualifier.py tests/policy_screener/test_llm_qualifier.py
git commit -m "feat(policy-screener): LLM qualitative scoring with graceful degradation"
```

---

## Task 8: 综合排序 ranker.py

加权合并三档分数 + 阈值过滤 + 降序排序 + 截断 Top N。纯函数。

**Files:**
- Create: `tradingagents/policy_screener/ranker.py`
- Test: `tests/policy_screener/test_ranker.py`

- [ ] **Step 1: 写失败测试**

Create `tests/policy_screener/test_ranker.py`:

```python
from tradingagents.policy_screener.models import Candidate, ScoredCandidate, FundFlowMetrics
from tradingagents.policy_screener.ranker import rank_candidates, composite_score

THRESHOLDS = {"main_net_inflow_ratio": 0.01, "price_gain_ratio": 0.15, "turnover_rate": 0.05}
WEIGHTS = {"relevance": 0.30, "fund_flow": 0.45, "llm_qualitative": 0.25}


def _scored(ticker, rel, ff, llm, gain=0.05, inflow=0.002, turnover=0.03):
    return ScoredCandidate(
        ticker=ticker, name=ticker, theme="T", is_fund=False, sector="S",
        relevance_score=rel, fund_flow_score=ff, llm_qualitative_score=llm,
        composite_score=0.0,
        metrics=FundFlowMetrics(ticker=ticker, price_gain_ratio=gain,
                               main_net_inflow_ratio=inflow, turnover_rate=turnover).__dict__,
    )


def test_composite_score_weighted_average():
    s = _scored("A", rel=100, ff=80, llm=60)
    assert abs(composite_score(s, WEIGHTS) - (0.30*100 + 0.45*80 + 0.25*60)) < 1e-9


def test_rank_orders_by_composite_desc():
    a = _scored("A", 50, 50, 50)
    b = _scored("B", 90, 90, 90)
    c = _scored("C", 60, 60, 60)
    ranked = rank_candidates([a, b, c], THRESHOLDS, WEIGHTS, top_n=10)
    assert [r.ticker for r in ranked] == ["B", "C", "A"]


def test_rank_filters_out_threshold_violators():
    # B 涨幅 30% 超阈值，应被剔除
    a = _scored("A", 50, 50, 50, gain=0.05)
    b = _scored("B", 90, 90, 90, gain=0.30)
    ranked = rank_candidates([a, b], THRESHOLDS, WEIGHTS, top_n=10)
    tickers = [r.ticker for r in ranked]
    assert "A" in tickers
    assert "B" not in tickers


def test_rank_respects_top_n():
    items = [_scored(f"T{i}", i, i, i) for i in range(5)]
    ranked = rank_candidates(items, THRESHOLDS, WEIGHTS, top_n=3)
    assert len(ranked) == 3
    assert ranked[0].ticker == "T4"  # 最高分在前


def test_rank_preserves_composite_score_on_result():
    a = _scored("A", 60, 60, 60)
    ranked = rank_candidates([a], THRESHOLDS, WEIGHTS, top_n=10)
    assert ranked[0].composite_score == composite_score(a, WEIGHTS)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_ranker.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 ranker.py**

Create `tradingagents/policy_screener/ranker.py`:

```python
"""综合排序器：加权 + 阈值过滤 + 排序 + 截断。纯函数。"""

from __future__ import annotations

from typing import List

from .fund_flow_scorer import passes_threshold
from .models import FundFlowMetrics, ScoredCandidate


def composite_score(scored: ScoredCandidate, weights: dict) -> float:
    """按权重合成综合分。"""
    return (
        weights["relevance"] * scored.relevance_score
        + weights["fund_flow"] * scored.fund_flow_score
        + weights["llm_qualitative"] * scored.llm_qualitative_score
    )


def rank_candidates(
    scored: List[ScoredCandidate],
    thresholds: dict,
    weights: dict,
    top_n: int,
) -> List[ScoredCandidate]:
    """阈值过滤 → 计算综合分 → 降序排序 → 截断 top_n。

    metrics 字段里若含资金面原始指标，用于阈值判定（与 ScoredCandidate.metrics 对齐）。
    """
    passed = []
    for s in scored:
        # 从 metrics 重建 FundFlowMetrics 以复用阈值判定
        m = _metrics_from_dict(s.metrics)
        if not passes_threshold(m, thresholds):
            continue
        s.composite_score = composite_score(s, weights)
        passed.append(s)

    passed.sort(key=lambda x: x.composite_score, reverse=True)
    return passed[:top_n]


def _metrics_from_dict(d: dict) -> FundFlowMetrics:
    """从 metrics dict（可能存的是 FundFlowMetrics.__dict__）重建。"""
    if not d:
        return FundFlowMetrics(ticker="")
    return FundFlowMetrics(
        ticker=d.get("ticker", ""),
        main_net_inflow_ratio=d.get("main_net_inflow_ratio"),
        north_inflow=d.get("north_inflow"),
        price_gain_ratio=d.get("price_gain_ratio"),
        turnover_rate=d.get("turnover_rate"),
        is_fund=d.get("is_fund", False),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_ranker.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add tradingagents/policy_screener/ranker.py tests/policy_screener/test_ranker.py
git commit -m "feat(policy-screener): weighted ranking with threshold filtering"
```

---

## Task 9: Markdown 报告 reporter.py

纯函数：输入推荐池 + 可选深度分析结果，输出 Markdown 文本。

**Files:**
- Create: `tradingagents/policy_screener/reporter.py`
- Test: `tests/policy_screener/test_reporter.py`

- [ ] **Step 1: 写失败测试**

Create `tests/policy_screener/test_reporter.py`:

```python
from tradingagents.policy_screener.models import ScoredCandidate, FundFlowMetrics
from tradingagents.policy_screener.reporter import render_report


def _s(ticker, name, score, is_fund=False, gain=0.05):
    return ScoredCandidate(
        ticker=ticker, name=name, theme="新质生产力", is_fund=is_fund, sector="半导体",
        relevance_score=80, fund_flow_score=75, llm_qualitative_score=70,
        composite_score=score,
        metrics={"price_gain_ratio": gain, "turnover_rate": 0.03, "main_net_inflow_ratio": 0.002},
        reason="主力未介入",
    )


def test_report_has_title_and_date():
    md = render_report([], themes=["新质生产力"], date="2026-06-18", deep_results={})
    assert "# 政策扶持标的推荐池 (2026-06-18)" in md
    assert "新质生产力" in md


def test_report_shows_stock_and_fund_tables():
    stock = _s("600584.SS", "长电科技", 82)
    fund = _s("159995", "芯片ETF", 78, is_fund=True)
    md = render_report([stock, fund], themes=["新质生产力"], date="2026-06-18", deep_results={})
    assert "## 推荐股票" in md
    assert "长电科技" in md
    assert "## 推荐基金/ETF" in md
    assert "芯片ETF" in md


def test_report_includes_composite_score():
    md = render_report([_s("600584.SS", "长电科技", 82)], themes=["T"], date="2026-06-18", deep_results={})
    assert "82" in md


def test_report_includes_deep_analysis_when_present():
    stock = _s("600584.SS", "长电科技", 82)
    deep = {"600584.SS": "建议逐步建仓，仓位 5%。"}
    md = render_report([stock], themes=["T"], date="2026-06-18", deep_results=deep)
    assert "## 深度配置建议" in md
    assert "逐步建仓" in md


def test_report_marks_deep_analysis_failed():
    stock = _s("600584.SS", "长电科技", 82)
    deep = {"600584.SS": None}  # None 表示该标的深度分析失败
    md = render_report([stock], themes=["T"], date="2026-06-18", deep_results=deep)
    assert "深度分析失败" in md


def test_report_empty_pool_message():
    md = render_report([], themes=["T"], date="2026-06-18", deep_results={})
    assert "未筛选出符合条件" in md
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_reporter.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 reporter.py**

Create `tradingagents/policy_screener/reporter.py`:

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_reporter.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add tradingagents/policy_screener/reporter.py tests/policy_screener/test_reporter.py
git commit -m "feat(policy-screener): markdown report renderer"
```

---

## Task 10: 编排器 runner.py

`PolicyScreenerRunner.run()` 串起全部步骤。所有外部依赖（akshare、LLM、propagate）在测试中 mock。本任务验证编排正确性与降级行为。

**Files:**
- Create: `tradingagents/policy_screener/runner.py`
- Test: `tests/policy_screener/test_runner.py`

- [ ] **Step 1: 写失败测试**

Create `tests/policy_screener/test_runner.py`:

```python
from unittest.mock import patch, MagicMock

from tradingagents.policy_screener.runner import PolicyScreenerRunner
from tradingagents.default_config import DEFAULT_CONFIG


def _cfg():
    c = DEFAULT_CONFIG.copy()
    c["policy_thresholds"] = {"main_net_inflow_ratio": 0.01, "price_gain_ratio": 0.15, "turnover_rate": 0.05}
    c["policy_weights"] = {"relevance": 0.30, "fund_flow": 0.45, "llm_qualitative": 0.25}
    c["policy_lookback_days"] = 10
    c["policy_top_n"] = 10
    c["policy_deep_analyze_top"] = 0   # 不跑深度，避免依赖 graph
    return c


def _fake_cons(sector):
    # 返回两只股票
    return [("600584", "长电科技"), ("002049", "紫光国微")]


def _fake_metrics_stock(ticker, end_date, lookback, is_fund):
    from tradingagents.policy_screener.models import FundFlowMetrics
    return FundFlowMetrics(
        ticker=ticker, main_net_inflow_ratio=0.002, price_gain_ratio=0.05,
        turnover_rate=0.03, is_fund=is_fund,
    )


def _fake_metrics_fund(ticker, end_date, lookback, is_fund):
    from tradingagents.policy_screener.models import FundFlowMetrics
    return FundFlowMetrics(ticker=ticker, price_gain_ratio=0.04, turnover_rate=0.02, is_fund=True)


def _fake_qualify(candidate, llm):
    return (70, "机构调研增加")


def test_runner_produces_report_with_candidates(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  新质生产力:\n    keywords: [半导体]\n    sectors: [半导体]\n    funds: [159995]\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_themes_file"] = str(themes_path)

    monkeypatch.setattr("tradingagents.policy_screener.expander.fetch_board_cons", _fake_cons)

    def metrics_router(ticker, end_date, lookback, is_fund):
        return _fake_metrics_fund(ticker, end_date, lookback, is_fund) if is_fund else _fake_metrics_stock(ticker, end_date, lookback, is_fund)
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", metrics_router)
    monkeypatch.setattr("tradingagents.policy_screener.runner.qualify", _fake_qualify)

    runner = PolicyScreenerRunner(cfg, llm=MagicMock())
    report = runner.run(themes=["新质生产力"], date="2026-06-18", deep_analyze=False)

    assert "# 政策扶持标的推荐池 (2026-06-18)" in report
    assert "长电科技" in report
    assert "159995" in report


def test_runner_filters_threshold_violators(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_themes_file"] = str(themes_path)

    monkeypatch.setattr("tradingagents.policy_screener.expander.fetch_board_cons", lambda s: [("600584", "长电科技")])

    def hot_metrics(ticker, end_date, lookback, is_fund):
        from tradingagents.policy_screener.models import FundFlowMetrics
        return FundFlowMetrics(ticker=ticker, price_gain_ratio=0.30, turnover_rate=0.12, main_net_inflow_ratio=0.05, is_fund=False)
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", hot_metrics)
    monkeypatch.setattr("tradingagents.policy_screener.runner.qualify", _fake_qualify)

    runner = PolicyScreenerRunner(cfg, llm=MagicMock())
    report = runner.run(themes=["T"], date="2026-06-18", deep_analyze=False)
    assert "未筛选出符合条件" in report


def test_runner_degrades_when_llm_none(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_themes_file"] = str(themes_path)
    monkeypatch.setattr("tradingagents.policy_screener.expander.fetch_board_cons", lambda s: [("600584", "长电科技")])
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", _fake_metrics_stock)

    runner = PolicyScreenerRunner(cfg, llm=None)
    report = runner.run(themes=["T"], date="2026-06-18", deep_analyze=False)
    assert "长电科技" in report  # LLM 降级为中性分，仍能产出报告


def test_runner_deep_analyze_calls_propagate(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_deep_analyze_top"] = 1
    cfg["policy_themes_file"] = str(themes_path)
    monkeypatch.setattr("tradingagents.policy_screener.expander.fetch_board_cons", lambda s: [("600584", "长电科技")])
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", _fake_metrics_stock)
    monkeypatch.setattr("tradingagents.policy_screener.runner.qualify", _fake_qualify)

    fake_graph = MagicMock()
    fake_graph.propagate.return_value = (None, "建议建仓 5%。")

    runner = PolicyScreenerRunner(cfg, llm=MagicMock(), graph=fake_graph)
    report = runner.run(themes=["T"], date="2026-06-18", deep_analyze=True)
    assert "建议建仓" in report
    fake_graph.propagate.assert_called()


def test_runner_deep_analyze_failure_isolated(tmp_path, monkeypatch):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n",
        encoding="utf-8",
    )
    cfg = _cfg()
    cfg["policy_deep_analyze_top"] = 1
    cfg["policy_themes_file"] = str(themes_path)
    monkeypatch.setattr("tradingagents.policy_screener.expander.fetch_board_cons", lambda s: [("600584", "长电科技")])
    monkeypatch.setattr("tradingagents.policy_screener.runner.fetch_metrics", _fake_metrics_stock)
    monkeypatch.setattr("tradingagents.policy_screener.runner.qualify", _fake_qualify)

    fake_graph = MagicMock()
    fake_graph.propagate.side_effect = RuntimeError("boom")

    runner = PolicyScreenerRunner(cfg, llm=MagicMock(), graph=fake_graph)
    report = runner.run(themes=["T"], date="2026-06-18", deep_analyze=True)
    # 推荐池仍在，深度分析标记失败
    assert "长电科技" in report
    assert "深度分析失败" in report
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/policy_screener/test_runner.py -v`
Expected: FAIL（`ModuleNotFoundError: ... runner`）

- [ ] **Step 3: 实现 runner.py**

Create `tradingagents/policy_screener/runner.py`:

```python
"""编排器：串起展开 → 打分 → 排序 → (深度分析) → 报告。

外部依赖（akshare/LLM/propagate）通过模块级函数引用，
测试可用 monkeypatch 替换。本模块不直接 import akshare。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .expander import expand_themes
# 从子模块引用 fetch_metrics / qualify，便于测试 monkeypatch 替换
from .fund_flow_scorer import fetch_metrics, score_metrics
from .llm_qualifier import qualify
from .models import Candidate, ScoredCandidate
from .ranker import rank_candidates
from .reporter import render_report
from .themes import load_themes

logger = logging.getLogger(__name__)


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
        candidates = expand_themes(theme_cfg)
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/policy_screener/test_runner.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add tradingagents/policy_screener/runner.py tests/policy_screener/test_runner.py
git commit -m "feat(policy-screener): orchestrator with deep-analysis and degradation"
```

---

## Task 11: Python 入口 policy_main.py

根目录入口，仿 `fund_main.py` 风格：配置 LLM → 构造 runner → 打印报告 → 写入 reports/。

**Files:**
- Create: `policy_main.py`

- [ ] **Step 1: 实现入口脚本**

Create `policy_main.py`:

```python
"""
政策扶持标的推荐筛选器入口
按"国家政策扶持 + 主力资金未介入"筛选 A 股股票与基金/ETF，
输出 Markdown 推荐池报告，可选对 Top 标的跑多 Agent 深度配置建议。

运行示例：
    python policy_main.py
    python policy_main.py --themes 新质生产力,低空经济 --date 2026-06-18 --deep

使用前请确保：
1. 安装 akshare：pip install akshare
2. 配置 LLM API Key（见 .env.example）
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.policy_screener.runner import PolicyScreenerRunner


def _build_llm(config: dict):
    """按 config 构造 LLM；未配置 API Key 时返回 None（降级为纯量化）。"""
    try:
        from tradingagents.llm_clients.factory import create_llm_client
        provider = config["llm_provider"]
        model = config["quick_think_llm"]
        client = create_llm_client(provider, model, config.get("backend_url"))
        return client.get_llm()
    except Exception as e:
        print(f"[warn] LLM 初始化失败，将仅使用量化打分: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="政策扶持标的推荐筛选器")
    parser.add_argument("--themes", type=str, default="",
                        help="主题名，逗号分隔，如 '新质生产力,低空经济'；留空启用全部")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"),
                        help="分析日期 yyyy-mm-dd")
    parser.add_argument("--deep", action="store_true",
                        help="对 Top N 跑多 Agent 深度配置建议（需 API Key）")
    parser.add_argument("--out", type=str, default=None,
                        help="报告输出路径，默认 reports/policy_<date>.md")
    args = parser.parse_args()

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = os.environ.get("TRADINGAGENTS_LLM_PROVIDER", "deepseek")
    config["deep_think_llm"] = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", "deepseek-reasoner")
    config["quick_think_llm"] = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", "deepseek-chat")
    config["output_language"] = "Chinese"

    themes = [t.strip() for t in args.themes.split(",") if t.strip()]

    llm = _build_llm(config)
    graph = None
    if args.deep and llm is not None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            debug=True, config=config,
        )

    runner = PolicyScreenerRunner(config, llm=llm, graph=graph)
    report = runner.run(themes=themes, date=args.date, deep_analyze=args.deep)

    out_path = args.out or os.path.join("reports", f"policy_{args.date}.md")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\n报告已保存至 {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 冒烟测试 — 验证脚本可导入且 --help 正常**

Run: `python policy_main.py --help`
Expected: 打印 argparse 帮助文本（不报 ImportError）

- [ ] **Step 3: 提交**

```bash
git add policy_main.py
git commit -m "feat(policy-screener): python entry point policy_main.py"
```

---

## Task 12: __init__.py 导出公开 API

让 `from tradingagents.policy_screener import PolicyScreenerRunner` 可用。

**Files:**
- Modify: `tradingagents/policy_screener/__init__.py`

- [ ] **Step 1: 实现**

Replace contents of `tradingagents/policy_screener/__init__.py` with:

```python
"""政策扶持标的推荐筛选器子包。

公开 API：
    PolicyScreenerRunner — 编排筛选全流程并产出 Markdown 报告
"""

from .runner import PolicyScreenerRunner

__all__ = ["PolicyScreenerRunner"]
```

- [ ] **Step 2: 验证导入**

Run: `python -c "from tradingagents.policy_screener import PolicyScreenerRunner; print('OK')"`
Expected: 打印 `OK`

- [ ] **Step 3: 全量回归测试**

Run: `pytest tests/policy_screener/ -v`
Expected: 全部通过（前述各任务测试合计约 50+ 用例）

- [ ] **Step 4: 提交**

```bash
git add tradingagents/policy_screener/__init__.py
git commit -m "feat(policy-screener): export public API from package init"
```

---

## Task 13: CLI 子命令 cli/policy.py

在 CLI 中新增 `policy-recommend` 子命令。沿用项目 questionary 风格做主题选择。

**Files:**
- Create: `cli/policy.py`
- Test: `tests/test_cli_policy.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_cli_policy.py`:

```python
from unittest.mock import patch

from cli.policy import run_policy_recommend


def test_run_policy_recommend_invokes_runner(tmp_path, capsys):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n", encoding="utf-8",
    )

    with patch("cli.policy.PolicyScreenerRunner") as MockRunner, \
         patch("cli.policy._build_llm", return_value=None), \
         patch("cli.policy.load_themes") as mock_load:
        instance = MockRunner.return_value
        instance.run.return_value = "# 报告"

        run_policy_recommend(
            themes=["T"], date="2026-06-18", deep=False,
            config_overrides={"policy_themes_file": str(themes_path)},
        )

        instance.run.assert_called_once()
        out = capsys.readouterr().out
        assert "报告" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_cli_policy.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'cli.policy'`）

- [ ] **Step 3: 实现 cli/policy.py**

Create `cli/policy.py`:

```python
"""政策扶持标的推荐筛选器 CLI 子命令。

通过函数入口 run_policy_recommend 暴露，便于测试与被 cli/main.py 集成。
"""

from __future__ import annotations

from typing import List, Optional

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.policy_screener.runner import PolicyScreenerRunner


def _build_llm(config: dict):
    """按 config 构造 LLM；失败返回 None。"""
    try:
        from tradingagents.llm_clients.factory import create_llm_client
        provider = config["llm_provider"]
        model = config["quick_think_llm"]
        client = create_llm_client(provider, model, config.get("backend_url"))
        return client.get_llm()
    except Exception:
        return None


def run_policy_recommend(
    themes: List[str],
    date: str,
    deep: bool = False,
    config_overrides: Optional[dict] = None,
) -> str:
    """运行政策推荐筛选，打印报告并返回报告文本。"""
    config = DEFAULT_CONFIG.copy()
    config["output_language"] = "Chinese"
    if config_overrides:
        config.update(config_overrides)

    llm = _build_llm(config)
    graph = None
    if deep and llm is not None:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            debug=True, config=config,
        )

    runner = PolicyScreenerRunner(config, llm=llm, graph=graph)
    report = runner.run(themes=themes, date=date, deep_analyze=deep)
    print(report)
    return report
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_cli_policy.py -v`
Expected: 1 passed

- [ ] **Step 5: 提交**

```bash
git add cli/policy.py tests/test_cli_policy.py
git commit -m "feat(policy-screener): CLI entry run_policy_recommend"
```

---

## Task 14: README 使用说明

在 README.md 追加"政策推荐筛选器"使用说明小节，与现有"基金分析"小节风格一致。

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 追加使用说明**

在 `README.md` 中找到基金分析示例代码块之后的位置，追加：

```markdown
## 政策扶持标的推荐筛选器

按"国家政策大力扶持 + 主力资金尚未大规模介入"筛选 A 股股票与基金/ETF，输出 Markdown 推荐池，并可对 Top 标的跑多 Agent 深度配置建议。

### 快速开始

```bash
# 仅量化筛选（无需 API Key）
python policy_main.py --themes 新质生产力,低空经济 --date 2026-06-18

# 含 Top 3 深度配置建议（需 LLM API Key）
python policy_main.py --themes 新质生产力 --deep
```

报告输出至 `reports/policy_<date>.md`。

### 主题与阈值

- 主题映射表：`tradingagents/policy_screener/data/policy_themes.yaml`（可自行增删主题、板块、基金代码）
- "主力未介入"阈值与打分权重：见 `tradingagents/default_config.py` 的 `policy_*` 配置项，可通过环境变量覆盖 `TRADINGAGENTS_POLICY_LOOKBACK_DAYS` 等

> ⚠️ 本工具仅供研究学习，不构成投资建议。
```

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: add policy screener usage to README"
```

---

## 完工验收

- [ ] **Step 1: 全量测试**

Run: `pytest tests/policy_screener/ tests/test_cli_policy.py tests/policy_screener/test_config.py -v`
Expected: 全部通过

- [ ] **Step 2: 冒烟运行（可选，需 akshare 联网）**

Run: `python policy_main.py --themes 新质生产力 --date 2026-06-18`
Expected: 生成 `reports/policy_2026-06-18.md`，含筛选条件与（可能为空的）推荐池表格。若 akshare 被限流，应看到降级提示而非崩溃。

- [ ] **Step 3: 提交（若 README 外有遗留改动）**

```bash
git status
# 若有未提交改动：
git add -A
git commit -m "chore(policy-screener): finalize"
```

---

## Self-Review 记录

**Spec 覆盖核对**：
- §3 约束表 → Task 1（配置项）、Task 3（映射表）✓
- §4 模块结构 → Task 2–10 各模块一一对应 ✓
- §5 数据结构 → Task 2 models.py（Candidate/ScoredCandidate/FundFlowMetrics）✓
- §6 打分逻辑 → Task 5（纯打分）+ Task 6（akshare 拉取）✓
- §6.4 阈值判定 → Task 5 passes_threshold ✓
- §7 配置 → Task 1 ✓
- §8 错误处理 → Task 6（akshare 降级）、Task 7（LLM 降级）、Task 10（深度分析隔离）、Task 3（映射表硬依赖）✓
- §9 测试 → 各任务均含对应测试 ✓
- §10 入口 → Task 11（Python）、Task 13（CLI）✓
- §11 依赖 → 无新依赖（pyyaml/akshare/langchain 均已有）✓

**Placeholder 扫描**：无 TBD/TODO；每步含完整代码与命令。✓

**类型一致性**：`fetch_metrics(ticker, end_date, lookback, is_fund)` 签名在 Task 6 定义、Task 10 runner 调用一致；`qualify(candidate, llm)` 在 Task 7 定义、Task 10 调用一致；`rank_candidates(scored, thresholds, weights, top_n)` 在 Task 8 定义、Task 10 调用一致；`render_report(ranked, themes, date, deep_results)` 在 Task 9 定义、Task 10 调用一致。✓

**已知偏差（已合理处理）**：spec §6.3 基金"份额变化率"因 akshare 无单只 ETF 份额历史接口，降级为日线涨幅+换手率代理（Task 6 `_fetch_fund_metrics`）；share_change_ratio 字段保留但常为 None，打分纯函数对缺失指标跳过（Task 5）。
