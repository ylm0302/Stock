# 政策扶持标的推荐筛选器 — 设计文档

**日期**：2026-06-18
**状态**：待复审
**作者**：用户 + Claude

---

## 1. 目标

新增"政策扶持标的推荐筛选器"功能。在国家政策重点扶持的领域，筛选出**主力资金尚未大规模介入**的股票和基金，形成推荐池，并对 Top 标的跑现有多 Agent 分析输出配置建议。

---

## 2. 方案选择

**方案 A：独立筛选器 + 复用现有 Agent**（已选定）

- 新建 `tradingagents/policy_screener/` 子包，独立负责"筛选推荐"
- 对 Top N 候选，复用现有 `TradingAgentsGraph.propagate()` 出深度配置建议
- 入口：`policy_main.py`（根目录）+ CLI 子命令 `policy-recommend`
- 筛选与分析解耦，不污染现有数据流

---

## 3. 核心约束

| 约束 | 决策 |
|---|---|
| 政策主题来源 | 预置可编辑映射表 `policy_themes.yaml` |
| 资金面数据 | akshare 量化 + LLM 定性，双轨打分 |
| 主力未介入判定 | 可配置阈值（主力净流入/市值 ≤1%、涨幅 ≤15%、换手 ≤5%） |
| 输出形式 | Python 入口 + CLI + Markdown 报告 |
| 适用市场 | A 股 + 国内公募基金/ETF（akshare 数据范围） |

---

## 4. 模块结构

```
tradingagents/policy_screener/
├── __init__.py
├── themes.py              # 主题映射表加载/校验
├── expander.py            # [1] 主题 → 候选标的池
├── fund_flow_scorer.py    # [2] akshare 资金面量化打分
├── llm_qualifier.py       # [2] LLM 定性补充打分
├── ranker.py              # [3] 综合评分排序 → 推荐池
├── runner.py              # [4] 编排：串起 [1]→[4]，可选调用 propagate()
├── reporter.py            # [5] Markdown 报告生成
└── data/
    └── policy_themes.yaml # 预置主题映射表（可编辑）
```

入口文件：
- `policy_main.py`（根目录，仿 `main.py` 风格）
- `cli/` 新增 `policy` 子命令

### 4.1 各模块职责

**themes.py** — 加载、校验、解析 `policy_themes.yaml`。格式错误时明确报错退出。

**expander.py** — 给定主题名称列表，展开为候选标的池：
- 映射表 → 板块 → akshare 板块成分股 → 股票代码列表
- 映射表 → 基金代码列表（直接取）
- 输出：`List[Candidate]`（ticker + name + sector + is_fund）

**fund_flow_scorer.py** — 对每只股票/基金，拉取 akshare 资金面数据，输出 0–100 量化分：
- 股票：近 N 日主力净流入/流通市值、北向资金净流入、区间涨幅、日均换手率
- 基金：份额变化率、规模变化、折溢价率
- 纯函数：`score(metrics, thresholds) -> float`

**llm_qualifier.py** — 对候选标的，调用现有 LLM 客户端，以独立 prompt 从新闻/研报文本中推断"机构关注但未重仓""政策催化待落地"等定性信号，输出 0–100 定性分。与现有 `fund_news_analyst.py` 不同：它不生成报告，只输出结构化分数和一句话理由。若 LLM 不可用则降级为空分。

**ranker.py** — 加权合并两个分数，按阈值过滤并排序，输出 Top N 推荐池：
- 综合分 = 0.30 × 政策相关度 + 0.45 × 量化分 + 0.25 × LLM 定性分
- 过滤：不满足"主力未介入"阈值的标的剔除

**runner.py** — 编排流程：
1. 加载主题 → expander 展开候选池
2. fund_flow_scorer + llm_qualifier 并行打分
3. ranker 排序 → 推荐池
4. 对 Top K 调 `TradingAgentsGraph.propagate()` 出深度配置建议
5. reporter 生成 Markdown 报告

**reporter.py** — 纯函数，输入推荐池 + 深度分析结果，输出 Markdown 文本。

---

## 5. 数据结构

### 5.1 主题映射表 `policy_themes.yaml`

```yaml
# 政策主题 → 行业/板块 → 候选标的映射
# 用户可自行增删改
themes:
  新质生产力:
    keywords: ["半导体", "先进算力", "人工智能", "量子"]
    sectors: ["半导体", "AI算力"]
    funds: ["159995", "515050"]
  低空经济:
    keywords: ["低空经济", "eVTOL", "无人机"]
    sectors: ["低空经济"]
    funds: ["159357"]
  设备更新:
    keywords: ["设备更新", "大规模以旧换新", "工程机械"]
    sectors: ["工程机械", "通用设备"]
    funds: ["159766"]
```

### 5.2 候选标的

```python
@dataclass
class Candidate:
    ticker: str           # 代码，如 "600519.SS" 或 "159995"
    name: str             # 名称
    theme: str            # 所属政策主题
    is_fund: bool         # 基金 or 股票
    sector: str           # 行业板块
```

### 5.3 打分结果

```python
@dataclass
class ScoredCandidate(Candidate):
    relevance_score: float      # 政策相关度 0-100
    fund_flow_score: float      # 量化资金面分 0-100
    llm_qualitative_score: float # LLM 定性分 0-100
    composite_score: float      # 综合分
    metrics: dict               # 原始资金面指标，供报告展示
    reason: str                 # 一句话推荐理由
```

### 5.4 报告输出

