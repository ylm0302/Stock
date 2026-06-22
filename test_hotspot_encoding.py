#!/usr/bin/env python3
"""测试热点推荐的编码问题排查脚本"""
import os
import sys
import logging

# 复制 webapp.py 的编码设置
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 设置 logging 捕获 warnings
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logging.captureWarnings(True)

print("=" * 60)
print("环境编码检查")
print("=" * 60)
print(f"sys.stdout.encoding: {sys.stdout.encoding}")
print(f"sys.stderr.encoding: {sys.stderr.encoding}")
print(f"PYTHONIOENCODING: {os.environ.get('PYTHONIOENCODING', '未设置')}")
print(f"PYTHONUTF8: {os.environ.get('PYTHONUTF8', '未设置')}")
print(f"locale: {os.environ.get('LC_ALL', '未设置')} / {os.environ.get('LANG', '未设置')}")
print()

# 测试中文输出
print("=" * 60)
print("测试 1: 直接打印中文")
print("=" * 60)
try:
    print("测试中文：算力、半导体、新能源车")
    print("✅ 直接打印成功")
except Exception as e:
    print(f"❌ 直接打印失败: {e}")
print()

# 测试 logging 输出中文
print("=" * 60)
print("测试 2: logging 输出中文")
print("=" * 60)
try:
    logging.info("测试中文日志：板块库共 31 个板块可供匹配")
    print("✅ logging 输出成功")
except Exception as e:
    print(f"❌ logging 输出失败: {e}")
print()

# 测试 warnings 输出中文
print("=" * 60)
print("测试 3: warnings 输出中文")
print("=" * 60)
try:
    import warnings
    warnings.warn("测试中文警告：板块名可能不匹配")
    print("✅ warnings 输出成功")
except Exception as e:
    print(f"❌ warnings 输出失败: {e}")
print()

# 测试 LLM 初始化
print("=" * 60)
print("测试 4: LLM 初始化（可能触发 warnings）")
print("=" * 60)
try:
    from tradingagents.policy_screener.runner import build_llm

    # 模拟配置
    llm_config = {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY"
    }

    llm = build_llm(llm_config)
    if llm:
        print(f"✅ LLM 初始化成功: {type(llm).__name__}")
    else:
        print("⚠️  LLM 返回 None（可能 API Key 未配置）")
except Exception as e:
    print(f"❌ LLM 初始化失败: {e}")
    import traceback
    traceback.print_exc()
print()

# 测试完整的热点分析流程
print("=" * 60)
print("测试 5: 完整热点分析流程")
print("=" * 60)
try:
    from tradingagents.policy_screener.news_hotspot import (
        fetch_cn_hotspot_news,
        extract_hotspots_with_llm,
    )
    from tradingagents.policy_screener.themes import load_themes

    # 获取板块列表
    themes = load_themes()
    all_boards = [b["name"] for t in themes for b in t.get("boards", [])]
    print(f"📊 加载板块: {len(all_boards)} 个")

    # 获取新闻
    news_text, source = fetch_cn_hotspot_news(limit=10)
    if news_text:
        print(f"📡 新闻获取成功: {source}")
        print(f"   新闻长度: {len(news_text)} 字符")
    else:
        print(f"⚠️  新闻获取失败: {source}")

    # 如果有 LLM，尝试分析
    if 'llm' in locals() and llm and news_text:
        print("🧠 开始 LLM 分析...")
        hotspots, reason = extract_hotspots_with_llm(news_text, llm, all_boards)
        print(f"   结果: {reason}")
        if hotspots:
            for h in hotspots:
                print(f"   - {h.get('theme', '?')}: {h.get('reason', '')}")
        print("✅ 完整流程执行成功")
    else:
        print("⚠️  跳过 LLM 分析（LLM 未初始化或新闻为空）")

except Exception as e:
    print(f"❌ 热点分析失败: {e}")
    import traceback
    traceback.print_exc()
print()

print("=" * 60)
print("测试完成")
print("=" * 60)
