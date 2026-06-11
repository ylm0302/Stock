"""AkShare-based news data fetching for Chinese A-share markets."""

import time
from datetime import datetime, timedelta
from typing import Optional

from .config import get_config


class AkshareRateLimitError(Exception):
    """Raised when AkShare underlying sources are unavailable or blocking requests."""


def _strip_ticker(ticker: str) -> str:
    """Extract the bare 6-digit A-share code from a ticker string.

    >>> _strip_ticker("600036.SS")
    '600036'
    >>> _strip_ticker("000001.SZ")
    '000001'
    """
    for suffix in (".SS", ".SZ"):
        if ticker.endswith(suffix):
            return ticker[: -len(suffix)]
    return ticker


def _is_a_share(ticker: str) -> bool:
    """Check if the ticker is an A-share stock (.SS = Shanghai, .SZ = Shenzhen)."""
    return ticker.endswith(".SS") or ticker.endswith(".SZ")


def _emit_article_md(title: str, source: str, content: str = "", link: str = "") -> str:
    """Format a single news article as Markdown."""
    md = f"### {title} (source: {source})\n"
    if content:
        md += f"{content}\n"
    if link:
        md += f"Link: {link}\n"
    md += "\n"
    return md


def _parse_akshare_date(date_str: str) -> Optional[datetime]:
    """Parse AkShare date string to datetime.  Format: ``YYYY-MM-DD HH:MM:SS``."""
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str).strip(), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _detect_rate_limit_error(exception: Exception) -> bool:
    """Heuristic: detect if an exception is a rate-limiting / blocking event."""
    msg = str(exception).lower()
    indicators = (
        "429", "too many requests", "rate limit", "connection refused",
        "connection reset", "timed out", "timeout", "service unavailable",
        "503", "blocked", "forbidden", "403",
    )
    return any(ind in msg for ind in indicators)


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    """Retrieve A-share news for *ticker* via Eastmoney.

    Args:
        ticker: A-share ticker with suffix (e.g. ``"600036.SS"``).
        start_date: Start date in ``yyyy-mm-dd`` format.
        end_date: End date in ``yyyy-mm-dd`` format.

    Returns:
        Formatted Markdown string of news articles.
    """
    import akshare as ak

    if not _is_a_share(ticker):
        return (
            f"AkShare only supports A-share tickers (.SS / .SZ). "
            f"'{ticker}' is not an A-share ticker."
        )

    config = get_config()
    article_limit = config["news_article_limit"]

    symbol = _strip_ticker(ticker)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    try:
        time.sleep(0.5)
        df = ak.stock_news_em(symbol=symbol)

        if df is None or df.empty:
            return f"No news found for {ticker}"

        news_md = ""
        filtered_count = 0

        for _, row in df.iterrows():
            if filtered_count >= article_limit:
                break

            pub_date = _parse_akshare_date(row.get("发布时间", ""))
            if pub_date:
                if not (start_dt <= pub_date <= end_dt + timedelta(days=1)):
                    continue

            title = str(row.get("新闻标题", "No title"))
            content = str(row.get("新闻内容", ""))
            source = str(row.get("文章来源", "Unknown"))
            link = str(row.get("新闻链接", ""))

            news_md += _emit_article_md(title, source, content, link)
            filtered_count += 1

        if filtered_count == 0:
            return f"No news found for {ticker} between {start_date} and {end_date}"

        return f"## {ticker} News, from {start_date} to {end_date}:\n\n{news_md}"

    except AkshareRateLimitError:
        raise
    except Exception as e:
        if _detect_rate_limit_error(e):
            raise AkshareRateLimitError(str(e)) from e
        return f"Error fetching news for {ticker}: {str(e)}"


def get_global_news(
    curr_date: str,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Retrieve Chinese macro / market news headlines via Caixin.

    Args:
        curr_date: Current date in ``yyyy-mm-dd`` format.
        look_back_days: Ignored (Caixin headlines have no date field).
        limit: Maximum articles to return.  Falls back to
            ``global_news_article_limit`` from config.

    Returns:
        Formatted Markdown string of market headlines.
    """
    import akshare as ak

    config = get_config()
    if limit is None:
        limit = config["global_news_article_limit"]

    try:
        time.sleep(0.5)
        df = ak.stock_news_main_cx()

        if df is None or df.empty:
            return f"No global news found for {curr_date}"

        news_md = ""
        count = 0

        for _, row in df.iterrows():
            if count >= limit:
                break

            tag = str(row.get("tag", ""))
            summary = str(row.get("summary", ""))
            url = str(row.get("url", ""))

            source_label = f"财新·{tag}" if tag else "财新"
            news_md += _emit_article_md(summary, source_label, link=url)
            count += 1

        if count == 0:
            return f"No global news found for {curr_date}"

        return f"## Chinese Market News（财新数据通）, {curr_date}:\n\n{news_md}"

    except AkshareRateLimitError:
        raise
    except Exception as e:
        if _detect_rate_limit_error(e):
            raise AkshareRateLimitError(str(e)) from e
        return f"Error fetching global news: {str(e)}"