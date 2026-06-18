import textwrap
from pathlib import Path

import pytest

from tradingagents.policy_screener.themes import (
    BoardConfig,
    load_themes,
    load_board_config,
)


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "sector_boards.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ── 新版 categories 格式 ────────────────────────────────────────

def test_load_categories_parses(tmp_path):
    p = _write_yaml(tmp_path, """
        categories:
          科技:
            - board: 半导体
              keywords: ["芯片"]
              funds: ["159995"]
            - board: 通信设备
              keywords: ["5G"]
              funds: []
    """)
    cfg = load_themes(str(p), enabled=[])
    assert isinstance(cfg, BoardConfig)
    names = cfg.enabled_board_names()
    assert "半导体" in names and "通信设备" in names


def test_categories_structure(tmp_path):
    p = _write_yaml(tmp_path, """
        categories:
          科技:
            - board: 半导体
              keywords: ["芯片"]
              funds: []
    """)
    cfg = load_themes(str(p), enabled=[])
    cats = cfg.all_categories()
    assert "科技" in cats
    assert cats["科技"] == ["半导体"]


def test_get_board_returns_info(tmp_path):
    p = _write_yaml(tmp_path, """
        categories:
          科技:
            - board: 半导体
              keywords: ["芯片", "集成电路"]
              funds: ["159995"]
    """)
    cfg = load_themes(str(p), enabled=[])
    b = cfg.get_board("半导体")
    assert b.keywords == ["芯片", "集成电路"]
    assert b.funds == ["159995"]
    assert b.category == "科技"
    assert b.sectors == ["半导体"]


def test_enabled_filter_by_board_name(tmp_path):
    p = _write_yaml(tmp_path, """
        categories:
          科技:
            - board: A
              keywords: ["a"]
              funds: []
            - board: B
              keywords: ["b"]
              funds: []
    """)
    cfg = load_themes(str(p), enabled=["A"])
    assert cfg.enabled_board_names() == ["A"]


def test_enabled_unknown_board_silently_ignored(tmp_path):
    """未知板块名在 enabled 中不报错，只是没匹配上。"""
    p = _write_yaml(tmp_path, """
        categories:
          科技:
            - board: A
              keywords: ["a"]
              funds: []
    """)
    cfg = load_themes(str(p), enabled=["不存在"])
    assert cfg.enabled_board_names() == []


def test_board_missing_keyword_raises(tmp_path):
    p = _write_yaml(tmp_path, """
        categories:
          科技:
            - board: 半导体
              funds: []
    """)
    with pytest.raises(ValueError, match="缺少字段 'keywords'"):
        load_themes(str(p), enabled=[])


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_themes(str(tmp_path / "nope.yaml"), enabled=[])


def test_missing_top_level_key_raises(tmp_path):
    p = _write_yaml(tmp_path, """
        wrong_key: {}
    """)
    with pytest.raises(ValueError, match="缺少顶级 'categories' 或 'themes'"):
        load_themes(str(p), enabled=[])


# ── 旧版 themes 格式兼容 ────────────────────────────────────────

def test_legacy_themes_format_still_works(tmp_path):
    p = tmp_path / "legacy.yaml"
    p.write_text(textwrap.dedent("""
        themes:
          新质生产力:
            keywords: ["半导体"]
            sectors: ["半导体"]
            funds: ["159995"]
    """), encoding="utf-8")
    cfg = load_themes(str(p), enabled=[])
    assert "新质生产力" in cfg.enabled_board_names()
    b = cfg.get_board("新质生产力")
    assert b.sectors == ["半导体"]


def test_load_board_config_alias(tmp_path):
    """load_board_config 是 load_themes 的别名入口。"""
    p = _write_yaml(tmp_path, """
        categories:
          A:
            - board: X
              keywords: ["x"]
              funds: []
    """)
    cfg = load_board_config(str(p))
    assert "X" in cfg.enabled_board_names()
