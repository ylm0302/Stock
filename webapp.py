#!/usr/bin/env python3
# 强制在任何 import 之前设置 UTF-8 编码，避免中文日志触发 ascii 编码错误
import os
import sys

# 设置环境变量，影响子进程和部分库的编码行为
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

# 强制设置 UTF-8 locale，防止 HTTP 客户端库（httpx/requests）使用 ASCII
# 这是根本性修复：许多底层库会从 locale 读取默认编码
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

# 强制 stdout/stderr 使用 UTF-8（Python 3.7+ 支持）
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

# 如果 reconfigure 不生效或不支持，直接替换为 UTF-8 文本包装器
import io
if not hasattr(sys.stdout, 'reconfigure') or sys.stdout.encoding.lower() != 'utf-8':
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding='utf-8',
            errors='replace',
            line_buffering=True,
            write_through=True
        )
if not hasattr(sys.stderr, 'reconfigure') or sys.stderr.encoding.lower() != 'utf-8':
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer,
            encoding='utf-8',
            errors='replace',
            line_buffering=True,
            write_through=True
        )

import argparse
import json
import logging
import queue
import re
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# ── 在所有业务 import 之前安装 UTF-8 安全 logging handler ────────────
def _install_safe_logging():
    """安装自定义 SafeStreamHandler，写入前强制 UTF-8 编码。

    必须在任何业务模块 import 前调用，否则其他模块触发的 basicConfig 可能
    先注册了 ascii StreamHandler，导致中文日志报 UnicodeEncodeError。
    """
    class SafeStreamHandler(logging.StreamHandler):
        def emit(self, record):
            try:
                msg = self.format(record)
                if hasattr(self.stream, "buffer"):
                    self.stream.buffer.write(
                        (msg + self.terminator).encode("utf-8", errors="replace")
                    )
                    self.stream.buffer.flush()
                else:
                    self.stream.write(
                        msg.encode("utf-8", errors="replace").decode("utf-8")
                        + self.terminator
                    )
                    self.flush()
            except RecursionError:
                raise
            except Exception:
                self.handleError(record)

    root = logging.getLogger()
    # 清除旧 handlers
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    h = SafeStreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    root.addHandler(h)
    root.setLevel(logging.INFO)

    # 捕获 warnings 模块的输出到 logging 系统，避免 ASCII stderr 编码错误
    # 这样 warnings.warn() 会经过上面的 SafeStreamHandler，确保 UTF-8 编码
    logging.captureWarnings(True)

    # 禁用 langchain 的缓存调试输出（可能包含中文并触发 ASCII 编码错误）
    os.environ.setdefault("LANGCHAIN_CACHE", "")
    os.environ.setdefault("LANGCHAIN_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

_install_safe_logging()

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.policy_screener.runner import PolicyScreenerRunner, build_llm
from tradingagents.policy_screener.themes import load_themes

LOG_NAME_RE = re.compile(r"^full_states_log_(\d{4}-\d{2}-\d{2})\.json$")
RESULTS_DIR = Path(DEFAULT_CONFIG["results_dir"]).expanduser().resolve()
STATIC_DIR = Path(__file__).resolve().parent / "cli" / "static"

JOB_LOCK = threading.Lock()
JOBS = {}           # job_id -> { status, ticker, logs, result, ... }
STREAM_QUEUES = {}  # job_id -> queue.Queue  (for SSE streaming)

CRYPTO_SUFFIXES = ("-USD", "-USDT", "-USDC", "-BTC", "-ETH")
FUND_CODE_RE = re.compile(r"^\d{6}$")

DEFAULT_ANALYSTS = ["market", "social", "news", "fundamentals"]
DEFAULT_PROVIDER_MODELS = {
    "openai": {"shallow": "gpt-5.4-mini", "deep": "gpt-5.4"},
    "google": {"shallow": "gemini-1.5-mini", "deep": "gemini-1.5-pro"},
    "anthropic": {"shallow": "claude-3.5-mini", "deep": "claude-4.1"},
    "xai": {"shallow": "grok-4.1-mini", "deep": "grok-4.1"},
    "deepseek": {"shallow": "deepseek-chat", "deep": "deepseek-reasoner"},
    "qwen": {"shallow": "qwen-7b-mini", "deep": "qwen-2.8b"},
    "glm": {"shallow": "glm-6b-mini", "deep": "glm-3.5"},
    "minimax": {"shallow": "m2-mini", "deep": "m2-large"},
    "openrouter": {"shallow": "google/gemma-4o-mini", "deep": "google/gemma-4-26b-a4b"},
    "azure": {"shallow": "gpt-5.4-mini", "deep": "gpt-5.4"},
    "ollama": {"shallow": "llama-3-mini", "deep": "llama-3"},
}

# ── Profiles (saved API configurations) ────────────────────────────────
PROFILES_PATH = Path(os.path.expanduser("~")) / ".tradingagents" / "profiles.json"


def mask_api_key(key) -> str:
    """Mask an API key for display: first 3 chars + '••••' + last 4 chars."""
    if not key:
        return ""
    key = str(key)
    if len(key) < 7:
        return "•" * len(key)
    return f"{key[:3]}{'•' * 4}{key[-4:]}"


def load_profiles() -> dict:
    """Read profiles.json. Returns empty structure if file missing or corrupted."""
    if not PROFILES_PATH.is_file():
        return {"profiles": [], "active": None}
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"profiles": [], "active": None}
        data.setdefault("profiles", [])
        data.setdefault("active", None)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[profiles] Failed to load {PROFILES_PATH}: {exc}")
        return {"profiles": [], "active": None}


