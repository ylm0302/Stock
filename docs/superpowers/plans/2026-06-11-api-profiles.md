# API 配置方案（Profiles）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在页面上保存并切换多套完整的 API 分析环境（provider / URL / key / 模型 / 运行参数），持久化到服务端 `~/.tradingagents/profiles.json`。

**Architecture:** 后端在 `webapp.py` 新增 4 个 API 端点（GET/POST/DELETE profiles、POST activate）+ 文件 I/O 辅助函数 + key 注入逻辑。前端在左侧面板顶部插入「📁 配置方案」下拉区块，新增 `backend_url` 和 `api_key` 输入框，启动时加载并填充激活方案。

**Tech Stack:** Python 3.10+ (stdlib `http.server` + `json`)、Vue 3 CDN、Tailwind CSS (CDN)、pytest、`~/.tradingagents/profiles.json` 作为持久化存储。

**Note:** 项目当前未初始化 git，本计划省略 commit 步骤。每个 Task 结束后可以自行 `git commit` 或跳过。

---

## File Structure

**后端（`webapp.py` 新增）：**
- `PROFILES_PATH: pathlib.Path` — `~/.tradingagents/profiles.json` 常量
- `load_profiles() -> dict` — 读文件，返回 `{"profiles": [...], "active": "..."}`；文件不存在返回空结构
- `save_profiles(data: dict) -> None` — 原子写文件
- `mask_api_key(key: str) -> str` — 返回 `sk-••••42e3` 格式
- `find_profile(data: dict, name: str) -> dict | None` — 按名字找方案
- `upsert_profile(data: dict, name: str, config: dict) -> dict` — 新建或覆盖
- `delete_profile(data: dict, name: str) -> dict` — 删除并维护 active
- `apply_profile_to_environ(config: dict) -> None` — 按 provider 把 api_key 注入 `os.environ`
- 4 个 handler：`handle_profiles_get`、`handle_profiles_post`、`handle_profiles_delete`、`handle_profiles_activate`
- 修改 `handle_api_get` 增加 `/api/profiles` 和 `/api/profiles/activate` 分支（注意 activate 是 POST，要在 `do_POST` 路由）
- 修改 `do_POST` 路由增加 `/api/profiles`、`/api/profiles/activate`
- 修改 `sanitize_payload` 增加 `profile` 字段
- 修改 `run_analysis_job` 开头注入 key

**前端（`cli/static/`）：**
- `frontend.html` — 顶部新增「配置方案」区块；新增 backend_url / api_key 输入框
- `app.js` — 新增 `profiles` 数据、`activeProfile`、`profileDirty`、方法（`loadProfiles`、`saveProfile`、`saveAsProfile`、`deleteProfile`、`switchProfile`、`applyProfile`、`isProfileDirty`）；`startAnalysis` 带 `profile` 字段；`mounted` 加载
- `style.css` — `@keyframes pulse-accent` 动画

**测试（新建）：**
- `tests/test_profiles_storage.py` — 测试 `load_profiles` / `save_profiles` / `mask_api_key` / `upsert` / `delete` / `apply_profile_to_environ`

**复用现有：**
- `tradingagents.llm_clients.api_key_env.PROVIDER_API_KEY_ENV` — provider→env var 映射（避免重复）

---

## Task 1: Backend — 文件 I/O 与 mask 辅助函数

**Files:**
- Create: `tests/test_profiles_storage.py`
- Modify: `webapp.py` (新增模块级常量和辅助函数，放在 `DEFAULT_PROVIDER_MODELS` 之后)

- [ ] **Step 1.1: 写测试文件（辅助函数部分）**

创建 `tests/test_profiles_storage.py`：

