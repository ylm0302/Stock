# Stock

基于 **TradingAgents** 框架的多智能体 LLM 金融交易系统。通过多个 LLM Agent 协作（市场分析、情绪分析、新闻宏观、基本面），对**股票**和**基金**进行深度分析，并给出可操作的配置建议。

> ⚠️ 本工具仅供研究学习，不构成投资建议。投资有风险，决策需谨慎。

---

## 功能特性

- **股票分析**：支持美股（如 `NVDA`、`AAPL`）、A 股（如 `600519.SS` 贵州茅台）、港股、加密货币等
- **基金分析**：支持国内公募基金（如 `110022` 易方达消费、`000961` 天弘沪深 300）和 ETF
- **多 Agent 协作**：市场分析师、情绪分析师、新闻分析师、基本面分析师 + 多空辩论 + 风险讨论
- **多 LLM 提供商**：DeepSeek、OpenAI、Anthropic、Google、Qwen、GLM、MiniMax、OpenRouter、Azure、Ollama
- **三种使用方式**：Python API、交互式 CLI、Web 界面
- **多语言输出**：支持中文 / 英文分析报告

---

## 项目结构

```
TradingAgents/
├── tradingagents/        # 核心框架（agents、dataflows、graph、llm_clients）
├── cli/                  # 交互式命令行界面
├── main.py               # 股票分析入口
├── fund_main.py          # 基金分析入口
├── webapp.py             # Web 界面（HTTP + SSE 流式）
├── tests/                # 单元测试
├── reports/              # 历史分析报告输出
├── .env.example          # 环境变量模板
└── pyproject.toml        # 项目配置
```

---

## 环境准备

### 1. 克隆仓库

```bash
git clone git@github.com:ylm0302/Stock.git
cd Stock
```

### 2. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate    # Windows 用 .venv\Scripts\activate
```

### 3. 安装依赖

```bash
pip install -e .
```

或使用 uv（更快）：

```bash
uv sync
```

### 4. 配置 API Key

复制环境变量模板并按需填写：

```bash
cp .env.example .env
```

编辑 `.env`，至少填写一个 LLM 提供商的 API Key：

| 提供商 | 环境变量 | 说明 |
|--------|----------|------|
| DeepSeek | `DEEPSEEK_API_KEY` | 国内可用，价格低，推荐 |
| OpenAI | `OPENAI_API_KEY` | GPT 系列 |
| Anthropic | `ANTHROPIC_API_KEY` | Claude 系列 |
| Google | `GOOGLE_API_KEY` | Gemini 系列，有免费额度 |
| Qwen | `QWEN_API_KEY` | 通义千问 |
| GLM | `GLM_API_KEY` | 智谱 GLM |

---

## 使用方法

### 方式一：股票分析（脚本）

编辑 `main.py`，修改股票代码和日期：

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-reasoner"
config["quick_think_llm"] = "deepseek-chat"

ta = TradingAgentsGraph(debug=True, config=config)

# 美股
_, decision = ta.propagate("NVDA", "2024-05-10")
# A 股
_, decision = ta.propagate("600519.SS", "2025-01-15")   # 贵州茅台
_, decision = ta.propagate("000858.SZ", "2025-01-15")   # 五粮液

print(decision)
```

运行：

```bash
python main.py
```

### 方式二：基金分析

编辑 `fund_main.py`：

```python
FUND_CODE = "110022"           # 基金代码（6 位数字）
ANALYSIS_DATE = "2025-01-15"   # 分析日期
```

运行：

```bash
python fund_main.py
```

常用基金代码：

| 代码 | 名称 | 类型 |
|------|------|------|
| `110022` | 易方达消费行业股票 | 主动股票型 |
| `000001` | 华夏成长混合 | 混合型 |
| `161725` | 招商中证白酒指数 | 指数型 |
| `270002` | 广发稳增债券 | 债券型 |
| `000961` | 天弘沪深 300ETF 联接 A | 指数型 |

### 方式三：交互式 CLI

```bash
tradingagents
```

按提示选择股票代码、分析日期、LLM 提供商、分析深度等。

### 方式四：Web 界面

```bash
python webapp.py
```

浏览器访问提示的地址（默认 `http://localhost:8000`），支持 SSE 流式输出、配置 Profile 保存、历史记录查看。

---

## 配置参数

在 `main.py` / `fund_main.py` 中调整 `config`：

```python
config["max_debate_rounds"] = 2          # 多空辩论轮数（1-3，越多越深入）
config["max_risk_discuss_rounds"] = 2    # 风险讨论轮数
config["output_language"] = "Chinese"    # 报告语言（Chinese / English）
config["analyst_concurrency_limit"] = 1  # 分析师并发数（建议 1，避免限流）

# 基金专用
config["fund_benchmark_ticker"] = "510300.SS"  # 业绩基准（沪深 300ETF）
```

---

## 输出结果

### 股票模式

| 结果 | 含义 |
|------|------|
| **Buy** | 建议买入 |
| **Overweight** | 建议增持 |
| **Hold** | 建议持有 |
| **Underweight** | 建议减持 |
| **Sell** | 建议卖出 |

### 基金模式

| 结果 | 含义 |
|------|------|
| **积极配置（Buy）** | 强烈看好，建议大幅增加配置 |
| **标准配置（Overweight）** | 看好，建议适度增加配置 |
| **维持配置（Hold）** | 中性，维持当前仓位 |
| **谨慎配置（Underweight）** | 偏谨慎，建议适度降低配置 |
| **赎回（Sell）** | 不建议持有，建议赎回 |

---

## 分析报告

每次运行后，完整报告保存在：

```
~/.tradingagents/logs/<代码>/TradingAgentsStrategy_logs/full_states_log_<日期>.json
```

包含：市场走势、情绪分析、新闻宏观、基本面、多空辩论全文、风险讨论全文、最终决策。

---

## 常见问题

**Q: Yahoo Finance 限流报错？**
A: Agent 会自动重试 3 次，失败后使用已有知识继续分析，不影响最终结果。

**Q: 运行很慢？**
A: 将 `max_debate_rounds` 和 `max_risk_discuss_rounds` 设为 `1`，或把 `deep_think_llm` 改为 `deepseek-chat`（速度更快）。

**Q: 如何分析 ETF？**
A: 使用 `asset_type="fund"` 模式，代码填 ETF 的场外代码（如 `000961`）。

**Q: 批量分析多只基金？**
```python
funds = ["110022", "000961", "161725"]
for code in funds:
    _, decision = ta.propagate(code, "2025-01-15", asset_type="fund")
    print(f"{code}: {decision}")
```

---

## 许可

详见 [LICENSE](LICENSE)。