def save_profiles(data: dict) -> None:
    """Atomically write profiles.json. Creates parent dir if missing."""
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PROFILES_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(PROFILES_PATH)


def find_profile(data: dict, name: str):
    """Return the profile dict with given name, or None."""
    for p in data.get("profiles", []):
        if p.get("name") == name:
            return p
    return None


def upsert_profile(data: dict, name: str, config: dict) -> dict:
    """Create or update a profile. Returns the updated data dict."""
    existing = find_profile(data, name)
    now = time.time()
    if existing is not None:
        existing["config"] = config
        existing["updated_at"] = now
    else:
        data["profiles"].append({
            "name": name,
            "created_at": now,
            "updated_at": now,
            "config": config,
        })
    return data


def delete_profile(data: dict, name: str) -> dict:
    """Remove profile by name. Maintains active fallback. Returns updated data."""
    data["profiles"] = [p for p in data.get("profiles", []) if p.get("name") != name]
    if data.get("active") == name:
        data["active"] = data["profiles"][0]["name"] if data["profiles"] else None
    return data


def apply_profile_to_environ(config: dict) -> None:
    """Inject api_key from profile config into os.environ per provider.

    Uses PROVIDER_API_KEY_ENV mapping. No-op if provider is unknown / ollama /
    key is missing or empty.
    """
    provider = (config.get("llm_provider") or "").lower()
    key = config.get("api_key")
    if not key:
        return
    env_var = PROVIDER_API_KEY_ENV.get(provider)
    if env_var:
        os.environ[env_var] = key


def resolve_profile_config(name: str):
    """Load a profile by name and return its config dict, or None if not found."""
    if not name:
        return None
    data = load_profiles()
    profile = find_profile(data, name)
    if profile is None:
        return None
    return profile.get("config", {})


def _mask_profile_config(config: dict) -> dict:
    """Return a copy of config with api_key masked for client response."""
    masked = dict(config)
    if "api_key" in masked:
        masked["api_key"] = mask_api_key(masked["api_key"])
    return masked


def _mask_profiles_for_response(data: dict) -> dict:
    """Return profiles data suitable for client response (keys masked)."""
    return {
        "profiles": [
            {**p, "config": _mask_profile_config(p.get("config", {}))}
            for p in data.get("profiles", [])
        ],
        "active": data.get("active"),
    }

# ── agent node name → display name mapping (for SSE agent_start/agent_done) ──
AGENT_DISPLAY_NAMES = {
    "market_analyst": "Market Analyst",
    "social_analyst": "Sentiment Analyst",
    "news_analyst": "News Analyst",
    "fundamentals_analyst": "Fundamentals Analyst",
    "bull_researcher": "Bull Researcher",
    "bear_researcher": "Bear Researcher",
    "research_manager": "Research Manager",
    "trader": "Trader",
    "aggressive_risk_analyst": "Aggressive Risk Analyst",
    "neutral_risk_analyst": "Neutral Risk Analyst",
    "conservative_risk_analyst": "Conservative Risk Analyst",
    "portfolio_manager": "Portfolio Manager",
}

# ── report section keys in final_state ──
REPORT_SECTION_KEYS = [
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
]

REPORT_SECTION_LABELS = {
    "market_report": "Market Analysis",
    "sentiment_report": "Sentiment Analysis",
    "news_report": "News Analysis",
    "fundamentals_report": "Fundamentals Analysis",
    "investment_plan": "Research Team Decision",
    "trader_investment_plan": "Trading Team Plan",
    "final_trade_decision": "Portfolio Management Decision",
}


