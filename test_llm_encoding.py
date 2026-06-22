#!/usr/bin/env python3
"""精确定位 LLM 调用中的编码错误"""
import os
import sys
import logging

# 先设置编码
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

# 重新配置 stdout/stderr
import io
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding='utf-8',
        errors='replace',
        line_buffering=True,
        write_through=True
    )
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer,
        encoding='utf-8',
        errors='replace',
        line_buffering=True,
        write_through=True
    )

# 设置 logging
logging.basicConfig(
    level=logging.DEBUG,  # 使用 DEBUG 级别查看更多信息
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logging.captureWarnings(True)

# 禁用 langchain 的详细日志，避免干扰
os.environ["LANGCHAIN_CACHE"] = ""
os.environ["LANGCHAIN_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

print("=" * 70)
print("测试 LLM 调用时的编码问题")
print("=" * 70)

# 检查 API Key
deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
if deepseek_key:
    print(f"✅ DEEPSEEK_API_KEY 已设置: {deepseek_key[:8]}...")
else:
    print("❌ DEEPSEEK_API_KEY 未设置")
    print("   请先设置环境变量: export DEEPSEEK_API_KEY='your-key'")
    sys.exit(1)

print()

# 测试 1: 创建 LLM 客户端
print("测试 1: 创建 LangChain LLM 客户端")
print("-" * 70)
try:
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model="deepseek-chat",
        openai_api_base="https://api.deepseek.com",
        openai_api_key=deepseek_key,
        temperature=0.3,
        max_tokens=1000,
    )
    print(f"✅ LLM 客户端创建成功: {type(llm).__name__}")
except Exception as e:
    print(f"❌ LLM 客户端创建失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# 测试 2: 调用 LLM（包含中文）
print("测试 2: 调用 LLM（包含中文 prompt）")
print("-" * 70)

test_prompt = """你是 A 股资深行业分析师。

任务：从以下新闻中识别 3 个热点板块。

新闻：
- 算力需求激增，AI 芯片供不应求
- 新能源车销量创新高
- 半导体国产化加速推进

请返回 JSON 数组：[{"theme":"板块名","reason":"原因"}]
"""

try:
    print("调用 llm.invoke()...")
    response = llm.invoke([
        ("system", "你是专业的 A 股分析师"),
        ("human", test_prompt),
    ])
    content = getattr(response, "content", str(response))
    print(f"✅ LLM 调用成功")
    print(f"   响应长度: {len(content)} 字符")
    print(f"   响应预览: {content[:200]}")
except UnicodeEncodeError as e:
    print(f"❌ 编码错误: {e}")
    print(f"   错误位置: position {e.start}-{e.end}")
    print(f"   问题字符: {repr(e.object[e.start:e.end])}")
    print(f"   使用的编码: {e.encoding}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"❌ LLM 调用失败: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 70)
print("测试完成")
print("=" * 70)
