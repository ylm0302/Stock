import copy
import unittest
from unittest.mock import patch

import tradingagents.default_config as default_config
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.finnhub_news import FinnhubRateLimitError
from tradingagents.dataflows.stockstats_utils import YFRateLimitError


class DataflowsInterfaceFallbackTests(unittest.TestCase):
    def setUp(self):
        set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))

    def test_route_to_vendor_falls_back_from_yfinance_rate_limit_to_alpha_vantage(self):
        def failing_yfinance(*args, **kwargs):
            raise YFRateLimitError()

        def fallback_alpha(*args, **kwargs):
            return "alpha news fallback"

        with patch.dict(
            "tradingagents.dataflows.interface.VENDOR_METHODS",
            {
                "get_news": {
                    "yfinance": failing_yfinance,
                    "alpha_vantage": fallback_alpha,
                }
            },
        ):
            set_config({"tool_vendors": {"get_news": "yfinance"}})
            result = route_to_vendor("get_news", "AAPL", "2024-01-01", "2024-01-31")

        self.assertEqual(result, "alpha news fallback")

    def test_route_to_vendor_uses_finnhub_for_news_when_configured(self):
        def finnhub_news(*args, **kwargs):
            return "finnhub news"

        with patch.dict(
            "tradingagents.dataflows.interface.VENDOR_METHODS",
            {
                "get_news": {
                    "finnhub": finnhub_news,
                }
            },
        ):
            set_config({"tool_vendors": {"get_news": "finnhub"}})
            result = route_to_vendor("get_news", "AAPL", "2024-01-01", "2024-01-31")

        self.assertEqual(result, "finnhub news")

    def test_route_to_vendor_falls_back_from_finnhub_rate_limit_to_alpha_vantage(self):
        def failing_finnhub(*args, **kwargs):
            raise FinnhubRateLimitError()

        def fallback_alpha(*args, **kwargs):
            return "alpha news fallback"

        with patch.dict(
            "tradingagents.dataflows.interface.VENDOR_METHODS",
            {
                "get_news": {
                    "finnhub": failing_finnhub,
                    "alpha_vantage": fallback_alpha,
                }
            },
        ):
            set_config({"tool_vendors": {"get_news": "finnhub"}})
            result = route_to_vendor("get_news", "AAPL", "2024-01-01", "2024-01-31")

        self.assertEqual(result, "alpha news fallback")