def detect_asset_type(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if normalized.endswith(CRYPTO_SUFFIXES):
        return "crypto"
    if FUND_CODE_RE.match(normalized):
        return "fund"
    return "stock"


def find_log_file(ticker: str, date: str):
    safe_ticker_component(ticker)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("date must be YYYY-MM-DD")

    ticker_dir = RESULTS_DIR / ticker
    if not ticker_dir.is_dir():
        return None

    for file_path in ticker_dir.rglob(f"full_states_log_{date}.json"):
        if file_path.is_file():
            return file_path
    return None


def list_ticker_logs():
    if not RESULTS_DIR.exists():
        return []

    tickers = []
    for ticker_dir in sorted(RESULTS_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        try:
            safe_ticker_component(ticker_dir.name)
        except ValueError:
            continue

        dates = set()
        for log_file in ticker_dir.rglob("full_states_log_*.json"):
            match = LOG_NAME_RE.fullmatch(log_file.name)
            if not match:
                continue
            dates.add(match.group(1))

        if dates:
            tickers.append({"ticker": ticker_dir.name, "dates": sorted(dates, reverse=True)})
    return tickers


def load_report(ticker: str, date: str):
    file_path = find_log_file(ticker, date)
    if file_path is None:
        raise FileNotFoundError(f"Result not found for {ticker} on {date}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Attach structured sections list for the frontend
    sections = []
    for key in REPORT_SECTION_KEYS:
        content = data.get(key)
        if content:
            sections.append({
                "key": key,
                "label": REPORT_SECTION_LABELS.get(key, key),
                "content": content,
            })
    data["_sections"] = sections
    return data


def create_job_id():
    return uuid.uuid4().hex


def sanitize_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Request payload must be a JSON object")

    ticker = payload.get("ticker")
    if not ticker or not isinstance(ticker, str):
        raise ValueError("ticker is required")

    analysis_date = payload.get("analysis_date")
    if not analysis_date or not isinstance(analysis_date, str):
        raise ValueError("analysis_date is required")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", analysis_date):
        raise ValueError("analysis_date must be YYYY-MM-DD")

    asset_type = payload.get("asset_type")
    if not asset_type or asset_type not in {"stock", "crypto", "fund"}:
        asset_type = detect_asset_type(ticker)

    selected_analysts = payload.get("selected_analysts") or DEFAULT_ANALYSTS
    if not isinstance(selected_analysts, list):
        raise ValueError("selected_analysts must be a list of strings")

    llm_provider = payload.get("llm_provider") or "deepseek"
    backend_url = payload.get("backend_url")
    shallow_thinker = payload.get("shallow_thinker") or DEFAULT_PROVIDER_MODELS.get(llm_provider, {}).get("shallow")
    deep_thinker = payload.get("deep_thinker") or DEFAULT_PROVIDER_MODELS.get(llm_provider, {}).get("deep")
    output_language = payload.get("output_language") or "Chinese"
    research_depth = int(payload.get("research_depth", 1))
    checkpoint = bool(payload.get("checkpoint", False))
    google_thinking_level = payload.get("google_thinking_level")
    openai_reasoning_effort = payload.get("openai_reasoning_effort")
    anthropic_effort = payload.get("anthropic_effort")
    profile_name = payload.get("profile")
    if profile_name is not None and not isinstance(profile_name, str):
        raise ValueError("profile must be a string")

    return {
        "ticker": ticker.strip().upper(),
        "analysis_date": analysis_date,
        "asset_type": asset_type,
        "selected_analysts": [str(x) for x in selected_analysts],
        "llm_provider": llm_provider.lower(),
        "backend_url": backend_url,
        "shallow_thinker": shallow_thinker,
        "deep_thinker": deep_thinker,
        "output_language": output_language,
        "research_depth": research_depth,
        "checkpoint": checkpoint,
        "google_thinking_level": google_thinking_level,
        "openai_reasoning_effort": openai_reasoning_effort,
        "anthropic_effort": anthropic_effort,
        "profile": profile_name,
    }


def _emit(evt_queue: queue.Queue, event: str, data: dict):
    """Push an SSE event dict onto the queue (non-blocking, best-effort)."""
    try:
        evt_queue.put_nowait({"event": event, "data": data})
    except queue.Full:
        pass  # drop on back-pressure; the stream is best-effort


def run_analysis_job(job_id: str, payload: dict):
    job = JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
    job["logs"].append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "message": "Job started"})

    # Create or reuse a queue for this job's SSE stream
    with JOB_LOCK:
        if job_id not in STREAM_QUEUES:
            STREAM_QUEUES[job_id] = queue.Queue(maxsize=256)
    evt = STREAM_QUEUES[job_id]

    _emit(evt, "log", {"message": "Analysis starting...", "level": "info"})

    try:
        selections = sanitize_payload(payload)

        # ── Apply profile overrides (if any) ──
        profile_config = resolve_profile_config(selections.get("profile"))
        if profile_config:
            for key in ("llm_provider", "backend_url", "shallow_thinker",
                        "deep_thinker", "output_language", "research_depth",
                        "checkpoint", "asset_type"):
                if key in profile_config and profile_config[key] is not None:
                    selections[key] = profile_config[key]
            apply_profile_to_environ(profile_config)

        config = DEFAULT_CONFIG.copy()
        config["max_debate_rounds"] = selections["research_depth"]
        config["max_risk_discuss_rounds"] = selections["research_depth"]
        config["quick_think_llm"] = selections["shallow_thinker"]
        config["deep_think_llm"] = selections["deep_thinker"]
        config["backend_url"] = selections["backend_url"]
        config["llm_provider"] = selections["llm_provider"]
        config["google_thinking_level"] = selections["google_thinking_level"]
        config["openai_reasoning_effort"] = selections["openai_reasoning_effort"]
        config["anthropic_effort"] = selections["anthropic_effort"]
        config["output_language"] = selections["output_language"]
        config["checkpoint_enabled"] = selections["checkpoint"]

        graph = TradingAgentsGraph(
            selections["selected_analysts"],
            config=config,
            debug=True,
        )

        if selections["asset_type"] == "fund":
            graph.tool_nodes = graph._fund_tool_nodes
            graph.graph_setup.tool_nodes = graph._fund_tool_nodes
            graph.workflow = graph.graph_setup.setup_graph(
                selections["selected_analysts"], asset_type="fund"
            )
            graph.graph = graph.workflow.compile()
            graph._last_asset_type = "fund"

        init_agent_state = graph.propagator.create_initial_state(
            selections["ticker"],
            selections["analysis_date"],
            asset_type=selections["asset_type"],
        )
        args = graph.propagator.get_graph_args()

        # ── Stream from LangGraph and push SSE events ──
        final_state = {}
        seen_agents = set()
        for chunk in graph.graph.stream(init_agent_state, **args):
            final_state.update(chunk)

            # Detect which agent node just produced output
            for node_name in chunk:
                if node_name == "messages":
                    continue
                # agent_start event (first time we see this node)
                display_name = AGENT_DISPLAY_NAMES.get(node_name, node_name)
                if node_name not in seen_agents:
                    seen_agents.add(node_name)
                    _emit(evt, "agent_start", {"agent": display_name, "node": node_name})
                    job["logs"].append({
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "message": f"{display_name} started",
                    })

                # agent_done event
                _emit(evt, "agent_done", {"agent": display_name, "node": node_name})
                job["logs"].append({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "message": f"{display_name} completed",
                })

            # Check for report sections filled in this chunk
            for key in REPORT_SECTION_KEYS:
                content = chunk.get(key)
                if content:
                    job["logs"].append({
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "message": f"Report section updated: {REPORT_SECTION_LABELS.get(key, key)}",
                    })
                    _emit(evt, "report_section", {
                        "key": key,
                        "label": REPORT_SECTION_LABELS.get(key, key),
                        "content": content,
                    })

        # ── Final decision ──
        final_decision = final_state.get("final_trade_decision", "")
        _emit(evt, "final_decision", {"decision": final_decision})

        job["logs"].append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "message": "Analysis finished"})
        job["completed_at"] = time.time()
        job["status"] = "completed"
        job["result"] = final_state
        job["report_path"] = str(find_log_file(selections["ticker"], selections["analysis_date"]))

        _emit(evt, "done", {
            "report_path": job.get("report_path"),
            "ticker": selections["ticker"],
            "analysis_date": selections["analysis_date"],
        })

    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        job["logs"].append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "message": f"Error: {exc}"})
        _emit(evt, "error", {"message": str(exc)})

    finally:
        # Signal stream closure
        _emit(evt, "stream_end", {})
        # Keep queue around for a short while so late-connecting clients can drain it,
        # then clean up.
        def _cleanup():
            time.sleep(30)
            with JOB_LOCK:
                STREAM_QUEUES.pop(job_id, None)
        threading.Thread(target=_cleanup, daemon=True).start()


