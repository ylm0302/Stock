# 配置方案（Profiles）设计

> 允许用户在页面上配置并保存多套完整的 API 分析环境（provider、URL、API Key、模型、运行参数），一键切换。持久化到服务端 JSON 文件。

## 背景

当前项目支持 11 个 LLM 提供商，但配置散落在两处：

- `.env` 文件 — 存 API Key
- 页面表单 — 仅 provider / 模型 / 深度等，不存 `backend_url` 也不存 API Key

每次切换环境（例如从 DeepSeek 换到 Azure OpenAI）都要手动改多处，且无法保存多套配置。

## 目标

- 一个「配置方案」= 一套完整的分析环境（所有配置字段）
- 可保存多个方案，在页面上一键切换
- 配置持久化到服务端，跨浏览器可用
- 不破坏现有 `.env` 兼容逻辑

## 非目标

- 不做多用户隔离（本地单用户工具）
- 不做 API Key 加密（与 `.env` 同等安全级别）
- 不修改 `.env` 文件（避免两套配置源冲突）
- 不做配置导入/导出（v1 范围外）

## 架构

### 数据文件

路径：`~/.tradingagents/profiles.json`

```json
{
  "profiles": [
    {
      "name": "家用 DeepSeek",
      "created_at": 1706000000.0,
      "updated_at": 1706000000.0,
      "config": {
        "llm_provider": "deepseek",
        "backend_url": "https://api.deepseek.com",
        "api_key": "sk-xxxx",
        "shallow_thinker": "deepseek-chat",
        "deep_thinker": "deepseek-reasoner",
        "output_language": "Chinese",
        "research_depth": 1,
        "checkpoint": false,
        "asset_type": "stock"
      }
    }
  ],
  "active": "家用 DeepSeek"
}
```

字段说明：

- `name` — 方案唯一标识，非空字符串。前端做重名校验（重名时走"覆盖"路径）
- `config` — 完整配置快照，包含 provider / backend_url / api_key / 两个模型 / 语言 / 深度 / checkpoint / 资产类型
- `active` — 当前激活的方案名；页面启动时自动加载此方案到表单。若该方案被删除，自动回退到第一个剩余方案；若列表为空则设为 `null`

### 后端 API（`webapp.py` 新增）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/profiles` | 返回 `{ "profiles": [...], "active": "..." }`。API Key 在返回时 mask 为 `sk-••••42e3`（前3后4字符） |
| `POST` | `/api/profiles` | 新建或更新方案。Body: `{ "name": "...", "config": {...} }`。`name` 已存在则覆盖 `config` 并更新 `updated_at`；否则新建 |
| `DELETE` | `/api/profiles?name=xxx` | 删除指定方案。若删除的是 `active`，自动将 `active` 设为第一个剩余方案名（或 `null`） |
| `POST` | `/api/profiles/activate` | 设置激活方案。Body: `{ "name": "..." }`。可选接口，前端切换下拉时调用 |

### 存储路径决策

使用 `~/.tradingagents/`（与现有 `results_dir`、`memory_log_path` 同目录），通过 `Path.home() / ".tradingagents" / "profiles.json"` 解析。首次写入时若目录不存在则创建。

## 前端 UI 设计

### 方案 A：内嵌下拉式

在左侧「分析配置」面板**顶部**插入「📁 配置方案」区块（蓝色高亮边框，与下方配置表单区分）：

```
┌─────────────────────────────────┐
│ 📁 配置方案              已保存 3│
│ ┌─────────────────────────────┐ │
│ │ 🏠 家用 DeepSeek       💾➕🗑│ │
│ └─────────────────────────────┘ │
│ 🔌 deepseek · 🔑 sk-••••42e3 · 🧠 reasoner │
└─────────────────────────────────┘
```

**组件：**
- **下拉选择器** — 列出所有方案名。前缀 emoji 按名称关键字自动推断：含"家"→🏠、含"公司"/"工作"→🏢、含"本地"/"ollama"→🔬、其余→⭐
- **💾 保存按钮** — 把表单当前值覆盖回下拉选中的方案（调用 `POST /api/profiles`）
- **➕ 另存为** — `prompt()` 输入新方案名 → 新建；名字已存在则 `confirm()` 确认覆盖
- **🗑 删除** — `confirm()` 二次确认 → 调用 `DELETE /api/profiles`，删除后自动切到第一个剩余方案
- **预览小字条** — 下拉下方一行小字，显示 `🔌 provider · 🔑 mask · 🧠 模型`，方便快速识别

### 新增表单字段

- `API 接入地址`（backend_url）— 文本输入框，placeholder `https://...`
- `API Key` — 默认 password 模式，右侧 👁 切换明文。placeholder 按 provider 变化（如 `sk-...` / `key-...`）

