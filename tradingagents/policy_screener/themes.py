"""政策板块 / 主题映射表加载与校验。

支持两种 YAML 格式：
  - 新版：categories（大类）→ boards（板块列表），每个板块含 board/keywords/funds。
  - 旧版：themes（主题名 → keywords/sectors/funds），向下兼容。

表缺失或格式错误是硬依赖故障，直接抛异常终止。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


class BoardInfo:
    """单个板块/主题的配置。"""

    def __init__(self, name: str, keywords: List[str], sectors: List[str], funds: List[str], category: str = ""):
        self.name = name          # 板块名（如 "半导体"）
        self.keywords = keywords  # 模糊匹配关键词
        self.sectors = sectors    # 对应的东财板块名列表（至少含 name 自身）
        self.funds = funds        # 关联 ETF/基金代码
        self.category = category  # 所属大类（如 "科技/半导体/通信"），旧格式为空


class BoardConfig:
    """已加载并校验的板块/主题映射表。"""

    def __init__(self):
        # 板块名 → BoardInfo
        self._boards: Dict[str, BoardInfo] = {}
        # 大类名 → [板块名列表]
        self._categories: Dict[str, List[str]] = {}

    def add_board(self, info: BoardInfo) -> None:
        self._boards[info.name] = info
        cat = info.category or "其他"
        if cat not in self._categories:
            self._categories[cat] = []
        self._categories[cat].append(info.name)

    def enabled_board_names(self) -> List[str]:
        """返回全部板块名。"""
        return list(self._boards.keys())

    def get_board(self, name: str) -> BoardInfo:
        """取单个板块配置；不存在则 KeyError。"""
        if name not in self._boards:
            raise KeyError(f"未知板块: {name}")
        return self._boards[name]

    def all_boards(self) -> Dict[str, BoardInfo]:
        return self._boards

    def all_categories(self) -> Dict[str, List[str]]:
        """返回 {大类名: [板块名列表]}。"""
        return dict(self._categories)

    # ---- 兼容旧 ThemeConfig API ----
    def enabled_theme_names(self) -> List[str]:
        return self.enabled_board_names()

    def get_theme(self, name: str) -> dict:
        b = self.get_board(name)
        return {"keywords": b.keywords, "sectors": b.sectors, "funds": b.funds}

    def all_themes(self) -> dict:
        return {n: {"keywords": b.keywords, "sectors": b.sectors, "funds": b.funds} for n, b in self._boards.items()}


# ── 新版格式校验 ──────────────────────────────────────────────────────

def _validate_board(name: str, board: dict) -> None:
    if not isinstance(board, dict):
        raise ValueError(f"板块 '{name}' 不是映射")
    for field in ("board", "keywords"):
        if field not in board:
            raise ValueError(f"板块 '{name}' 缺少字段 '{field}'")
        if not isinstance(board[field], (str, list)):
            raise ValueError(f"板块 '{name}' 字段 '{field}' 必须是字符串或列表")
    if "funds" in board and not isinstance(board["funds"], list):
        raise ValueError(f"板块 '{name}' 字段 'funds' 必须是列表")


def _load_categories_format(data: dict, enabled: List[str]) -> BoardConfig:
    """加载新版 categories 格式。"""
    config = BoardConfig()
    all_categories = data["categories"]
    if not isinstance(all_categories, dict):
        raise ValueError("'categories' 必须是映射")

    for cat_name, boards in all_categories.items():
        if not isinstance(boards, list):
            raise ValueError(f"大类 '{cat_name}' 下的板块必须是列表")
        for board in boards:
            board_name = board.get("board", "")
            if not board_name:
                raise ValueError(f"大类 '{cat_name}' 下板块缺少 'board' 字段")
            _validate_board(board_name, board)

            # enabled 过滤：按板块名匹配
            if enabled and board_name not in enabled:
                continue

            info = BoardInfo(
                name=board_name,
                keywords=list(board.get("keywords", [])),
                sectors=[board_name],  # sectors 默认 = 板块名自身
                funds=list(board.get("funds", [])),
                category=cat_name,
            )
            config.add_board(info)

    return config


# ── 旧版格式校验（兼容） ──────────────────────────────────────────────

def _validate_theme(name: str, theme: dict) -> None:
    if not isinstance(theme, dict):
        raise ValueError(f"主题 '{name}' 不是映射")
    for field in ("keywords", "sectors", "funds"):
        if field not in theme:
            raise ValueError(f"主题 '{name}' 缺少字段 '{field}'")
        if not isinstance(theme[field], list):
            raise ValueError(f"主题 '{name}' 字段 '{field}' 必须是列表")


def _load_themes_format(data: dict, enabled: List[str]) -> BoardConfig:
    """加载旧版 themes 格式（兼容）。"""
    config = BoardConfig()
    all_themes = data["themes"]
    if not isinstance(all_themes, dict):
        raise ValueError("'themes' 必须是映射")

    for name, theme in all_themes.items():
        _validate_theme(name, theme)
        if enabled and name not in enabled:
            continue
        info = BoardInfo(
            name=name,
            keywords=list(theme.get("keywords", [])),
            sectors=list(theme.get("sectors", [])),
            funds=list(theme.get("funds", [])),
            category="",
        )
        config.add_board(info)

    return config


# ── 统一入口 ──────────────────────────────────────────────────────────

def load_board_config(path: str, enabled: List[str] = None) -> BoardConfig:
    """加载新版板块映射表。"""
    if enabled is None:
        enabled = []
    return _load_board_file(path, enabled)


def load_board_file(path: str, enabled: List[str]) -> BoardConfig:
    return _load_board_file(path, enabled)


def _load_board_file(path: str, enabled: List[str]) -> BoardConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"板块映射表不存在: {path}")

    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"板块表 {path} 格式错误")

    # 自动检测格式
    if "categories" in data:
        return _load_categories_format(data, enabled)
    if "themes" in data:
        return _load_themes_format(data, enabled)

    raise ValueError(f"板块表 {path} 缺少顶级 'categories' 或 'themes' 键")


# ── 兼容旧 API ────────────────────────────────────────────────────────

ThemeConfig = BoardConfig  # 类型别名


def load_themes(path: str, enabled: List[str]) -> BoardConfig:
    """兼容旧 API，加载主题/板块映射表。"""
    return _load_board_file(path, enabled)