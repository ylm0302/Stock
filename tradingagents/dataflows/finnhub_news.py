import os
from datetime import datetime, timedelta
from typing import Any

import requests

from .config import get_config

API_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubRateLimitError(Exception):
    """Exception raised when Finnhub API rate limit is exceeded."""


def get_api_key() -> str:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise ValueError("FINNHUB_API_KEY environment variable is not set.")
    return api_key


def _format_article(article: dict[str, Any]) -> dict[str, Any]:
    publish_ts = article.get("datetime")
    publish_date = None
    if publish_ts:
        try:
            publish_date = datetime.utcfromtimestamp(int(publish_ts))
        except (TypeError, ValueError):
            publish_date = None

    return {
        "title": article.get("headline", article.get("summary", "No title")),
        "summary": article.get("summary", ""),
        "publisher": article.get("source", "Unknown"),
        "link": article.get("url", ""),
        "pub_date": publish_date,
    }


def _make_request(path: str, params: dict[str, str]) -> list[dict[str, Any]]:
    params = params.copy()
    params["token"] = get_api_key()
    response = requests.get(f"{API_BASE_URL}/{path}", params=params, timeout=15)

    if response.status_code == 429:
        raise FinnhubRateLimitError("Finnhub rate limit exceeded: HTTP 429")

    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(f"Finnhub error: {data.get('error')}")
    return data


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    article_limit = get_config()["news_article_limit"]
    try:
        params = {
            "symbol": ticker,
            "from": start_date,
            "to": end_date,
        }
        raw_articles = _make_request("company-news", params)

        if not raw_articles:
            return f"No news found for {ticker}"

        news_str = ""
        filtered_count = 0
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        for article in raw_articles:
            if filtered_count >= article_limit:
                break
            data = _format_article(article)
            if data["pub_date"]:
                pub_date_naive = data["pub_date"].replace(tzinfo=None)
                if not (start_dt <= pub_date_naive <= end_dt + timedelta(days=1)):
                    continue

            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"
            filtered_count += 1

        if filtered_count == 0:
            return f"No news found for {ticker} between {start_date} and {end_date}"

        return f"## {ticker} News, from {start_date} to {end_date}:\n\n{news_str}"

    except FinnhubRateLimitError:
        raise
    except Exception as e:
        return f"Error fetching news for {ticker}: {str(e)}"


def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 50) -> str:
    try:
        config = get_config()
        if limit is None:
            limit = config["global_news_article_limit"]
        look_back_days = look_back_days or config["global_news_lookback_days"]

        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - timedelta(days=look_back_days)
        params = {
            "category": "general",
            "min_id": "",
        }
        raw_articles = _make_request("news", params)

        if not raw_articles:
            return f"No global news found for {curr_date}"

        news_str = ""
        filtered = 0
        for article in raw_articles:
            if filtered >= limit:
                break
            data = _format_article(article)
            if data["pub_date"]:
                pub_date_naive = data["pub_date"].replace(tzinfo=None)
                if not (start_dt <= pub_date_naive <= curr_dt + timedelta(days=1)):
                    continue

            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"
            filtered += 1

        if filtered == 0:
            return f"No global news found for {curr_date}"

        start_date = start_dt.strftime("%Y-%m-%d")
        return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"

    except FinnhubRateLimitError:
        raise
    except Exception as e:
        return f"Error fetching global news: {str(e)}"
