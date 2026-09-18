"""StockSense 離線測試（不需要網路，使用合成資料）。

執行方式：
    python tests/test_stocksense.py
    python -m unittest discover tests
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT / "backend"), str(ROOT / "api"), str(ROOT / "models")):
    if path not in sys.path:
        sys.path.insert(0, path)

import numpy as np  # noqa: E402

import forecast as forecast_engine  # noqa: E402
import indicators as indicator_engine  # noqa: E402
import signals as signal_engine  # noqa: E402
import symbols as symbol_utils  # noqa: E402


def make_prices(values, start_volume: int = 1_000_000) -> list[dict]:
    """把收盤價序列轉成 API 格式的價格列表。"""
    prices = []
    for index, value in enumerate(values):
        close = float(value)
        prices.append({
            "date": f"2025-01-{(index % 28) + 1:02d}",
            "open": round(close * 0.995, 2),
            "high": round(close * 1.01, 2),
            "low": round(close * 0.99, 2),
            "close": round(close, 2),
            "volume": start_volume + index * 1000,
        })
    return prices


def trending_series(n=300, slope=0.3, noise=0.5, seed=42, base=100.0):
    rng = np.random.default_rng(seed)
    return base + slope * np.arange(n) + rng.normal(0, noise, n)


class SymbolResolutionTests(unittest.TestCase):
    def test_taiwan_etf_codes_get_tw_suffix(self):
        for code in ("0050", "0056", "00878", "006208", "00679B"):
            with self.subTest(code=code):
                self.assertEqual(symbol_utils.resolve(code)["primary"], f"{code}.TW")

    def test_otc_stock_prefers_two_suffix(self):
        resolved = symbol_utils.resolve("6488")
        self.assertEqual(resolved["primary"], "6488.TWO")
        self.assertIn("6488.TW", resolved["candidates"])  # 仍保留備援

    def test_unknown_taiwan_code_tries_both_boards(self):
        self.assertEqual(symbol_utils.resolve("1234")["candidates"], ["1234.TW", "1234.TWO"])

    def test_us_symbols_pass_through(self):
        self.assertEqual(symbol_utils.resolve("spy")["primary"], "SPY")
        self.assertEqual(symbol_utils.resolve("BRK-B")["primary"], "BRK-B")

    def test_chinese_name_resolves_to_symbol(self):
        self.assertEqual(symbol_utils.resolve("台積電")["primary"], "2330.TW")
        self.assertEqual(symbol_utils.resolve("元大台灣50")["primary"], "0050.TW")

    def test_full_width_and_padding_are_normalized(self):
        self.assertEqual(symbol_utils.normalize_query(" ｎｖｄａ "), "NVDA")

    def test_symbol_search_matches_code_name_and_tag(self):
        codes = [item["code"] for item in symbol_utils.search("高股息", limit=5)]
        self.assertIn("0056", codes)
        self.assertIn("00878", codes)
        self.assertTrue(all(item["kind"] == "etf" for item in symbol_utils.search("台灣", limit=5, kind="etf")))

    def test_empty_query_returns_quick_picks(self):
        self.assertTrue(symbol_utils.search("", limit=5))
        self.assertTrue(symbol_utils.quick_picks())

    def test_quote_type_classification(self):
        self.assertEqual(symbol_utils.classify_quote_type("ETF"), "etf")
        self.assertEqual(symbol_utils.classify_quote_type("EQUITY"), "stock")
        self.assertEqual(symbol_utils.classify_quote_type(None), "unknown")


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.prices = make_prices(trending_series())
        self.indicators = indicator_engine.compute_indicators(self.prices)

    def test_series_length_matches_prices(self):
        self.assertEqual(len(self.indicators["rsi"]), len(self.prices))
        self.assertEqual(len(self.indicators["sma"]["sma20"]), len(self.prices))

    def test_warmup_period_is_none(self):
        self.assertIsNone(self.indicators["sma"]["sma20"][0])
        self.assertIsNotNone(self.indicators["sma"]["sma20"][-1])

    def test_rsi_within_bounds(self):
        values = [v for v in self.indicators["rsi"] if v is not None]
        self.assertTrue(values)
        self.assertTrue(all(0 <= value <= 100 for value in values))

    def test_uptrend_pushes_rsi_above_fifty(self):
        self.assertGreater(self.indicators["rsi"][-1], 50)

    def test_empty_input_is_safe(self):
        empty = indicator_engine.compute_indicators([])
        self.assertEqual(empty["rsi"], [])
        self.assertEqual(indicator_engine.latest_snapshot([], {}), {})

    def test_snapshot_contains_expected_fields(self):
        snapshot = indicator_engine.latest_snapshot(self.prices, self.indicators)
        for key in ("close", "rsi", "macd", "sma20", "position_52w", "volatility_annualized"):
            self.assertIn(key, snapshot)
        self.assertGreater(snapshot["high_52w"], snapshot["low_52w"])


class ForecastTests(unittest.TestCase):
    def test_uptrend_is_forecast_upward(self):
        result = forecast_engine.compute_forecast(make_prices(trending_series(slope=0.3)), horizon=7)
        self.assertEqual(result["status"], "ready")
        self.assertGreater(result["ensemble"]["change_pct"], 0)

    def test_downtrend_is_forecast_downward(self):
        values = trending_series(slope=-0.3, base=250.0)
        result = forecast_engine.compute_forecast(make_prices(values), horizon=14)
        self.assertLess(result["ensemble"]["change_pct"], 0)

    def test_forecast_path_length_matches_horizon(self):
        result = forecast_engine.compute_forecast(make_prices(trending_series()), horizon=30)
        self.assertEqual(len(result["ensemble"]["path"]), 30)
        self.assertEqual(len(result["ensemble"]["upper_band"]), 30)

    def test_confidence_band_brackets_the_forecast(self):
        result = forecast_engine.compute_forecast(make_prices(trending_series()), horizon=7)
        ensemble = result["ensemble"]
        for lower, mid, upper in zip(ensemble["lower_band"], ensemble["path"], ensemble["upper_band"]):
            self.assertLessEqual(lower, mid)
            self.assertLessEqual(mid, upper)

    def test_weights_are_normalized(self):
        result = forecast_engine.compute_forecast(make_prices(trending_series()), horizon=7)
        total = sum(item["weight"] for item in result["predictions"].values())
        self.assertAlmostEqual(total, 100.0, delta=0.6)

    def test_backtest_runs_are_recorded(self):
        result = forecast_engine.compute_forecast(make_prices(trending_series()), horizon=7)
        self.assertGreater(result["validation"]["runs"], 0)
        self.assertIsNotNone(result["ensemble"]["backtest_mape"])

    def test_predictions_stay_within_reasonable_bounds(self):
        prices = make_prices(trending_series())
        latest = prices[-1]["close"]
        result = forecast_engine.compute_forecast(prices, horizon=30)
        for item in result["predictions"].values():
            self.assertLess(abs(item["predicted_price"] - latest) / latest, 0.36)

    def test_insufficient_history_reports_status(self):
        self.assertEqual(
            forecast_engine.compute_forecast(make_prices(trending_series(n=10)), 7)["status"],
            "insufficient_history",
        )

    def test_empty_prices(self):
        self.assertEqual(forecast_engine.compute_forecast([], 7)["status"], "no_data")

    def test_flat_series_does_not_explode(self):
        result = forecast_engine.compute_forecast(make_prices([100.0] * 200), horizon=7)
        self.assertEqual(result["status"], "ready")
        self.assertLess(abs(result["ensemble"]["change_pct"]), 5)


class SignalTests(unittest.TestCase):
    def _analyze(self, values, sentiment=None, kind="stock"):
        prices = make_prices(values)
        indicators = indicator_engine.compute_indicators(prices)
        snapshot = indicator_engine.latest_snapshot(prices, indicators)
        forecast_result = forecast_engine.compute_forecast(prices, horizon=7)
        return signal_engine.analyze(snapshot, sentiment, forecast_result, kind)

    def test_strong_uptrend_reads_bullish(self):
        read = self._analyze(trending_series(slope=0.35))
        self.assertIn(read["stance"], {"bullish", "slightly_bullish"})
        self.assertGreater(read["score"], 0)
        self.assertGreater(read["counts"]["bullish"], read["counts"]["bearish"])

    def test_strong_downtrend_reads_bearish(self):
        read = self._analyze(trending_series(slope=-0.35, base=250.0))
        self.assertIn(read["stance"], {"bearish", "slightly_bearish"})
        self.assertLess(read["score"], 0)

    def test_summary_is_traditional_chinese_text(self):
        read = self._analyze(trending_series())
        self.assertGreater(len(read["summary"]), 60)
        self.assertIn("分數", read["summary"])
        self.assertTrue(read["headline"])
        self.assertTrue(read["risk_note"].endswith("。"))

    def test_every_signal_has_required_fields(self):
        read = self._analyze(trending_series())
        self.assertTrue(read["signals"])
        for signal in read["signals"]:
            self.assertIn(signal["stance"], {"bullish", "bearish", "neutral"})
            self.assertTrue(0 <= signal["strength"] <= 100)
            self.assertTrue(signal["name"] and signal["text"])

    def test_sentiment_is_included_as_a_signal(self):
        sentiment = {"records": 30, "score_mean": 25.0, "positive_ratio": 0.6,
                     "negative_ratio": 0.1, "neutral_ratio": 0.3, "dominant_label": "positive"}
        read = self._analyze(trending_series(), sentiment=sentiment)
        keys = {signal["key"] for signal in read["signals"]}
        self.assertIn("sentiment", keys)
        self.assertIn("forecast", keys)

    def test_score_is_bounded(self):
        for slope in (2.0, -2.0):
            read = self._analyze(trending_series(slope=slope, base=500.0))
            self.assertTrue(-100 <= read["score"] <= 100)

    def test_no_snapshot_returns_friendly_message(self):
        read = signal_engine.analyze({})
        self.assertEqual(read["status"], "no_data")
        self.assertTrue(read["summary"])


class ApiTests(unittest.TestCase):
    """用假的下載函式取代 yfinance / Google News，驗證 API 組裝邏輯。"""

    @classmethod
    def setUpClass(cls):
        import fetcher as fetcher_module
        import news as news_module

        cls.prices = make_prices(trending_series())
        fetcher_module.StockDataFetcher._download = (
            lambda self, symbol, period, interval: cls.prices if symbol.endswith(".TW") or symbol == "SPY" else None
        )
        fetcher_module.StockDataFetcher.get_company_overview = (
            lambda self, symbol, catalog_entry=None: {
                "symbol": symbol, "name": "測試標的", "kind": (catalog_entry or {}).get("kind", "stock"),
                "kind_label": "ETF", "currency": "TWD",
            }
        )
        news_module.analyze_ticker_news = lambda **kwargs: {
            "ok": True, "news": [], "summary": news_module.summarize([], {}, "rnn", "test", "ok"),
        }

        import index
        index.news_engine.analyze_ticker_news = news_module.analyze_ticker_news
        cls.client = index.app.test_client()

    def test_health(self):
        payload = self.client.get("/api/health").get_json()
        self.assertEqual(payload["status"], "healthy")
        self.assertTrue(payload["features"]["etf_support"])

    def test_symbol_search_endpoint(self):
        payload = self.client.get("/api/symbol_search?q=0050").get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["results"][0]["code"], "0050")

    def test_stock_insight_returns_full_payload(self):
        response = self.client.get("/api/stock_insight?ticker=0050&period=1y&interval=1d&forecast_horizon=7")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        for key in ("stock_price_trends", "technical_indicators", "forecast",
                    "market_read", "price_change_detail", "symbol"):
            self.assertIn(key, payload)
        self.assertEqual(payload["symbol"]["resolved"], "0050.TW")
        self.assertEqual(payload["forecast"]["status"], "ready")
        self.assertTrue(payload["market_read"]["summary"])

    def test_missing_ticker_is_rejected(self):
        self.assertEqual(self.client.get("/api/stock_insight").status_code, 400)

    def test_invalid_period_is_rejected(self):
        self.assertEqual(self.client.get("/api/stock_insight?ticker=0050&period=99y").status_code, 400)

    def test_unknown_symbol_returns_404_with_suggestions(self):
        response = self.client.get("/api/stock_insight?ticker=ZZZZ")
        self.assertEqual(response.status_code, 404)
        self.assertIn("suggestions", response.get_json())

    def test_intraday_period_is_clamped(self):
        payload = self.client.get(
            "/api/stock_insight?ticker=0050&period=1y&interval=15m"
        ).get_json()
        self.assertEqual(payload["request"]["effective_period"], "1mo")


class FetcherHelperTests(unittest.TestCase):
    def test_clamp_period(self):
        import fetcher as fetcher_module

        self.assertEqual(fetcher_module.clamp_period("1y", "15m"), "1mo")
        self.assertEqual(fetcher_module.clamp_period("5d", "5m"), "5d")
        self.assertEqual(fetcher_module.clamp_period("1y", "1d"), "1y")


if __name__ == "__main__":
    unittest.main(verbosity=2)
