"""Tests for profiles storage helpers in webapp."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture()
def profiles_module(tmp_path, monkeypatch):
    """Import webapp with PROFILES_PATH redirected to a tmp directory."""
    import importlib
    import webapp as webapp_module

    fake_path = tmp_path / "profiles.json"
    monkeypatch.setattr(webapp_module, "PROFILES_PATH", fake_path)
    yield webapp_module
    importlib.reload(webapp_module)


# ---- mask_api_key ---------------------------------------------------------


def test_mask_short_key(profiles_module):
    assert profiles_module.mask_api_key("sk-abcdef") == "sk-••••cdef"


def test_mask_typical_key(profiles_module):
    assert profiles_module.mask_api_key("sk-test000000000000000000000000000000") == "sk-••••0000"


def test_mask_very_short_key(profiles_module):
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


def test_load_profiles_corrupted_json_returns_empty(profiles_module):
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
    assert result["profiles"][0]["created_at"] == 1.0
    assert result["profiles"][0]["updated_at"] > 1.0


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
    assert result == data


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
    config = {"llm_provider": "ollama", "api_key": "ignored"}
    profiles_module.apply_profile_to_environ(config)  # no exception


def test_apply_profile_skips_missing_key_field(profiles_module, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = {"llm_provider": "anthropic"}
    profiles_module.apply_profile_to_environ(config)
    assert "ANTHROPIC_API_KEY" not in os.environ


# ---- GET /api/profiles (mask helper) -----------------------------------


def test_get_profiles_empty(profiles_module):
    """GET returns empty list when no file exists."""
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
    assert reloaded["profiles"][0]["created_at"] == 1.0


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


# ---- apply_profile_to_environ: azure, missing provider --------------


def test_apply_profile_azure_injects_api_key(profiles_module, monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    config = {"llm_provider": "azure", "api_key": "azure-key-123"}
    profiles_module.apply_profile_to_environ(config)
    assert os.environ.get("AZURE_OPENAI_API_KEY") == "azure-key-123"


def test_apply_profile_unknown_provider_no_injection(profiles_module, monkeypatch):
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