```python
"""Tests for profiles storage helpers in webapp."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture()
def profiles_module(tmp_path, monkeypatch):
    """Import webapp with PROFILES_PATH redirected to a tmp directory."""
    # Redirect PROFILES_PATH before importing so tests don't touch ~/.tradingagents
    import importlib
    import webapp as webapp_module

    fake_path = tmp_path / "profiles.json"
    monkeypatch.setattr(webapp_module, "PROFILES_PATH", fake_path)
    yield webapp_module
    # Reload to reset module state if needed
    importlib.reload(webapp_module)


# ---- mask_api_key ---------------------------------------------------------


def test_mask_short_key(profiles_module):
    assert profiles_module.mask_api_key("sk-abcdef") == "sk-••••cdef"


def test_mask_typical_key(profiles_module):
    assert profiles_module.mask_api_key("sk-test000000000000000000000000000000") == "sk-••••b4e3"


def test_mask_very_short_key(profiles_module):
    # Key shorter than 7 chars: full mask
    assert profiles_module.mask_api_key("abc") == "•••"


def test_mask_empty_string(profiles_module):
    assert profiles_module.mask_api_key("") == ""


def test_mask_none(profiles_module):
    assert profiles_module.mask_api_key(None) == ""


# ---- load_profiles / save_profiles ---------------------------------------


def test_load_profiles_missing_file_returns_empty(profiles_module):
    result = profiles_module.load_profiles()
    assert result == {"profiles": [], "active": None}


def test_save_then_load_roundtrip(profiles_module):
    data = {
        "profiles": [
            {
                "name": "test",
                "created_at": 1.0,
                "updated_at": 1.0,
                "config": {"llm_provider": "deepseek"},
            }
        ],
        "active": "test",
    }
    profiles_module.save_profiles(data)
    loaded = profiles_module.load_profiles()
    assert loaded == data


def test_load_profiles_corrupted_json_returns_empty(profiles_module, capsys):
    # Write garbage
    profiles_module.PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    profiles_module.PROFILES_PATH.write_text("{ not valid json")
    result = profiles_module.load_profiles()
    assert result == {"profiles": [], "active": None}


# ---- upsert_profile -------------------------------------------------------


def test_upsert_new_profile(profiles_module):
    data = {"profiles": [], "active": None}
    result = profiles_module.upsert_profile(data, "Home", {"llm_provider": "deepseek"})
    assert len(result["profiles"]) == 1
    assert result["profiles"][0]["name"] == "Home"
    assert result["profiles"][0]["config"] == {"llm_provider": "deepseek"}
    assert "created_at" in result["profiles"][0]
    assert "updated_at" in result["profiles"][0]


def test_upsert_existing_profile_updates_config(profiles_module):
    data = {
        "profiles": [
            {"name": "Home", "created_at": 1.0, "updated_at": 1.0, "config": {"llm_provider": "deepseek"}}
        ],
        "active": "Home",
    }
    result = profiles_module.upsert_profile(data, "Home", {"llm_provider": "openai"})
    assert len(result["profiles"]) == 1
    assert result["profiles"][0]["config"]["llm_provider"] == "openai"
    assert result["profiles"][0]["created_at"] == 1.0  # preserved
    assert result["profiles"][0]["updated_at"] > 1.0    # bumped


# ---- delete_profile -------------------------------------------------------


def test_delete_existing_profile(profiles_module):
    data = {
        "profiles": [
            {"name": "A", "created_at": 1.0, "updated_at": 1.0, "config": {}},
            {"name": "B", "created_at": 1.0, "updated_at": 1.0, "config": {}},
        ],
        "active": "A",
    }
    result = profiles_module.delete_profile(data, "A")
    assert len(result["profiles"]) == 1
    assert result["profiles"][0]["name"] == "B"
    # active was "A" (deleted) → fallback to first remaining
    assert result["active"] == "B"


def test_delete_last_profile_sets_active_null(profiles_module):
    data = {
        "profiles": [{"name": "Only", "created_at": 1.0, "updated_at": 1.0, "config": {}}],
        "active": "Only",
    }
    result = profiles_module.delete_profile(data, "Only")
    assert result["profiles"] == []
    assert result["active"] is None


def test_delete_nonexistent_profile_no_op(profiles_module):
    data = {
        "profiles": [{"name": "A", "created_at": 1.0, "updated_at": 1.0, "config": {}}],
        "active": "A",
    }
    result = profiles_module.delete_profile(data, "missing")
    assert result == data  # unchanged


def test_delete_non_active_profile_keeps_active(profiles_module):
    data = {
        "profiles": [
            {"name": "A", "created_at": 1.0, "updated_at": 1.0, "config": {}},
            {"name": "B", "created_at": 1.0, "updated_at": 1.0, "config": {}},
        ],
        "active": "A",
    }
    result = profiles_module.delete_profile(data, "B")
    assert result["active"] == "A"


# ---- apply_profile_to_environ --------------------------------------------


def test_apply_profile_injects_deepseek_key(profiles_module, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = {"llm_provider": "deepseek", "api_key": "sk-test-key"}
    profiles_module.apply_profile_to_environ(config)
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-test-key"


def test_apply_profile_skips_empty_key(profiles_module, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = {"llm_provider": "openai", "api_key": ""}
    profiles_module.apply_profile_to_environ(config)
    assert "OPENAI_API_KEY" not in os.environ


def test_apply_profile_skips_ollama(profiles_module, monkeypatch):
    # ollama has no key env var; should not raise
    config = {"llm_provider": "ollama", "api_key": "ignored"}
    profiles_module.apply_profile_to_environ(config)  # no exception


def test_apply_profile_skips_missing_key_field(profiles_module, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = {"llm_provider": "anthropic"}  # no api_key field
    profiles_module.apply_profile_to_environ(config)
    assert "ANTHROPIC_API_KEY" not in os.environ
```

- [ ] **Step 1.2: 运行测试，确认全部失败**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/test_profiles_storage.py -v`

Expected: 所有测试 ERROR 或 FAIL，因为 `webapp.mask_api_key` 等还不存在。

- [ ] **Step 1.3: 在 `webapp.py` 顶部新增 imports**

在 `webapp.py` 第 12 行附近（现有 `from tradingagents...` 之后）新增：

```python
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
```

- [ ] **Step 1.4: 在 `webapp.py` 中新增常量和辅助函数**

在 `DEFAULT_PROVIDER_MODELS` 字典定义之后（约第 41 行之后），插入：

```python
# ── Profiles (saved API configurations) ────────────────────────────────
PROFILES_PATH = Path(os.path.expanduser("~")) / ".tradingagents" / "profiles.json"


