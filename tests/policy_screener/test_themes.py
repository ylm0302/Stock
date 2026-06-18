import textwrap
from pathlib import Path

import pytest

from tradingagents.policy_screener.themes import ThemeConfig, load_themes


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "policy_themes.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_load_themes_parses_valid_file(tmp_path):
    p = _write_yaml(tmp_path, """
        themes:
          新质生产力:
            keywords: ["半导体", "人工智能"]
            sectors: ["半导体"]
            funds: ["159995"]
          低空经济:
            keywords: ["低空经济"]
            sectors: ["低空经济"]
            funds: []
    """)
    cfg = load_themes(str(p), enabled=[])
    assert isinstance(cfg, ThemeConfig)
    names = cfg.enabled_theme_names()
    assert "新质生产力" in names
    assert "低空经济" in names


def test_enabled_filter_restricts_themes(tmp_path):
    p = _write_yaml(tmp_path, """
        themes:
          A:
            keywords: ["a"]
            sectors: ["a"]
            funds: []
          B:
            keywords: ["b"]
            sectors: ["b"]
            funds: []
    """)
    cfg = load_themes(str(p), enabled=["A"])
    assert cfg.enabled_theme_names() == ["A"]


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_themes(str(tmp_path / "nope.yaml"), enabled=[])


def test_missing_top_level_themes_key_raises(tmp_path):
    p = _write_yaml(tmp_path, """
        wrong_key: {}
    """)
    with pytest.raises(ValueError, match="缺少顶级 'themes' 键"):
        load_themes(str(p), enabled=[])


def test_theme_missing_required_field_raises(tmp_path):
    p = _write_yaml(tmp_path, """
        themes:
          半导体:
            keywords: ["半导体"]
            # 缺 sectors
            funds: []
    """)
    with pytest.raises(ValueError, match="缺少字段 'sectors'"):
        load_themes(str(p), enabled=[])


def test_get_theme_returns_config():
    cfg = ThemeConfig({
        "半导体": {"keywords": ["k"], "sectors": ["s"], "funds": ["f"]},
    })
    t = cfg.get_theme("半导体")
    assert t["sectors"] == ["s"]


def test_get_theme_unknown_raises():
    cfg = ThemeConfig({"半导体": {"keywords": ["k"], "sectors": ["s"], "funds": []}})
    with pytest.raises(KeyError):
        cfg.get_theme("不存在")


def test_theme_non_list_field_raises(tmp_path):
    """字段写成字符串（非列表）应报错。"""
    p = _write_yaml(tmp_path, """
        themes:
          半导体:
            keywords: "半导体"     # 应为列表，这里故意写成字符串
            sectors: ["半导体"]
            funds: []
    """)
    with pytest.raises(ValueError, match="必须是列表"):
        load_themes(str(p), enabled=[])


def test_enabled_unknown_name_raises(tmp_path):
    """enabled 中传入不存在的主题名应报错。"""
    p = _write_yaml(tmp_path, """
        themes:
          A:
            keywords: ["a"]
            sectors: ["a"]
            funds: []
    """)
    with pytest.raises(ValueError, match="未知主题"):
        load_themes(str(p), enabled=["不存在"])
