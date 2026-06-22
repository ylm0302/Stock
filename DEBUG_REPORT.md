# 推荐板块功能诊断报告

## 执行日期
2026-06-22

## 问题描述
用户反馈："推荐板块无法正常执行"

## Phase 1: 根本原因调查（已完成）

### 问题 1: 编码错误（已修复 ✅）
**症状**：日志中显示 `UnicodeEncodeError: 'ascii' codec can't encode characters`
**根本原因**：在 HTTP 请求头构建阶段，httpx 库在某些 locale 设置下使用 ASCII 编码而非 UTF-8
**修复状态**：✅ 已通过以下方式修复：
- webapp.py 第13-22行：全局 locale 初始化
- news_hotspot.py 第146-158行：局部 locale 防护
- 诊断验证：当前环境 locale 正确设置为 UTF-8

### 问题 2: 配置字段名不匹配（需要修复 ❌）
**症状**：`KeyError: 'policy_themes_file'`
**根本原因**：
- webapp.py 在第1112行：`config = DEFAULT_CONFIG.copy()` ✅ 正确
- 但 profile 存储的 config 字段名与 runner.py 期望的字段名不一致：
  - profile 使用：`shallow_thinker` / `deep_thinker`
  - runner.py 期望：`quick_think_llm` / `deep_think_llm`
- 当从 profile 加载配置时，没有进行字段名映射

**影响范围**：
- `run_auto()` 方法第211行期望的 `policy_themes_file` 存在于 DEFAULT_CONFIG 中
- 但当直接使用 profile 的 config 时会丢失

### 问题 3: akshare 库兼容性（需要修复 ❌）
**症状**：`module 'akshare' has no attribute 'stock_zh_a_alerts_cls'`
**根本原因**：
- news_hotspot.py 第81行调用了 akshare 库的 `stock_zh_a_alerts` 方法
- 当前 akshare 版本不包含 `stock_zh_a_alerts_cls` 这个属性
- 可能是版本升级导致 API 变更

**验证**：
```bash
python3 -c "import akshare; print(dir(akshare))" | grep -i alert
```

## Phase 2: 模式分析

### 工作流程追踪
1. webapp.py 接收 POST 请求 → 从 profile 加载 config
2. config 传递给 build_llm() → runner.py 期望特定的字段名
3. PolicyScreenerRunner.run_auto() → 需要 DEFAULT_CONFIG 中的字段
4. news_hotspot.fetch_cn_hotspot_news() → 调用 akshare

### 相关文件
- `/Users/mac/Desktop/TradingAgents/webapp.py` - 配置加载和 API 创建
- `/Users/mac/Desktop/TradingAgents/tradingagents/policy_screener/runner.py` - 主流程
- `/Users/mac/Desktop/TradingAgents/tradingagents/policy_screener/news_hotspot.py` - 新闻获取
- `/Users/mac/Desktop/TradingAgents/tradingagents/default_config.py` - 默认配置
- `~/.tradingagents/profiles.json` - 用户保存的配置

## Phase 3: 修复计划

### 优先级顺序

#### 优先级 1（关键）：修复 akshare 兼容性问题
- 检查当前 akshare 版本的 API
- 更新调用方式或回退到兼容的版本

#### 优先级 2（重要）：修复配置字段名映射
- 在 webapp.py 中统一配置字段名
- 或在 profile 加载时进行字段映射

#### 优先级 3（可选）：改进错误处理
- 当 akshare 不可用时的优雅降级
- 更详细的错误日志

## 验证步骤
1. ✅ LLM 调用成功（编码修复有效）
2. ❌ run_auto() 因配置字段丢失而失败
3. ❌ akshare 调用失败

## 下一步
建议按优先级进行修复。最关键的是解决 akshare 兼容性问题和配置字段映射。