def parse_args():
    parser = argparse.ArgumentParser(
        description="TradingAgents 本地 HTML 结果展示。"
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument(
        "--results-dir",
        default=str(RESULTS_DIR),
        help="结果日志目录，默认使用 TradingAgents 配置中的 results_dir",
    )
    return parser.parse_args()


class FrontendHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return

        if parsed.path in ("/", ""):
            self.path = "/frontend.html"
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            self.handle_api_run()
            return
        if parsed.path == "/api/profiles":
            self.handle_profiles_post()
            return
        if parsed.path == "/api/profiles/activate":
            self.handle_profiles_activate()
            return
        if parsed.path == "/api/policy-recommend":
            self.handle_api_policy_recommend()
            return
        if parsed.path == "/api/hotspot-recommend":
            self.handle_api_hotspot_recommend()
            return
        self.send_error(404, "Unknown API endpoint")

    # ── GET API routing ──────────────────────────────────────────────────

    def handle_api_get(self, parsed):
        params = parse_qs(parsed.query)

        if parsed.path == "/api/profiles":
            data = load_profiles()
            self.send_json(_mask_profiles_for_response(data))
            return

        if parsed.path == "/api/tickers":
            self.send_json({"tickers": list_ticker_logs()})
            return

        if parsed.path == "/api/policy-themes":
            self.handle_api_policy_themes()
            return

        if parsed.path == "/api/report":
            ticker = params.get("ticker", [None])[0]
            date = params.get("date", [None])[0]
            if not ticker or not date:
                self.send_error(400, "Missing required query parameters: ticker and date")
                return
            try:
                report = load_report(ticker, date)
                self.send_json(report)
            except FileNotFoundError as exc:
                self.send_error(404, str(exc))
            except ValueError as exc:
                self.send_error(400, str(exc))
            return

        if parsed.path == "/api/status":
            self.send_json({
                "results_dir": str(RESULTS_DIR),
                "ticker_count": len(list_ticker_logs()),
                "job_count": len(JOBS),
            })
            return

        if parsed.path == "/api/jobs":
            jobs = [
                {
                    "id": job_id,
                    "ticker": job["ticker"],
                    "analysis_date": job["analysis_date"],
                    "status": job["status"],
                    "created_at": job["created_at"],
                    "started_at": job.get("started_at"),
                    "completed_at": job.get("completed_at"),
                }
                for job_id, job in JOBS.items()
            ]
            self.send_json({"jobs": jobs})
            return

        # ── SSE stream endpoint ──────────────────────────────────────
        if parsed.path.startswith("/api/stream/"):
            job_id = parsed.path.split("/", 3)[-1]
            self.handle_sse_stream(job_id)
            return

        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.split("/", 3)[-1]
            job = JOBS.get(job_id)
            if not job:
                self.send_error(404, "Job not found")
                return
            self.send_json({
                "id": job_id,
                "ticker": job["ticker"],
                "analysis_date": job["analysis_date"],
                "status": job["status"],
                "created_at": job["created_at"],
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "logs": job["logs"],
                "error": job.get("error"),
                "report_path": job.get("report_path"),
            })
            return

        # ── Chart data endpoint ──────────────────────────────────────
        if parsed.path == "/api/chart":
            ticker = params.get("ticker", [None])[0]
            if not ticker:
                self.send_error(400, "Missing required query parameter: ticker")
                return
            self.handle_chart_data(ticker)
            return

        self.send_error(404, "Unknown API endpoint")

    # ── SSE streaming ────────────────────────────────────────────────────

    def handle_sse_stream(self, job_id: str):
        """Serve a Server-Sent Events stream for a running (or recently completed) job."""
        evt_queue = STREAM_QUEUES.get(job_id)
        if evt_queue is None:
            # Job doesn't exist — check if it's already completed
            job = JOBS.get(job_id)
            if job is None:
                self.send_error(404, "Job not found")
                return
            # Job exists but queue is gone — send a one-shot done/error event
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if job["status"] == "completed":
                self.wfile.write(f"event: done\ndata: {json.dumps({'report_path': job.get('report_path'), 'ticker': job['ticker'], 'analysis_date': job['analysis_date']})}\n\n".encode())
            elif job["status"] == "failed":
                self.wfile.write(f"event: error\ndata: {json.dumps({'message': job.get('error', 'Unknown error')})}\n\n".encode())
            self.wfile.write("event: stream_end\ndata: {}\n\n".encode())
            self.wfile.flush()
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            while True:
                try:
                    msg = evt_queue.get(timeout=30)
                except queue.Empty:
                    # Send keep-alive comment
                    self.wfile.write(": keepalive\n\n".encode())
                    self.wfile.flush()
                    continue

                event_type = msg.get("event", "message")
                data = json.dumps(msg.get("data", {}), ensure_ascii=False)
                self.wfile.write(f"event: {event_type}\ndata: {data}\n\n".encode())
                self.wfile.flush()

                if event_type in ("stream_end", "done", "error"):
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected

    # ── Chart data ───────────────────────────────────────────────────────

    def handle_chart_data(self, ticker: str):
        """Return OHLCV + technical indicators for ECharts candlestick chart.

        先尝试 yfinance，若限速则自动降级到 baostock（仅限 A 股）。
        """
        ticker_clean = ticker.strip().upper()

        # ── 尝试 yfinance ──────────────────────────────────────────────
        yf_error = None
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker_clean)
            hist = stock.history(period="6mo")
            if not hist.empty:
                ohlc, volumes = self._build_chart_arrays(hist)
                self.send_json({
                    "ticker": ticker_clean,
                    "ohlc": ohlc,
                    "volumes": volumes,
                    "period": "6mo",
                    "source": "yfinance",
                })
                return
            # hist 为空可能是限速或无数据
            yf_error = "yfinance 返回空数据"
        except Exception as exc:
            yf_error = str(exc)
            logging.warning("[图表] yfinance 失败: %s，尝试 baostock 降级", yf_error)

        # ── 降级到 baostock（仅 A 股） ─────────────────────────────────
        is_a_share = (
            ticker_clean.endswith(".SS") or
            ticker_clean.endswith(".SZ") or
            (ticker_clean.isdigit() and len(ticker_clean) == 6)
        )
        if is_a_share:
            try:
                ohlc, volumes = self._get_chart_data_baostock(ticker_clean)
                if ohlc:
                    self.send_json({
                        "ticker": ticker_clean,
                        "ohlc": ohlc,
                        "volumes": volumes,
                        "period": "6mo",
                        "source": "baostock",
                    })
                    logging.info("[图表] %s 已通过 baostock 降级获取数据（%d 条）", ticker_clean, len(ohlc))
                    return
            except Exception as bs_exc:
                logging.warning("[图表] baostock 降级也失败: %s", bs_exc)
                self.send_error(500, f"Chart data error: yfinance({yf_error}), baostock({bs_exc})")
                return

        self.send_error(500, f"Chart data error: {yf_error}")

    def _build_chart_arrays(self, hist):
        """将 yfinance DataFrame 转换为 ECharts 格式数组。"""
        ohlc = []
        volumes = []
        for idx, row in hist.iterrows():
            date_str = idx.strftime("%Y-%m-%d")
            ohlc.append([
                date_str,
                round(float(row["Open"]), 2),
                round(float(row["Close"]), 2),
                round(float(row["Low"]), 2),
                round(float(row["High"]), 2),
            ])
            volumes.append([
                date_str,
                round(float(row["Volume"]), 0),
                1 if row["Close"] >= row["Open"] else -1,
            ])
        return ohlc, volumes

    def _get_chart_data_baostock(self, ticker: str):
        """用 baostock 获取 K 线数据，返回 (ohlc, volumes) 元组。"""
        from datetime import datetime, timedelta
        from tradingagents.dataflows.baostock_data import _to_bs_code, _ensure_login

        bs_code = _to_bs_code(ticker)
        if bs_code is None:
            raise ValueError(f"baostock 不支持 ticker: {ticker}")

        if not _ensure_login():
            raise RuntimeError("baostock 登录失败")

        import baostock as bs
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",  # 前复权
        )
        if rs.error_code != "0":
            raise RuntimeError(f"baostock 查询失败: {rs.error_msg}")

        ohlc = []
        volumes = []
        while rs.next():
            row = rs.get_row_data()
            # row: [date, open, high, low, close, volume]
            try:
                date_str = row[0]
                o = round(float(row[1] or 0), 2)
                h = round(float(row[2] or 0), 2)
                lo = round(float(row[3] or 0), 2)
                c = round(float(row[4] or 0), 2)
                v = round(float(row[5] or 0), 0)
                if o == 0 and c == 0:
                    continue
                ohlc.append([date_str, o, c, lo, h])
                volumes.append([date_str, v, 1 if c >= o else -1])
            except (ValueError, IndexError):
                continue

        return ohlc, volumes

    # ── POST /api/profiles ─────────────────────────────────────────────

    def handle_profiles_post(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self.send_error(400, "Invalid JSON payload")
            return

        name = (body.get("name") or "").strip()
        if not name:
            self.send_error(400, "name is required")
            return
        config = body.get("config")
        if not isinstance(config, dict):
            self.send_error(400, "config must be a dict")
            return

        try:
            data = load_profiles()
            data = upsert_profile(data, name, config)
            if data.get("active") is None and data["profiles"]:
                data["active"] = name
            save_profiles(data)
            self.send_json({"ok": True, "active": data["active"]}, status=201)
        except OSError as exc:
            self.send_error(500, f"Failed to save profiles: {exc}")

    def handle_profiles_activate(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self.send_error(400, "Invalid JSON payload")
            return

        name = (body.get("name") or "").strip()
        if not name:
            self.send_error(400, "name is required")
            return

        try:
            data = load_profiles()
            if find_profile(data, name) is None:
                self.send_error(404, f"Profile not found: {name}")
                return
            data["active"] = name
            save_profiles(data)
            self.send_json({"ok": True, "active": data["active"]})
        except OSError as exc:
            self.send_error(500, f"Failed to save profiles: {exc}")

    # ── POST /api/run ────────────────────────────────────────────────────

    def handle_api_run(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self.send_error(400, "Invalid JSON payload")
            return

        try:
            sanitized = sanitize_payload(payload)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return

        job_id = create_job_id()
        with JOB_LOCK:
            JOBS[job_id] = {
                "ticker": sanitized["ticker"],
                "analysis_date": sanitized["analysis_date"],
                "status": "pending",
                "created_at": time.time(),
                "logs": [],
                "payload": sanitized,
            }
            STREAM_QUEUES[job_id] = queue.Queue(maxsize=256)

        thread = threading.Thread(target=run_analysis_job, args=(job_id, payload), daemon=True)
        thread.start()
        self.send_json({"job_id": job_id, "status": "pending"}, status=202)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/profiles"):
            self.handle_profiles_delete(parsed)
            return
        self.send_error(404, "Unknown API endpoint")

    def handle_profiles_delete(self, parsed):
        params = parse_qs(parsed.query)
        name = (params.get("name") or [None])[0]
        if not name:
            self.send_error(400, "Missing required query parameter: name")
            return
        try:
            data = load_profiles()
            if find_profile(data, name) is None:
                self.send_error(404, f"Profile not found: {name}")
                return
            data = delete_profile(data, name)
            save_profiles(data)
            self.send_json({"ok": True, "active": data["active"]})
        except OSError as exc:
            self.send_error(500, f"Failed to save profiles: {exc}")

    # ── Policy Recommend ───────────────────────────────────────────────

    def handle_api_policy_recommend(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self.send_error(400, "Invalid JSON payload")
            return

        themes_str = payload.get("themes", "")
        date = payload.get("date", "")
        deep = payload.get("deep", False)
        llm_provider = payload.get("llm_provider") or "deepseek"
        shallow_thinker = payload.get("shallow_thinker") or ""
        deep_thinker = payload.get("deep_thinker") or ""
        api_key = payload.get("api_key") or ""
        backend_url = payload.get("backend_url") or ""

        # Parse themes (comma-separated)
        themes_list = [t.strip() for t in themes_str.split(",") if t.strip()]

        # Set API key in environment for LLM client
        env_var = PROVIDER_API_KEY_ENV.get(llm_provider.lower())
        if env_var and api_key:
            os.environ[env_var] = api_key

        config = DEFAULT_CONFIG.copy()
        config["output_language"] = "Chinese"
        config["llm_provider"] = llm_provider.lower()
        if shallow_thinker:
            config["quick_think_llm"] = shallow_thinker
        if deep_thinker:
            config["deep_think_llm"] = deep_thinker
        if backend_url:
            config["backend_url"] = backend_url

        llm = build_llm(config)
        graph = None
        if deep and llm is not None:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            graph = TradingAgentsGraph(
                selected_analysts=["market", "social", "news", "fundamentals"],
                debug=True, config=config,
            )

        runner = PolicyScreenerRunner(config, llm=llm, graph=graph)
        try:
            report = runner.run(themes=themes_list, date=date, deep_analyze=deep)
            self.send_json({"report": report, "themes": themes_list, "date": date})
        except Exception as e:
            self.send_json({"error": str(e), "report": None}, status=500)

    def handle_api_policy_themes(self):
        try:
            config = DEFAULT_CONFIG.copy()
            cfg = load_themes(config["policy_themes_file"], enabled=[])
            # 返回分类+板块数据
            categories = []
            for cat_name, board_names in cfg.all_categories().items():
                boards = []
                for bn in board_names:
                    try:
                        b = cfg.get_board(bn)
                        boards.append({"name": b.name, "keywords": b.keywords, "funds": b.funds})
                    except KeyError:
                        pass
                categories.append({"name": cat_name, "boards": boards})
            self.send_json({"categories": categories})
        except Exception as e:
            self.send_json({"error": str(e), "categories": []}, status=500)

    # ── Hotspot Recommend (SSE) ────────────────────────────────────────

    def handle_api_hotspot_recommend(self):
        """POST /api/hotspot-recommend — 自动拉新闻、识别热点、筛选标的，SSE 实时推进度。"""
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self.send_error(400, "Invalid JSON payload")
            return

        date           = payload.get("date", "")
        deep           = payload.get("deep", False)
        llm_provider   = payload.get("llm_provider") or "deepseek"
        shallow_thinker = payload.get("shallow_thinker") or ""
        deep_thinker   = payload.get("deep_thinker") or ""
        api_key        = payload.get("api_key") or ""
        backend_url    = payload.get("backend_url") or ""
        max_price_raw  = payload.get("max_price")
        max_price      = float(max_price_raw) if max_price_raw else None

        # 设置 API Key 环境变量
        env_var = PROVIDER_API_KEY_ENV.get(llm_provider.lower())
        if env_var and api_key:
            os.environ[env_var] = api_key

        config = DEFAULT_CONFIG.copy()
        config["output_language"] = "Chinese"
        config["llm_provider"] = llm_provider.lower()
        if shallow_thinker:
            config["quick_think_llm"] = shallow_thinker   # 快速思考模型
        if deep_thinker:
            config["deep_think_llm"] = deep_thinker       # 深度思考模型
        if backend_url:
            config["backend_url"] = backend_url
        if max_price:
            config["policy_max_price"] = max_price
        # api_key 已写入环境变量，此处再存一份便于 build_llm 检测
        if api_key:
            config["_api_key"] = api_key

        # 建立 SSE 响应
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def _sse(event: str, data: dict):
            """写一条 SSE 事件到响应流。"""
            try:
                msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def progress_cb(stage: str, message: str):
            _sse("progress", {"stage": stage, "message": message})

        try:
            from tradingagents.policy_screener.runner import PolicyScreenerRunner, build_llm

            # ── 构建 LLM，失败立即推送错误原因 ──
            try:
                llm = build_llm(config)
                _sse("progress", {"stage": "hotspot", "message": f"LLM 初始化成功（{llm_provider}/{config.get('quick_think_llm','')}）"})
            except RuntimeError as llm_err:
                _sse("progress", {"stage": "hotspot", "message": f"❌ LLM 初始化失败：{llm_err}"})
                _sse("error", {"message": str(llm_err)})
                return

            graph = None
            if deep and llm is not None:
                from tradingagents.graph.trading_graph import TradingAgentsGraph
                graph = TradingAgentsGraph(
                    selected_analysts=["market", "social", "news", "fundamentals"],
                    debug=True, config=config,
                )

            runner = PolicyScreenerRunner(config, llm=llm, graph=graph)
            report, hotspots = runner.run_auto(
                date=date,
                deep_analyze=deep,
                progress_cb=progress_cb,
            )
            _sse("done", {"report": report, "hotspots": hotspots})

        except Exception as e:
            _sse("error", {"message": str(e)})
        finally:
            _sse("stream_end", {})

    # ── helpers ──────────────────────────────────────────────────────────

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Suppress default access logging or keep it light."""
        # Uncomment the next line to see HTTP access logs:
        # super().log_message(format, *args)
        pass


def _setup_logging():
    """配置 logging 使用 UTF-8 编码，避免中文日志在某些终端引发 ascii 编码错误。"""
    import io

    class SafeStreamHandler(logging.StreamHandler):
        """StreamHandler 的子类，写入时强制 UTF-8 并用 replace 处理无法编码的字符。"""

        def emit(self, record):
            try:
                msg = self.format(record)
                stream = self.stream
                # 确保写入时不会因编码问题崩溃
                if hasattr(stream, "buffer"):
                    stream.buffer.write((msg + self.terminator).encode("utf-8", errors="replace"))
                    stream.buffer.flush()
                else:
                    # fallback：先把 msg 安全编码再解码成 ascii 兼容字符串
                    safe_msg = msg.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
                    stream.write(safe_msg + self.terminator)
                    self.flush()
            except RecursionError:
                raise
            except Exception:
                self.handleError(record)

    # 移除根 logger 上已有的所有 StreamHandler，换成 SafeStreamHandler
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler):
            root.removeHandler(h)
            h.close()

    handler = SafeStreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # 捕获 warnings 模块的输出到 logging 系统，避免 ASCII stderr 编码错误
    logging.captureWarnings(True)

    # 禁用 langchain 的缓存调试输出（可能包含中文并触发 ASCII 编码错误）
    os.environ.setdefault("LANGCHAIN_CACHE", "")
    os.environ.setdefault("LANGCHAIN_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")


def main():
    _setup_logging()
    args = parse_args()
    global RESULTS_DIR
    RESULTS_DIR = Path(args.results_dir).expanduser().resolve()

    server = ThreadingHTTPServer((args.host, args.port), FrontendHandler)
    print(
        f"TradingAgents 本地 HTML 展示已启动：http://{args.host}:{args.port}/\n"
        f"结果目录：{RESULTS_DIR}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止。")


if __name__ == "__main__":
    main()