def mask_api_key(key) -> str:
    """Mask an API key for display: first 3 chars + '••••' + last 4 chars.

    Returns empty string for None / empty / too-short inputs.
    """
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


def find_profile(data: dict, name: str) -> dict | None:
    """Return the profile dict with given name, or None."""
    for p in data.get("profiles", []):
        if p.get("name") == name:
            return p
    return None


def upsert_profile(data: dict, name: str, config: dict) -> dict:
    """Create or update a profile. Returns the updated data dict."""
    import time
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
```

- [ ] **Step 1.5: 运行测试，确认全部通过**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/test_profiles_storage.py -v`

Expected: 所有测试 PASS。

---

## Task 2: Backend — GET /api/profiles 端点

**Files:**
- Modify: `webapp.py` (在 `handle_api_get` 中加分支；新增 `handle_profiles_get` 方法)
- Modify: `tests/test_profiles_storage.py` (追加端点测试)

- [ ] **Step 2.1: 追加端点测试**

在 `tests/test_profiles_storage.py` 末尾追加：

```python
# ---- GET /api/profiles (via handler) -----------------------------------


def test_get_profiles_empty(profiles_module):
    """GET returns empty list when no file exists."""
    # Use a mock request handler — call the underlying logic directly
    data = profiles_module.load_profiles()
    masked = profiles_module._mask_profiles_for_response(data)
    assert masked == {"profiles": [], "active": None}


def test_get_profiles_masks_keys(profiles_module):
    profiles_module.save_profiles({
        "profiles": [
            {
                "name": "Home",
                "created_at": 1.0,
                "updated_at": 1.0,
                "config": {
                    "llm_provider": "deepseek",
                    "api_key": "sk-test000000000000000000000000000000",
                },
            }
        ],
        "active": "Home",
    })
    data = profiles_module.load_profiles()
    masked = profiles_module._mask_profiles_for_response(data)
    assert len(masked["profiles"]) == 1
    assert masked["profiles"][0]["config"]["api_key"] == "sk-••••b4e3"
    assert masked["active"] == "Home"
```

- [ ] **Step 2.2: 运行测试，确认失败**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/test_profiles_storage.py::test_get_profiles_empty tests/test_profiles_storage.py::test_get_profiles_masks_keys -v`

Expected: FAIL（`_mask_profiles_for_response` 不存在）

- [ ] **Step 2.3: 在 `webapp.py` 中新增 `_mask_profiles_for_response` 辅助**

在 `apply_profile_to_environ` 函数之后追加：

```python
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
```

- [ ] **Step 2.4: 在 `webapp.py` 的 `handle_api_get` 方法中加分支**

在 `handle_api_get` 方法中，找到 `if parsed.path == "/api/tickers":` 之前（约第 381 行），插入：

```python
        if parsed.path == "/api/profiles":
            data = load_profiles()
            self.send_json(_mask_profiles_for_response(data))
            return
```

- [ ] **Step 2.5: 运行测试，确认通过**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/test_profiles_storage.py -v`

Expected: 全部 PASS。

- [ ] **Step 2.6: 手动冒烟（可选）**

启动服务器：`.venv/bin/python webapp.py`，浏览器访问 `http://localhost:8000/api/profiles`，预期看到 `{"profiles": [], "active": null}`。

---

## Task 3: Backend — POST /api/profiles 端点（新建/更新）

**Files:**
- Modify: `webapp.py` (在 `do_POST` 中路由；新增 `handle_profiles_post`)
- Modify: `tests/test_profiles_storage.py` (追加测试)

- [ ] **Step 3.1: 追加测试**

在 `tests/test_profiles_storage.py` 末尾追加：

```python
# ---- POST /api/profiles (logic) ----------------------------------------


def test_post_profile_create_new(profiles_module):
    data = profiles_module.load_profiles()
    body = {
        "name": "Work",
        "config": {"llm_provider": "openai", "api_key": "sk-work"},
    }
    data = profiles_module.upsert_profile(data, body["name"], body["config"])
    profiles_module.save_profiles(data)

    reloaded = profiles_module.load_profiles()
    assert len(reloaded["profiles"]) == 1
    assert reloaded["profiles"][0]["name"] == "Work"
    assert reloaded["profiles"][0]["config"]["api_key"] == "sk-work"


def test_post_profile_update_existing(profiles_module):
    # Pre-populate
    profiles_module.save_profiles({
        "profiles": [
            {"name": "Home", "created_at": 1.0, "updated_at": 1.0,
             "config": {"llm_provider": "deepseek"}}
        ],
        "active": "Home",
    })
    data = profiles_module.load_profiles()
    data = profiles_module.upsert_profile(data, "Home", {"llm_provider": "openai"})
    profiles_module.save_profiles(data)

    reloaded = profiles_module.load_profiles()
    assert len(reloaded["profiles"]) == 1
    assert reloaded["profiles"][0]["config"]["llm_provider"] == "openai"
    assert reloaded["profiles"][0]["created_at"] == 1.0  # preserved
```

- [ ] **Step 3.2: 在 `webapp.py` 的 `do_POST` 方法中添加路由**

找到 `do_POST` 方法（约第 369 行），替换为：

