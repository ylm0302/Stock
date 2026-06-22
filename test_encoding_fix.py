#!/usr/bin/env python3
"""验证编码修复是否生效"""
import subprocess
import sys

print("=" * 70)
print("测试编码修复")
print("=" * 70)
print()

# 测试 1: 检查 webapp.py 的编码初始化
print("测试 1: 检查 webapp.py 编码初始化代码")
print("-" * 70)
with open("webapp.py", "r", encoding="utf-8") as f:
    content = f.read()
    if "locale.setlocale" in content:
        print("✅ webapp.py 已包含 locale 设置")
    else:
        print("❌ webapp.py 缺少 locale 设置")

    if "PYTHONIOENCODING" in content:
        print("✅ webapp.py 已设置 PYTHONIOENCODING")
    else:
        print("❌ webapp.py 缺少 PYTHONIOENCODING")
print()

# 测试 2: 检查 news_hotspot.py 的增强错误处理
print("测试 2: 检查 news_hotspot.py 增强错误处理")
print("-" * 70)
with open("tradingagents/policy_screener/news_hotspot.py", "r", encoding="utf-8") as f:
    content = f.read()
    if "locale.setlocale" in content:
        print("✅ news_hotspot.py 已包含 locale 设置")
    else:
        print("❌ news_hotspot.py 缺少 locale 设置")

    if "诊断信息" in content:
        print("✅ news_hotspot.py 已包含详细诊断")
    else:
        print("❌ news_hotspot.py 缺少详细诊断")
print()

# 测试 3: Python 环境编码
print("测试 3: 当前 Python 环境编码")
print("-" * 70)
result = subprocess.run(
    [sys.executable, "-c",
     "import sys, locale; "
     "print(f'stdout: {sys.stdout.encoding}'); "
     "print(f'stderr: {sys.stderr.encoding}'); "
     "print(f'locale: {locale.getpreferredencoding()}')"],
    capture_output=True,
    text=True
)
print(result.stdout)
print()

print("=" * 70)
print("修复总结")
print("=" * 70)
print("""
已应用的修复：

1. webapp.py 启动时设置 UTF-8 locale
   - 调用 locale.setlocale(LC_ALL, 'en_US.UTF-8')
   - 防止 HTTP 客户端库使用 ASCII

2. news_hotspot.py LLM 调用前设置 locale
   - 双重防护，确保调用时环境正确

3. 增强的错误诊断
   - UnicodeEncodeError 时输出详细信息
   - 帮助定位具体哪个变量导致问题

4. webapp.py 的 SafeStreamHandler
   - 确保日志输出使用 UTF-8
   - logging.captureWarnings(True) 捕获 warnings 模块输出

建议下一步：
1. 重启 webapp.py
2. 再次触发热点推荐
3. 如果仍有错误，查看新的详细诊断信息
""")