```markdown
# 政策扶持标的推荐池 (YYYY-MM-DD)

## 筛选条件
- 主题：{用户指定的主题列表}
- 资金面：主力介入度低（净流入/市值 ≤1%，涨幅 ≤15%，换手 ≤5%）
- 数据源：akshare + LLM 双轨

## 推荐股票
| 代码 | 名称 | 主题 | 综合分 | 近10日主力净流入 | 区间涨幅 | 换手率 | 推荐理由 |
| ... |

## 推荐基金/ETF
| 代码 | 名称 | 主题 | 综合分 | 份额变化 | 规模 | 推荐理由 |

## 深度配置建议（Top 3）
### 600XXX.SS —— 综合分 82
（调用 TradingAgentsGraph 输出的配置建议）

### 159995 —— 综合分 78
...
```

---

## 6. 打分逻辑

### 6.1 三档加权

| 维度 | 权重 | 来源 | 高分含义 |
|---|---|---|---|
| 政策相关度 | 30% | 主题映射命中 | 命中主题得满分；多主题命中加分 |
| 资金面量化 | 45% | akshare | 主力未介入 → 高分（逆向信号） |
| LLM 定性 | 25% | 新闻/研报文本 | "机构调研增多但仓位低""政策催化待落地" |

### 6.2 量化指标（股票）

| 指标 | 来源 | 方向 |
|---|---|---|
| 近 N 日主力净流入 / 流通市值 | akshare stock_fund_flow | 越低分越高 |
| 近 N 日北向资金净流入 | akshare north_flow | 越低分越高 |
| 区间涨跌幅 | akshare 日线 | 越低分越高（未拉升） |
| 日均换手率 | akshare 日线 | 越低分越高（未过热） |

### 6.3 量化指标（基金/ETF）

| 指标 | 来源 | 方向 |
|---|---|---|
| 近 N 日份额变化率 | akshare fund_share | 越低分越高（未抢购） |
| 规模变化 | akshare fund_info | 适中分高 |
| 折溢价率 | akshare ETF | 折价分高 |

### 6.4 "主力未介入"判定（可配置阈值）

```python
"policy_thresholds": {
    "main_net_inflow_ratio": 0.01,   # 主力净流入/流通市值 ≤ 1%
    "price_gain_ratio": 0.15,        # 区间涨幅 ≤ 15%
    "turnover_rate": 0.05,           # 日均换手率 ≤ 5%
}
```

满足以上全部 → 标记为"主力尚未大举介入"，进入推荐池。

---

## 7. 配置

写入 `tradingagents/default_config.py`，可被 `.env` 覆盖：

```python
# 政策筛选器配置
"policy_themes_file": "tradingagents/policy_screener/data/policy_themes.yaml",
"policy_enabled_themes": [],           # 空列表 = 全部启用
"policy_lookback_days": 10,
"policy_top_n": 10,
"policy_deep_analyze_top": 3,         # 对前 N 个跑深度 Agent
"policy_thresholds": {
    "main_net_inflow_ratio": 0.01,
    "price_gain_ratio": 0.15,
    "turnover_rate": 0.05,
},
"policy_weights": {
    "relevance": 0.30,
    "fund_flow": 0.45,
    "llm_qualitative": 0.25,
},
```

---

## 8. 错误处理

逐层降级，确保筛选器不因单个数据失败而整体崩溃：

| 故障点 | 处理 |
|---|---|
| akshare 单只股票资金流拉取失败 | 跳过该标的，`log` 记录，继续其余 |
| akshare 整体不可用（限流/断网） | 降级：仅用 LLM 定性档打分，报告中标注"资金面数据缺失" |
| LLM 调用失败 | 降级：仅用量化分，LLM 档权重折算到量化档 |
| 主题映射表缺失/格式错 | 报错退出，提示用户检查 yaml（硬依赖） |
| 深度 Agent 对某 Top 标的分析失败 | 该标的跳过配置建议，报告中标注"深度分析失败"，不影响推荐池 |

---

## 9. 测试策略

TDD，先写测试再实现。测试文件：

```
tests/policy_screener/
├── test_themes.py          # 映射表加载、格式校验、缺字段报错
├── test_expander.py        # 主题 → 候选池（mock 板块成分）
├── test_fund_flow_scorer.py# 打分计算（喂构造数据，断言分数）
├── test_ranker.py          # 综合排序、阈值过滤
├── test_reporter.py        # Markdown 生成（快照/字段断言）
└── test_runner.py          # 端到端编排（全部 mock，验证流程串通）
```

- 资金流打分与排序是**纯函数**，可用构造数据精确断言
- akshare / LLM 在测试中全部 mock，不依赖网络
- 不引入新依赖

---

## 10. 入口示意

### Python API

```python
from tradingagents.policy_screener.runner import PolicyScreenerRunner

runner = PolicyScreenerRunner(config)
report = runner.run(
    themes=["新质生产力", "低空经济"],
    date="2026-06-18",
    deep_analyze=True,       # 是否对 Top 跑深度 Agent
)
print(report)
```

### CLI

```bash
python policy_main.py --themes 新质生产力,低空经济 --date 2026-06-18
# 或
tradingagents policy-recommend --themes 新质生产力
```

---

## 11. 依赖

- 复用 `akshare`（已在 requirements.txt）
- 复用现有 `TradingAgentsGraph`（深度分析）
- 复用现有 LLM 客户端（`tradingagents/llm_clients/`）
- 不引入新第三方依赖

---

## 12. 不在范围内的

- 实时盯盘/预警
- 历史回测
- 自动交易
- 港股/美股支持（akshare 数据范围限制）
- Web 界面（后续可加）