```python
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
        self.send_error(404, "Unknown API endpoint")
```

- [ ] **Step 3.3: 在 `FrontendHandler` 类中新增 `handle_profiles_post` 方法**

在 `handle_api_run` 方法之前（约第 553 行之前）插入：

```python
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
            # If this is the first profile, auto-activate it
            if data.get("active") is None and data["profiles"]:
                data["active"] = name
            save_profiles(data)
            self.send_json({"ok": True, "active": data["active"]}, status=201)
        except OSError as exc:
            self.send_error(500, f"Failed to save profiles: {exc}")
```

- [ ] **Step 3.4: 运行测试**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/test_profiles_storage.py -v`

Expected: 全部 PASS。

---

## Task 4: Backend — DELETE /api/profiles + POST /api/profiles/activate

**Files:**
- Modify: `webapp.py` (新增 `handle_profiles_delete`、`handle_profiles_activate`；扩展 `do_DELETE`)
- Modify: `tests/test_profiles_storage.py` (追加测试)

- [ ] **Step 4.1: 追加测试**

在 `tests/test_profiles_storage.py` 末尾追加：

```python
# ---- DELETE /api/profiles (logic) --------------------------------------


def test_delete_active_profile_falls_back(profiles_module):
    profiles_module.save_profiles({
        "profiles": [
            {"name": "A", "created_at": 1.0, "updated_at": 1.0, "config": {}},
            {"name": "B", "created_at": 1.0, "updated_at": 1.0, "config": {}},
        ],
        "active": "A",
    })
    data = profiles_module.load_profiles()
    data = profiles_module.delete_profile(data, "A")
    profiles_module.save_profiles(data)

    reloaded = profiles_module.load_profiles()
    assert reloaded["active"] == "B"
    assert len(reloaded["profiles"]) == 1


# ---- POST /api/profiles/activate (logic) -------------------------------


def test_activate_existing_profile(profiles_module):
    profiles_module.save_profiles({
        "profiles": [
            {"name": "A", "created_at": 1.0, "updated_at": 1.0, "config": {}},
            {"name": "B", "created_at": 1.0, "updated_at": 1.0, "config": {}},
        ],
        "active": "A",
    })
    data = profiles_module.load_profiles()
    data["active"] = "B" if profiles_module.find_profile(data, "B") else data["active"]
    profiles_module.save_profiles(data)

    reloaded = profiles_module.load_profiles()
    assert reloaded["active"] == "B"


def test_activate_nonexistent_profile_no_change(profiles_module):
    profiles_module.save_profiles({
        "profiles": [{"name": "A", "created_at": 1.0, "updated_at": 1.0, "config": {}}],
        "active": "A",
    })
    data = profiles_module.load_profiles()
    target = "missing"
    if profiles_module.find_profile(data, target):
        data["active"] = target
    profiles_module.save_profiles(data)

    reloaded = profiles_module.load_profiles()
    assert reloaded["active"] == "A"
```

- [ ] **Step 4.2: 在 `webapp.py` 的 `FrontendHandler` 中添加 `do_DELETE` 方法**

在 `do_POST` 方法之后插入：

```python
    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/profiles"):
            self.handle_profiles_delete(parsed)
            return
        self.send_error(404, "Unknown API endpoint")
```

- [ ] **Step 4.3: 新增 `handle_profiles_delete` 方法**

在 `handle_profiles_post` 之后插入：

```python
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
```

- [ ] **Step 4.4: 运行测试**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/test_profiles_storage.py -v`

Expected: 全部 PASS。

---

## Task 5: Backend — 在 `/api/run` 中接入 profile

**Files:**
- Modify: `webapp.py` (在 `sanitize_payload` 增加 profile 字段；在 `run_analysis_job` 注入 key)
- Modify: `tests/test_profiles_storage.py` (追加测试)

- [ ] **Step 5.1: 追加测试**

在 `tests/test_profiles_storage.py` 末尾追加：

```python
# ---- apply_profile_to_environ: azure, missing provider --------------


def test_apply_profile_azure_injects_api_key(profiles_module, monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    config = {"llm_provider": "azure", "api_key": "azure-key-123"}
    profiles_module.apply_profile_to_environ(config)
    assert os.environ.get("AZURE_OPENAI_API_KEY") == "azure-key-123"


def test_apply_profile_unknown_provider_no_injection(profiles_module, monkeypatch):
    # Unknown provider should not raise; no env var written
    config = {"llm_provider": "totally-fake", "api_key": "sk-fake"}
    profiles_module.apply_profile_to_environ(config)  # no exception


# ---- resolve_profile_config (helper for /api/run) ----------------------


def test_resolve_profile_config_returns_overrides(profiles_module):
    profiles_module.save_profiles({
        "profiles": [
            {
                "name": "Home",
                "created_at": 1.0,
                "updated_at": 1.0,
                "config": {
                    "llm_provider": "deepseek",
                    "api_key": "sk-home",
                    "backend_url": "https://home.example.com",
                },
            }
        ],
        "active": "Home",
    })
    result = profiles_module.resolve_profile_config("Home")
    assert result is not None
    assert result["api_key"] == "sk-home"
    assert result["backend_url"] == "https://home.example.com"


def test_resolve_profile_config_missing_returns_none(profiles_module):
    result = profiles_module.resolve_profile_config("nonexistent")
    assert result is None
```