### 状态提示

- **未保存改动** — 表单字段与当前方案 `config` 不一致时，💾 按钮高亮脉动（CSS `animation: pulse`）
- **空态** — 若方案列表为空，整个区块替换为「➕ 保存当前为新方案」单一引导按钮
- **启动加载** — 页面 `mounted` 时调用 `GET /api/profiles`，把 `active` 对应方案的 `config` 填充到表单
- **切换方案** — 下拉 `change` 事件：前端确认是否丢弃未保存改动（`confirm()`），然后填充表单；同时调用 `POST /api/profiles/activate` 更新 `active`

### 提交分析时的行为

`POST /api/run` 时：

1. 若请求带 `profile` 字段（方案名），后端从 `profiles.json` 读取该方案的完整 `config`，**覆盖** payload 中对应字段
2. 若方案含 `api_key`，按 provider 类型写入 `os.environ` 中对应变量（`DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / 等），下一个 job 会再次覆盖
3. 若请求不带 `profile`，沿用现有逻辑（`.env` 或 payload 字段）

前端在 `startAnalysis` 中带 `profile: form.activeProfile || null`。若当前无任何激活方案（列表为空或 `active` 为 `null`），则不带 `profile` 字段，沿用现有 `.env` 逻辑。

## API Key 注入

运行时注入，避免持久化到 `os.environ` 污染其他任务：

```python
KEY_ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "glm": "ZHIPUAI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "azure": ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"),
    "ollama": None,  # 本地运行，无需 key
}
```

在 `run_analysis_job` 开始处，临时写入 `os.environ`（进程全局，但每个 job 在独立线程中运行且 LLM client 在 `TradingAgentsGraph` 实例化时读取，因此下一个 job 会再次用自己的 key 覆盖，不会串号）。分析结束后**不主动清理**，理由：(1) 清理会影响同进程内的其他正在初始化的 client；(2) 下一次分析会用自己的 key 覆盖。

## 错误处理

| 场景 | 处理 |
|------|------|
| `profiles.json` 不存在 | 返回空列表；前端显示空态引导 |
| JSON 格式损坏 | 后端 log 警告，返回空列表；前端 toast「配置加载失败，请检查 profiles.json」 |
| 写入失败（磁盘满/权限） | 返回 HTTP 500 + 错误信息；前端 toast 显示；不丢弃用户当前表单数据 |
| 方案名冲突（POST 时） | 服务端直接覆盖（upsert 语义）；前端在「另存为」路径用 `confirm()` 让用户确认 |
| 删除激活方案 | 自动 fallback 到第一个剩余方案；若无剩余则 `active = null` |

## 安全注意事项

- API Key 明文存 JSON 文件，与 `.env` 同等安全级别
- 服务端 `GET /api/profiles` 返回列表时 mask key（前3后4字符），防止页面源码泄露
- 真值只在执行分析的线程内读取，通过环境变量注入到 LLM client
- 建议用户执行 `chmod 600 ~/.tradingagents/profiles.json`（在页面帮助文案中提示）

## 与 `.env` 的优先级

1. 若分析请求带 `profile` 且该方案含 `api_key` → 使用方案中的 key（临时注入）
2. 否则回退到 `.env` 或系统环境变量（维持现状）
3. `backend_url` / 模型 / 深度等字段同理：profile 优先，缺失则用请求 payload 字段，再缺失用 `DEFAULT_CONFIG`

## 测试要点

- 首次启动：`profiles.json` 不存在 → 页面正常加载，显示空态
- 新建 → 保存 → 刷新页面 → 方案仍在
- 切换方案 → 表单字段全部正确填充
- 修改表单后 💾 保存 → `profiles.json` 中 `updated_at` 更新
- 删除激活方案 → `active` 自动切到第一个剩余方案
- 删除最后一个方案 → `active = null`，显示空态
- API Key mask：GET 返回的 key 形如 `sk-••••42e3`，不含明文
- 提交分析时带 `profile` → 后端从文件读取真值并注入环境变量
- `.env` 回退：不带 profile 时，原有逻辑正常工作

## 影响范围

### 改动文件

- `webapp.py` — 新增 4 个 API 端点 + `sanitize_payload` 增加 profile 解析 + `run_analysis_job` 增加 key 注入
- `cli/static/frontend.html` — 在配置面板顶部插入方案选择器区块；新增 API Key 和 backend_url 输入框
- `cli/static/app.js` — 新增 profiles 数据、加载/保存/删除/激活方法、表单改动检测、提交时带 profile
- `cli/static/style.css` — 💾 按钮脉动动画

### 不动

- `tradingagents/default_config.py`
- `tradingagents/llm_clients/*`
- `.env` 解析逻辑
- CLI (`cli/main.py`)
