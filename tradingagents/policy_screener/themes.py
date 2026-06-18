"""政策主题映射表加载与校验。

映射表为 YAML 文件，结构见 data/policy_themes.yaml。
表缺失或格式错误是硬依赖故障，直接抛异常终止。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

# 每个主题必须包含的字段
_REQUIRED_FIELDS = ("keywords", "sectors", "funds")


class ThemeConfig:
    """已加载并校验的主题映射表。"""

    def __init__(self, themes: Dict[str, dict]):
        self._themes = themes

    def enabled_theme_names(self) -> List[str]:
        """返回全部主题名（enabled 过滤已在 load_themes 完成）。"""
        return list(self._themes.keys())

    def get_theme(self, name: str) -> dict:
        """取单个主题配置；不存在则 KeyError。"""
        if name not in self._themes:
            raise KeyError(f"未知主题: {name}")
        return self._themes[name]

    def all_themes(self) -> Dict[str, dict]:
        return self._themes


def _validate(theme_name: str, theme: dict) -> None:
    if not isinstance(theme, dict):
        raise ValueError(f"主题 '{theme_name}' 不是映射")
    for field in _REQUIRED_FIELDS:
        if field not in theme:
            raise ValueError(f"主题 '{theme_name}' 缺少字段 '{field}'")
        if not isinstance(theme[field], list):
            raise ValueError(f"主题 '{theme_name}' 字段 '{field}' 必须是列表")


def load_themes(path: str, enabled: List[str]) -> ThemeConfig:
    """加载并校验主题表。

    Args:
        path: YAML 文件路径。
        enabled: 启用的主题名列表；空列表表示启用全部。

    Returns:
        校验后的 ThemeConfig（仅含启用主题）。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 格式错误或缺字段。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"主题映射表不存在: {path}")

    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "themes" not in data:
        raise ValueError(f"主题表 {path} 缺少顶级 'themes' 键")

    all_themes = data["themes"]
    if not isinstance(all_themes, dict):
        raise ValueError(f"主题表 {path} 的 'themes' 必须是映射")

    # 校验全部主题（即便未启用，格式错也要尽早暴露）
    for name, theme in all_themes.items():
        _validate(name, theme)

    # 按 enabled 过滤；空列表 = 全部启用
    if enabled:
        unknown = [n for n in enabled if n not in all_themes]
        if unknown:
            raise ValueError(f"启用了未知主题: {unknown}")
        selected = {n: all_themes[n] for n in enabled}
    else:
        selected = all_themes

    return ThemeConfig(selected)