- [ ] **Step 5.2: 运行测试，确认失败**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/test_profiles_storage.py::test_resolve_profile_config_returns_overrides tests/test_profiles_storage.py::test_resolve_profile_config_missing_returns_none -v`

Expected: FAIL（`resolve_profile_config` 不存在）

- [ ] **Step 5.3: 在 `webapp.py` 中新增 `resolve_profile_config`**

在 `apply_profile_to_environ` 函数之后追加：

```python
def resolve_profile_config(name: str) -> dict | None:
    """Load a profile by name and return its config dict, or None if not found."""
    if not name:
        return None
    data = load_profiles()
    profile = find_profile(data, name)
    if profile is None:
        return None
    return profile.get("config", {})
```

- [ ] **Step 5.4: 修改 `sanitize_payload` 接受 `profile` 字段**

在 `sanitize_payload` 函数中，找到 `return {` 语句（约第 189 行），在它之前插入：

```python
    profile_name = payload.get("profile")
    if profile_name is not None and not isinstance(profile_name, str):
        raise ValueError("profile must be a string")
```

在返回的字典中新增一项：

```python
        "profile": profile_name,
```

即返回的字典改为：

```python
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
```

- [ ] **Step 5.5: 修改 `run_analysis_job` 应用 profile 配置并注入 key**

在 `run_analysis_job` 函数中，找到 `selections = sanitize_payload(payload)` 之后（约第 230 行之后），`config = DEFAULT_CONFIG.copy()` 之前，插入：

```python
        # ── Apply profile overrides (if any) ──
        profile_config = resolve_profile_config(selections.get("profile"))
        if profile_config:
            # Profile fields override payload fields (except ticker/date/analysts)
            for key in ("llm_provider", "backend_url", "shallow_thinker",
                        "deep_thinker", "output_language", "research_depth",
                        "checkpoint", "asset_type"):
                if key in profile_config and profile_config[key] is not None:
                    selections[key] = profile_config[key]
            # Inject API key into environment for this job
            apply_profile_to_environ(profile_config)
```

- [ ] **Step 5.6: 运行测试**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/test_profiles_storage.py -v`

Expected: 全部 PASS。

- [ ] **Step 5.7: 运行整个测试套件，确保未破坏原有功能**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/ -x --ignore=tests/test_analyst_execution.py`

Expected: 所有测试 PASS。（`test_analyst_execution.py` 是集成测试，可能需要 API key，按惯例忽略）

---

## Task 6: Frontend HTML — 添加方案选择器区块 + 新输入框

**Files:**
- Modify: `cli/static/frontend.html`

- [ ] **Step 6.1: 在「📋 分析配置」标题之后、标的代码输入框之前，插入方案选择器区块**

打开 `cli/static/frontend.html`，找到约第 63 行（`<h2 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">📋 分析配置</h2>`）。在这行**之前**插入：

```html
        <!-- ═══ Profile Selector ═══ -->
        <div id="profile-selector-block" class="mb-3 p-3 rounded-lg border border-accent/40 bg-surface/50">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-semibold text-accent">📁 配置方案</span>
            <span class="text-[10px] text-slate-500">已保存 {{ profiles.length }}</span>
          </div>

          <!-- Empty state:引导创建 -->
          <div v-if="profiles.length === 0" class="text-center py-2">
            <button @click="saveAsProfile"
              class="text-xs text-accent hover:text-white transition">
              ➕ 保存当前为新方案
            </button>
          </div>

          <!-- Populated state -->
          <div v-else>
            <div class="flex items-center gap-1 mb-2">
              <select v-model="activeProfileName" @change="onProfileSwitch"
                class="flex-1 px-2 py-1.5 bg-surface border border-slate-600 rounded text-xs text-white focus:border-accent focus:outline-none">
                <option v-for="p in profiles" :key="p.name" :value="p.name">
                  {{ profileEmoji(p.name) }} {{ p.name }}
                </option>
              </select>
              <button @click="saveProfile" title="保存到当前方案"
                class="px-2 py-1.5 rounded text-xs font-bold transition"
                :class="profileDirty ? 'bg-accent text-slate-900 animate-pulse-accent' : 'bg-surface-lighter text-slate-400 hover:text-white'">
                💾
              </button>
              <button @click="saveAsProfile" title="另存为新方案"
                class="px-2 py-1.5 rounded text-xs bg-surface-lighter text-slate-400 hover:text-white transition">
                ➕
              </button>
              <button @click="deleteProfile" title="删除当前方案"
                class="px-2 py-1.5 rounded text-xs bg-surface-lighter text-red-400 hover:text-red-300 transition">
                🗑
              </button>
            </div>
            <div class="text-[10px] text-slate-500 flex gap-2 flex-wrap">
              <span>🔌 {{ (activeProfileConfig.llm_provider || '—') }}</span>
              <span>🔑 {{ maskedApiKey }}</span>
              <span>🧠 {{ activeProfileConfig.deep_thinker || '—' }}</span>
            </div>
          </div>
        </div>

```

- [ ] **Step 6.2: 在「LLM 提供商」下拉框之后、「快速思考模型」输入框之前，新增 backend_url 和 api_key 输入框**

找到约第 99 行（`<!-- Shallow Model -->` 之前），插入：

```html
          <!-- Backend URL -->
          <div>
            <label class="block text-xs text-slate-400 mb-1">API 接入地址</label>
            <input v-model="form.backend_url" type="text" placeholder="https://..."
              class="w-full px-3 py-2 bg-surface border border-slate-600 rounded-lg text-sm text-white placeholder-slate-500 focus:border-accent focus:outline-none transition" />
          </div>

          <!-- API Key -->
          <div>
            <label class="block text-xs text-slate-400 mb-1">API Key</label>
            <div class="relative">
              <input v-model="form.api_key" :type="showApiKey ? 'text' : 'password'" placeholder="sk-..."
                class="w-full px-3 py-2 pr-9 bg-surface border border-slate-600 rounded-lg text-sm text-white placeholder-slate-500 focus:border-accent focus:outline-none transition" />
              <button @click="showApiKey = !showApiKey" type="button"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white text-sm"
                tabindex="-1">
                {{ showApiKey ? '🙈' : '👁' }}
              </button>
            </div>
          </div>

```

---

## Task 7: Frontend JS — profiles 数据与方法

**Files:**
- Modify: `cli/static/app.js`

- [ ] **Step 7.1: 在 `data()` 中新增 profiles 相关状态**

找到 `data: function () {` 内 `form:` 对象（约第 91 行），在 `form` 的 `backend_url: '',` 之后加一行：

```javascript
          api_key: '',
```

然后在 `form` 对象之后（在 `running: false,` 之前）新增：

```javascript
        // Profiles state
        profiles: [],                 // Array of { name, created_at, updated_at, config }
        activeProfileName: '',        // Currently selected profile name (matches <select> value)
        profileDirty: false,          // True when form differs from active profile config
        showApiKey: false,            // Toggle for API Key plaintext display
```

- [ ] **Step 7.2: 新增 `computed` 属性**

找到 `computed: {`（约第 126 行），在其中追加两个：

```javascript
      activeProfileConfig: function () {
        var p = this.profiles.find(function (x) { return x.name === this.activeProfileName; }, this);
        return p ? (p.config || {}) : {};
      },
      maskedApiKey: function () {
        var key = this.activeProfileConfig.api_key || '';
        if (!key) return '—';
        if (key.indexOf('•') !== -1) return key;  // already masked by server
        if (key.length < 7) return '•••';
        return key.slice(0, 3) + '••••' + key.slice(-4);
      },
```

- [ ] **Step 7.3: 在 `methods` 中新增 profile 相关方法**

找到 `methods: {`（约第 140 行），在 `onProviderChange:` 方法之后（约第 190 行之后），插入：

```javascript
      // ── Profiles ────────────────────────────────────────────────
      profileEmoji: function (name) {
        if (/家/.test(name)) return '🏠';
        if (/公司|工作/.test(name)) return '🏢';
        if (/本地|ollama/i.test(name)) return '🔬';
        return '⭐';
      },

      loadProfiles: function () {
        var self = this;
        fetch('/api/profiles')
          .then(function (r) { return r.json(); })
          .then(function (data) {
            self.profiles = data.profiles || [];
            var active = data.active || (self.profiles[0] && self.profiles[0].name) || '';
            self.activeProfileName = active;
            self.applyProfileToForm();
          })
          .catch(function (e) { self.addLog('加载配置方案失败: ' + e.message, 'error'); });
      },

      applyProfileToForm: function () {
        var cfg = this.activeProfileConfig;
        if (!cfg || !this.activeProfileName) return;
        if (cfg.llm_provider) this.form.llm_provider = cfg.llm_provider;
        if (cfg.backend_url !== undefined) this.form.backend_url = cfg.backend_url || '';
        // Only fill api_key into form if it's not already masked.
        // Server sends masked keys; real key is injected server-side at run time.
        if (cfg.api_key && cfg.api_key.indexOf('•') === -1) {
          this.form.api_key = cfg.api_key;
        } else {
          this.form.api_key = '';  // don't prefill masked value
        }
        if (cfg.shallow_thinker) this.form.shallow_thinker = cfg.shallow_thinker;
        if (cfg.deep_thinker) this.form.deep_thinker = cfg.deep_thinker;
        if (cfg.output_language) this.form.output_language = cfg.output_language;
        if (cfg.research_depth !== undefined) this.form.research_depth = cfg.research_depth;
        if (cfg.checkpoint !== undefined) this.form.checkpoint = cfg.checkpoint;
        if (cfg.asset_type) this.form.asset_type = cfg.asset_type;
        this.profileDirty = false;
      },

      currentFormAsConfig: function () {
        return {
          llm_provider: this.form.llm_provider,
          backend_url: this.form.backend_url,
          api_key: this.form.api_key,
          shallow_thinker: this.form.shallow_thinker,
          deep_thinker: this.form.deep_thinker,
          output_language: this.form.output_language,
          research_depth: this.form.research_depth,
          checkpoint: this.form.checkpoint,
          asset_type: this.form.asset_type,
        };
      },

      saveProfile: function () {
        var self = this;
        if (!self.activeProfileName) {
          self.addLog('请先选择一个方案或使用「另存为」', 'warn');
          return;
        }
        fetch('/api/profiles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: self.activeProfileName, config: self.currentFormAsConfig() }),
        })
          .then(function (r) {
            if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
            return r.json();
          })
          .then(function () {
            self.addLog('已保存方案: ' + self.activeProfileName);
            self.profileDirty = false;
            self.loadProfiles();
          })
          .catch(function (e) { self.addLog('保存方案失败: ' + e.message, 'error'); });
      },

      saveAsProfile: function () {
        var self = this;
        var name = prompt('输入新方案名称:');
        if (!name || !name.trim()) return;
        name = name.trim();
        // If name already exists, confirm overwrite
        var exists = self.profiles.some(function (p) { return p.name === name; });
        if (exists && !confirm('方案「' + name + '」已存在，是否覆盖？')) return;

        fetch('/api/profiles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name, config: self.currentFormAsConfig() }),
        })
          .then(function (r) {
            if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
            return r.json();
          })
          .then(function () {
            self.activeProfileName = name;
            self.addLog('已创建方案: ' + name);
            self.profileDirty = false;
            self.loadProfiles();
          })
          .catch(function (e) { self.addLog('创建方案失败: ' + e.message, 'error'); });
      },

      deleteProfile: function () {
        var self = this;
        if (!self.activeProfileName) return;
        if (!confirm('确定删除方案「' + self.activeProfileName + '」？此操作不可恢复。')) return;

        fetch('/api/profiles?name=' + encodeURIComponent(self.activeProfileName), {
          method: 'DELETE',
        })
          .then(function (r) {
            if (!r.ok) return r.text().then(function (t) { throw new Error(t); });
            return r.json();
          })
          .then(function (data) {
            self.addLog('已删除方案: ' + self.activeProfileName);
            self.activeProfileName = data.active || '';
            self.loadProfiles();
          })
          .catch(function (e) { self.addLog('删除方案失败: ' + e.message, 'error'); });
      },

      onProfileSwitch: function () {
        var self = this;
        if (self.profileDirty) {
          if (!confirm('当前方案有未保存的改动，切换将丢弃。是否继续？')) {
            // Revert select by re-applying previous name on next tick
            self.$nextTick(function () {
              // Find the previously active profile; fallback to any
              self.activeProfileName = self.profiles[0] ? self.profiles[0].name : '';
            });
            return;
          }
        }
        fetch('/api/profiles/activate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: self.activeProfileName }),
        }).catch(function () { /* ignore; non-critical */ });
        self.applyProfileToForm();
      },

      checkProfileDirty: function () {
        var cfg = this.activeProfileConfig;
        if (!cfg || !this.activeProfileName) {
          this.profileDirty = false;
          return;
        }
        var cur = this.currentFormAsConfig();
        var dirty = false;
        ['llm_provider', 'backend_url', 'shallow_thinker', 'deep_thinker',
         'output_language', 'research_depth', 'checkpoint', 'asset_type'].forEach(function (k) {
          if (cfg[k] !== undefined && cfg[k] !== cur[k]) dirty = true;
        });
        // api_key: only mark dirty if user actually entered one and saved config had none
        if (cur.api_key && !cfg.api_key) dirty = true;
        this.profileDirty = dirty;
      },
```

- [ ] **Step 7.4: 修改 `startAnalysis` 方法**

找到 `startAnalysis: function () {`（约第 462 行），在 `var payload = {` 块中（约第 482 行）新增一个字段：

```javascript
          profile: self.activeProfileName || null,
```

即 payload 对象改为：

```javascript
        var payload = {
          ticker: self.form.ticker.trim().toUpperCase(),
          analysis_date: self.form.analysis_date,
          asset_type: self.form.asset_type || 'stock',
          selected_analysts: ['market', 'social', 'news', 'fundamentals'],
          llm_provider: self.form.llm_provider || 'deepseek',
          backend_url: self.form.backend_url || '',
          shallow_thinker: (self.form.shallow_thinker || '').trim(),
          deep_thinker: (self.form.deep_thinker || '').trim(),
          output_language: self.form.output_language || 'Chinese',
          research_depth: self.form.research_depth || 1,
          checkpoint: !!self.form.checkpoint,
          profile: self.activeProfileName || null,
        };
```

注意：我们**故意不把 `form.api_key` 放进 payload**——真值由后端从 `profiles.json` 读取并注入，避免明文通过 HTTP 发送。

- [ ] **Step 7.5: 在 `mounted` 中调用 `loadProfiles`**

找到 `mounted: function () {`（约第 518 行），在 `self.loadHistory();` 之后追加：

```javascript
      self.loadProfiles();
```

- [ ] **Step 7.6: 在表单字段上添加 `@input` 监听以触发 `checkProfileDirty`**

在 `frontend.html` 的每个表单输入框（标的代码、provider、backend_url、api_key、shallow_thinker、deep_thinker、output_language、research_depth、checkpoint）上添加 `@input="checkProfileDirty"` 或 `@change="checkProfileDirty"`。

找到标的代码输入框（`<input v-model="form.ticker" ...>`），替换为：

```html
<input v-model="form.ticker" @input="checkProfileDirty" type="text" placeholder="NVDA / AAPL / 110022 / BTC-USD"
```

对 provider 下拉，找到 `<select v-model="form.llm_provider" @change="onProviderChange"`，替换为：

```html
<select v-model="form.llm_provider" @change="onProviderChange(); checkProfileDirty()"
```

对 backend_url、shallow_thinker、deep_thinker、api_key 输入框，每个的 `<input v-model="form.X"` 之后追加 `@input="checkProfileDirty"`。

对 output_language、research_depth 下拉，追加 `@change="checkProfileDirty"`。

对 checkpoint，追加 `@change="checkProfileDirty"`。

---

## Task 8: Frontend CSS — 💾 按钮脉动动画

**Files:**
- Modify: `cli/static/style.css`

- [ ] **Step 8.1: 在 `style.css` 末尾追加脉动动画**

打开 `cli/static/style.css`，在文件末尾追加：

```css
/* ── Profile save button pulse ── */
@keyframes pulse-accent {
  0%, 100% { box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.6); }
  50% { box-shadow: 0 0 0 6px rgba(56, 189, 248, 0); }
}
.animate-pulse-accent {
  animation: pulse-accent 1.6s ease-in-out infinite;
}
```

---

## Task 9: 端到端冒烟测试

**Files:**
- 无新文件；手动验证

- [ ] **Step 9.1: 启动服务器**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python webapp.py`

Expected: 服务器启动于 http://localhost:8000

- [ ] **Step 9.2: 在浏览器中打开 `http://localhost:8000`**

Expected:
- 页面加载无报错
- 左侧面板顶部出现「📁 配置方案」区块，显示「➕ 保存当前为新方案」引导按钮（因为 profiles 为空）
- 表单中新增了「API 接入地址」和「API Key」两个输入框

- [ ] **Step 9.3: 创建第一个方案**

- 填写一些配置：LLM 提供商 = DeepSeek、API 接入地址 = `https://api.deepseek.com`、API Key = `sk-test-123456`、深度思考模型 = `deepseek-reasoner`
- 点击「➕ 保存当前为新方案」
- 在 prompt 中输入「家用 DeepSeek」

Expected:
- 提示「已创建方案: 家用 DeepSeek」
- 下拉中出现「🏠 家用 DeepSeek」选项
- 下方小字显示 `🔌 deepseek · 🔑 sk-••••3456 · 🧠 deepseek-reasoner`

- [ ] **Step 9.4: 验证持久化**

- 刷新页面（F5）

Expected:
- 下拉仍显示「🏠 家用 DeepSeek」
- 表单字段自动填充为 DeepSeek 配置
- API Key 输入框为空白（不回填 mask 值）

- [ ] **Step 9.5: 验证文件落盘**

Run: `cat ~/.tradingagents/profiles.json`

Expected: 看到完整的 JSON，包含 `sk-test-123456` 明文（注意 chmod 600）

- [ ] **Step 9.6: 验证 mask**

Run: `curl http://localhost:8000/api/profiles`

Expected: 返回的 `api_key` 字段为 `sk-••••3456`，不含明文

- [ ] **Step 9.7: 验证 `profileDirty` 检测**

- 在页面上修改「研究深度」从 1 改为 3

Expected: 💾 按钮变为蓝色高亮并开始脉动

- 点击 💾 保存

Expected: 按钮恢复正常颜色，`profiles.json` 中 `research_depth` 更新为 3

- [ ] **Step 9.8: 运行全套 pytest 确认无回归**

Run: `cd /Users/mac/Desktop/TradingAgents && .venv/bin/python -m pytest tests/ -x --ignore=tests/test_analyst_execution.py`

Expected: 所有测试 PASS

- [ ] **Step 9.9: 安全加固提示**

Run: `chmod 600 ~/.tradingagents/profiles.json`

Optional: 在 `frontend.html` 方案选择器区块下方加一行小字提示：
```html
<p class="text-[10px] text-slate-600 mt-1">💡 建议: chmod 600 ~/.tradingagents/profiles.json</p>
```

---

## Done

全部 9 个 Task 完成后：

- 后端：4 个新 API 端点（GET/POST/DELETE profiles、POST activate）+ profile 配置注入到 `/api/run` + API Key 按 provider 注入 `os.environ`
- 前端：左侧面板顶部「📁 配置方案」下拉区块，含 💾➕🗑 按钮、mask 预览、💾 脉动；新增 backend_url / api_key 输入框
- 持久化：`~/.tradingagents/profiles.json`
- 测试：`tests/test_profiles_storage.py` 覆盖所有辅助函数和核心逻辑

启动后用户工作流：
1. 第一次使用：点「➕ 保存当前为新方案」→ 输入名字 → 创建
2. 之后：下拉选方案 → 表单自动填充 → 改配置 → 💾 保存
3. 切环境：下拉切到另一个方案 → 整套配置跟着变
