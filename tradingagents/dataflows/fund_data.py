"""
基金数据接口模块
优先使用雪球（XQ）接口，稳定性高，不依赖 mini_racer JS 引擎。
东方财富（EM）接口作为补充，仅用于净值历史和持仓数据。

依赖：akshare >= 1.10.0
安装：pip install akshare
"""

from __future__ import annotations

import warnings
from datetime import datetime
from typing import Optional

try:
    import akshare as ak
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False
    warnings.warn(
        "akshare 未安装，基金数据功能不可用。请运行: pip install akshare",
        ImportWarning,
        stacklevel=2,
    )

import pandas as pd


def _check_akshare():
    if not _AKSHARE_AVAILABLE:
        return "错误：akshare 未安装，无法获取基金数据。请运行 `pip install akshare` 后重试。"
    return None


# ---------------------------------------------------------------------------
# 基金基本信息（雪球接口，稳定）
# ---------------------------------------------------------------------------

def get_fund_info(fund_code: str, curr_date: Optional[str] = None) -> str:
    """获取基金基本信息：名称、类型、成立日期、基金公司等。"""
    err = _check_akshare()
    if err:
        return err
    try:
        df = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if df is None or df.empty:
            return f"未找到基金 {fund_code} 的基本信息"
        lines = [f"# 基金基本信息 — {fund_code}",
                 f"# 数据获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
        for _, row in df.iterrows():
            key = str(row.iloc[0]) if len(row) > 0 else ""
            val = str(row.iloc[1]) if len(row) > 1 else ""
            if key and val not in ("nan", "None", ""):
                lines.append(f"{key}: {val}")
        return "\n".join(lines)
    except Exception as e:
        return f"获取基金 {fund_code} 基本信息失败: {str(e)}"


# ---------------------------------------------------------------------------
# 基金净值历史（直接 HTTP，不经过 mini_racer）
# ---------------------------------------------------------------------------

def get_fund_nav_history(
    fund_code: str,
    start_date: str,
    end_date: str,
) -> str:
    """获取基金净值历史（单位净值 + 日增长率），直接调用天天基金 API。"""
    err = _check_akshare()
    if err:
        return err
    try:
        import requests
        all_records = []
        page = 1
        while True:
            url = "https://api.fund.eastmoney.com/f10/lsjz"
            params = {
                "fundCode": fund_code,
                "pageIndex": page,
                "pageSize": 200,
                "startDate": start_date,
                "endDate": end_date,
                "_": "1234567890",
            }
            headers = {
                "Referer": "https://fundf10.eastmoney.com/",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            }
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            data = resp.json()
            records = data.get("Data", {}).get("LSJZList", [])
            if not records:
                break
            all_records.extend(records)
            total_count = data.get("TotalCount", 0)
            if len(all_records) >= total_count:
                break
            page += 1

        if not all_records:
            return f"基金 {fund_code} 在 {start_date} 至 {end_date} 期间无净值数据"

        rows = []
        for r in all_records:
            rows.append({
                "净值日期": r.get("FSRQ", ""),
                "单位净值": r.get("DWJZ", ""),
                "日增长率": r.get("JZZZL", ""),
                "申购状态": r.get("SGZT", ""),
                "赎回状态": r.get("SHZT", ""),
            })
        df = pd.DataFrame(rows)
        df = df.sort_values("净值日期")

        header = f"# 基金净值历史 — {fund_code} ({start_date} 至 {end_date})\n"
        header += f"# 共 {len(df)} 条记录\n\n"
        return header + df.to_csv(index=False)
    except Exception as e:
        return f"获取基金 {fund_code} 净值历史失败: {str(e)}"


# ---------------------------------------------------------------------------
# 基金持仓（东方财富接口，稳定）
# ---------------------------------------------------------------------------

def get_fund_portfolio(fund_code: str, curr_date: Optional[str] = None) -> str:
    """获取基金最新持仓（前十大重仓股/债券）。"""
    err = _check_akshare()
    if err:
        return err
    result_parts = []
    try:
        # 取最近年份
        year = str(datetime.now().year - 1) if datetime.now().month <= 4 else str(datetime.now().year)
        df_stock = ak.fund_portfolio_hold_em(symbol=fund_code, date=year)
        if df_stock is not None and not df_stock.empty:
            # 只取最新一期（最大季度）
            if "季度" in df_stock.columns:
                latest_q = df_stock["季度"].max()
                df_stock = df_stock[df_stock["季度"] == latest_q]
            result_parts.append(f"## 前十大重仓股（最新季报）\n" + df_stock.head(10).to_csv(index=False))
    except Exception as e:
        result_parts.append(f"## 股票持仓获取失败: {str(e)}")
    try:
        year = str(datetime.now().year - 1) if datetime.now().month <= 4 else str(datetime.now().year)
        df_bond = ak.fund_portfolio_bond_hold_em(symbol=fund_code, date=year)
        if df_bond is not None and not df_bond.empty:
            if "季度" in df_bond.columns:
                latest_q = df_bond["季度"].max()
                df_bond = df_bond[df_bond["季度"] == latest_q]
            result_parts.append(f"## 前五大重仓债券（最新季报）\n" + df_bond.head(5).to_csv(index=False))
    except Exception:
        pass
    # 补充雪球资产配置
    try:
        df_hold = ak.fund_individual_detail_hold_xq(symbol=fund_code)
        if df_hold is not None and not df_hold.empty:
            result_parts.append(f"## 资产配置比例（雪球）\n" + df_hold.to_csv(index=False))
    except Exception:
        pass
    if not result_parts:
        return f"未找到基金 {fund_code} 的持仓数据"
    header = f"# 基金持仓 — {fund_code}\n# 数据获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + "\n\n".join(result_parts)


# ---------------------------------------------------------------------------
# 基金业绩指标（雪球接口，稳定）
# ---------------------------------------------------------------------------

def get_fund_performance(fund_code: str, curr_date: Optional[str] = None) -> str:
    """获取基金业绩指标：各期收益率、最大回撤、夏普比率、同类排名。"""
    err = _check_akshare()
    if err:
        return err
    lines = [f"# 基金业绩指标 — {fund_code}",
             f"# 数据获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    # 年度业绩和同类排名
    try:
        df_ach = ak.fund_individual_achievement_xq(symbol=fund_code)
        if df_ach is not None and not df_ach.empty:
            lines.append("## 各期业绩与同类排名")
            lines.append(df_ach.to_csv(index=False))
    except Exception as e:
        lines.append(f"业绩数据获取失败: {str(e)}")
    # 风险收益分析（夏普、最大回撤、波动率）
    try:
        df_ana = ak.fund_individual_analysis_xq(symbol=fund_code)
        if df_ana is not None and not df_ana.empty:
            lines.append("\n## 风险收益分析（夏普比率/最大回撤/波动率）")
            lines.append(df_ana.to_csv(index=False))
    except Exception as e:
        lines.append(f"风险分析数据获取失败: {str(e)}")
    # 盈利概率
    try:
        df_prob = ak.fund_individual_profit_probability_xq(symbol=fund_code)
        if df_prob is not None and not df_prob.empty:
            lines.append("\n## 持有盈利概率")
            lines.append(df_prob.to_csv(index=False))
    except Exception:
        pass
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 基金经理信息（雪球接口，稳定）
# ---------------------------------------------------------------------------

def get_fund_manager(fund_code: str, curr_date: Optional[str] = None) -> str:
    """获取基金经理信息及历史业绩。"""
    err = _check_akshare()
    if err:
        return err
    lines = [f"# 基金经理信息 — {fund_code}",
             f"# 数据获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    # 基本信息中包含基金经理字段
    try:
        df_info = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if df_info is not None and not df_info.empty:
            manager_rows = df_info[df_info.iloc[:, 0].astype(str).str.contains("经理|管理人", na=False)]
            if not manager_rows.empty:
                lines.append("## 基金经理（来自基本信息）")
                for _, row in manager_rows.iterrows():
                    lines.append(f"{row.iloc[0]}: {row.iloc[1]}")
    except Exception:
        pass
    # 基金经理历史业绩（雪球）
    try:
        df_mgr = ak.fund_individual_achievement_xq(symbol=fund_code)
        if df_mgr is not None and not df_mgr.empty:
            lines.append("\n## 基金历史业绩（含基金经理任职期间）")
            lines.append(df_mgr.to_csv(index=False))
    except Exception as e:
        lines.append(f"基金经理业绩数据获取失败: {str(e)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 基金资产配置（雪球接口，稳定）
# ---------------------------------------------------------------------------

def get_fund_asset_allocation(fund_code: str, curr_date: Optional[str] = None) -> str:
    """获取基金资产配置比例（股票/债券/现金/其他）。"""
    err = _check_akshare()
    if err:
        return err
    lines = [f"# 基金资产配置 — {fund_code}",
             f"# 数据获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    try:
        df = ak.fund_individual_detail_hold_xq(symbol=fund_code)
        if df is not None and not df.empty:
            lines.append("## 当前资产配置比例")
            lines.append(df.to_csv(index=False))
    except Exception as e:
        lines.append(f"资产配置数据获取失败: {str(e)}")
    # 补充风险分析中的波动率信息
    try:
        df_ana = ak.fund_individual_analysis_xq(symbol=fund_code)
        if df_ana is not None and not df_ana.empty:
            lines.append("\n## 风险特征（波动率/最大回撤）")
            lines.append(df_ana.to_csv(index=False))
    except Exception:
        pass
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 基金费率（雪球接口，稳定）
# ---------------------------------------------------------------------------

def get_fund_fee(fund_code: str) -> str:
    """获取基金费率信息：申购费、赎回费、管理费等。"""
    err = _check_akshare()
    if err:
        return err
    try:
        df = ak.fund_individual_detail_info_xq(symbol=fund_code)
        if df is None or df.empty:
            return f"未找到基金 {fund_code} 的费率信息"
        header = f"# 基金费率 — {fund_code}\n# 数据获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return header + df.to_csv(index=False)
    except Exception as e:
        return f"获取基金 {fund_code} 费率信息失败: {str(e)}"


# ---------------------------------------------------------------------------
# 同类基金比较（雪球接口，稳定）
# ---------------------------------------------------------------------------

def get_fund_comparison(fund_code: str, curr_date: Optional[str] = None) -> str:
    """获取同类基金排名和风险收益比较。"""
    err = _check_akshare()
    if err:
        return err
    lines = [f"# 同类基金比较 — {fund_code}",
             f"# 数据获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    try:
        df_ach = ak.fund_individual_achievement_xq(symbol=fund_code)
        if df_ach is not None and not df_ach.empty:
            lines.append("## 各期业绩与同类排名")
            lines.append(df_ach.to_csv(index=False))
    except Exception as e:
        lines.append(f"同类排名数据获取失败: {str(e)}")
    try:
        df_ana = ak.fund_individual_analysis_xq(symbol=fund_code)
        if df_ana is not None and not df_ana.empty:
            lines.append("\n## 较同类风险收益比较")
            lines.append(df_ana.to_csv(index=False))
    except Exception:
        pass
    try:
        df_prob = ak.fund_individual_profit_probability_xq(symbol=fund_code)
        if df_prob is not None and not df_prob.empty:
            lines.append("\n## 持有盈利概率（与同类比较参考）")
            lines.append(df_prob.to_csv(index=False))
    except Exception:
        pass
    return "\n".join(lines)
