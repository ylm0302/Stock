# LLM 调用编码错误修复报告

## 问题描述

**错误信息**：
```
ERR [🧠 热点] LLM 调用失败：'ascii' codec can't encode characters in position 10-13: ordinal not in range(128)
```

**触发场景**：热点推荐功能调用 LLM 分析财经新闻时，包含中文的 prompt 无法正确编码

## 根本原因

底层 HTTP 客户端库（如 httpx/requests）在某些环境下会从系统 `locale` 设置读取默认编码。当 locale 未正确设置为 UTF-8 时，这些库可能使用 ASCII 编码处理请求体，导致包含中文字符的内容触发 `UnicodeEncodeError`。

即使 Python 的 `sys.stdout.encoding` 和环境变量 `PYTHONIOENCODING` 已经设置为 UTF-8，底层库仍可能绕过这些设置直接读取 locale。

## 修复方案

### 1. webapp.py 全局 locale 初始化（根本性修复）

在文件开头、任何 import 之前设置 UTF-8 locale：

```python
import locale
try:
    # 尝试常见的 UTF-8 locale（按优先级排序）
    for loc in ['en_US.UTF-8', 'C.UTF-8', 'zh_CN.UTF-8', 'en_GB.UTF-8']:
        try:
            locale.setlocale(locale.LC_ALL, loc)
            break
        except locale.Error:
            continue
except Exception:
    pass  # locale 设置失败不影响启动，后续有其他防护
```

**位置**：[webapp.py:13-23](webapp.py#L13-L23)

### 2. news_hotspot.py 局部防护（双重保险）

在 LLM 调用前再次设置 locale，并在调用后恢复：

```python
import locale

old_locale = None
try:
    old_locale = locale.getlocale()
    for loc in ['en_US.UTF-8', 'C.UTF-8', 'zh_CN.UTF-8']:
        try:
            locale.setlocale(locale.LC_ALL, loc)
            break
        except locale.Error:
            continue
except Exception as e:
    logger.debug(f"设置 locale 失败（非致命）: {e}")

try:
    resp = llm.invoke([...])
finally:
    # 恢复原始 locale
    if old_locale is not None:
        try:
            locale.setlocale(locale.LC_ALL, old_locale)
        except Exception:
            pass
```

**位置**：[tradingagents/policy_screener/news_hotspot.py:130-167](tradingagents/policy_screener/news_hotspot.py#L130-L167)

### 3. 增强的错误诊断

如果仍然出现 `UnicodeEncodeError`，现在会输出：

- 错误类型、编码方式、错误位置
- 问题字符的上下文（前后10个字符）
- 完整的 traceback
- 各个变量的 UTF-8 编码测试结果

**位置**：[tradingagents/policy_screener/news_hotspot.py:179-215](tradingagents/policy_screener/news_hotspot.py#L179-L215)

### 4. 已有的防护措施（保留）

- `sys.stdout/stderr` 强制使用 UTF-8
- 环境变量 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`
- SafeStreamHandler 确保日志 UTF-8 输出
- `logging.captureWarnings(True)` 捕获 warnings 模块输出

## 验证结果

✅ webapp.py 已包含 locale 设置  
✅ news_hotspot.py 已包含 locale 设置  
✅ news_hotspot.py 已包含详细诊断  
✅ 当前 Python 环境编码: stdout=utf-8, stderr=utf-8, locale=UTF-8  
✅ webapp 已重启（进程 ID: 72781）  
✅ 服务正常监听在 http://127.0.0.1:8000

## 下一步测试

1. 访问 webapp 界面
2. 触发热点推荐功能
3. 观察日志输出：
   - 如果成功：应该能看到 LLM 识别的热点板块
   - 如果仍失败：新的诊断日志会提供详细错误信息

## 相关文件修改

- [webapp.py](webapp.py) - 添加全局 locale 初始化
- [tradingagents/policy_screener/news_hotspot.py](tradingagents/policy_screener/news_hotspot.py) - 添加局部 locale 防护 + 增强诊断
- [test_encoding_fix.py](test_encoding_fix.py) - 验证脚本

## 技术细节

### 为什么需要设置 locale？

Python 的编码设置分为多个层次：

1. **sys.stdout.encoding** - Python 标准输出流的编码
2. **环境变量** - `PYTHONIOENCODING`, `PYTHONUTF8`
3. **locale** - 系统级别的区域设置

某些底层库（特别是 C 扩展）会直接读取 locale，而不是 Python 的编码设置。这就是为什么即使设置了前两者，仍需要正确配置 locale。

### 为什么选择这些 locale？

- `en_US.UTF-8` - 最通用的 UTF-8 locale
- `C.UTF-8` - 轻量级 UTF-8 locale，不依赖特定语言
- `zh_CN.UTF-8` - 中文环境的 UTF-8 locale
- `en_GB.UTF-8` - 英国英语 UTF-8 locale（备选）

按优先级尝试，只要有一个成功即可。

### 为什么在两个地方都设置？

- **webapp.py 全局设置**：确保整个应用启动时就使用 UTF-8
- **news_hotspot.py 局部设置**：双重保险，防止其他代码修改了 locale

这种多层防护策略确保在各种运行环境下都能正常工作。
