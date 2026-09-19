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

import analytics as analytics_engine  # noqa: E402
import fetcher as fetcher_module  # noqa: E402
import forecast as forecast_engine  # noqa: E402
import indicators as indicator_engine  # noqa: E402
import signals as signal_engine  # noqa: E402
import pandas as pd  # noqa: E402

import news as news_module  # noqa: E402
import symbols as symbol_utils  # noqa: E402
import tw_directory  # noqa: E402
import us_directory  # noqa: E402


START_DATE = pd.Timestamp("2022-01-03")


# ApiTests 會替換掉 news.analyze_ticker_news，先保留原本的實作供安全性測試使用
ORIGINAL_ANALYZE_TICKER_NEWS = news_module.analyze_ticker_news


def make_prices(values, start_volume: int = 1_000_000) -> list[dict]:
    """把收盤價序列轉成 API 格式的價格列表（日期為連續營業日）。"""
    dates = pd.bdate_range(START_DATE, periods=len(values))
    prices = []
    for index, value in enumerate(values):
        close = float(value)
        prices.append({
            "date": dates[index].strftime("%Y-%m-%d"),
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


ISIN_SAMPLE = """
<table class="h4">
<tr><td colspan="7" align="left"><B>&nbsp;股票&nbsp;</B></td></tr>
<tr align=center><td>有價證券代號及名稱</td><td>國際證券辨識號碼</td><td>上市日</td><td>市場別</td><td>產業別</td><td>CFICode</td><td>備註</td></tr>
<tr><td bgcolor=#FAFAD2>1101\u3000台泥</td><td>TW0001101004</td><td>1962/02/09</td><td>上市</td><td>水泥工業</td><td>ESVUFR</td><td></td></tr>
<tr><td>2618\u3000長榮航</td><td>TW0002618007</td><td>1996/11/26</td><td>上市</td><td>航運業</td><td>ESVUFR</td><td></td></tr>
<tr><td>0050\u3000元大台灣50</td><td>TW0000050004</td><td>2003/06/30</td><td>上市</td><td></td><td>CEOGEU</td><td></td></tr>
<tr><td>6446\u3000藥華藥</td><td>TW0006446002</td><td>2016/12/19</td><td>上櫃</td><td>生技醫療業</td><td>ESVUFR</td><td></td></tr>
<tr><td>031505\u3000元大臺灣50購01</td><td>TW0310505005</td><td>2024/01/02</td><td>上市</td><td></td><td>RWSCPE</td><td></td></tr>
</table>
"""


class TaiwanDirectoryTests(unittest.TestCase):
    """證交所清單解析與中文名稱查詢。"""

    def setUp(self):
        self._original = tw_directory._cache._entries
        tw_directory._cache._entries = tw_directory.parse_isin_html(ISIN_SAMPLE, "上市")
        symbol_utils._directory_cache = None

    def tearDown(self):
        tw_directory._cache._entries = self._original
        symbol_utils._directory_cache = None

    def test_parser_keeps_stocks_and_etfs_only(self):
        entries = tw_directory.parse_isin_html(ISIN_SAMPLE, "上市")
        codes = {entry["code"] for entry in entries}
        self.assertEqual(codes, {"1101", "2618", "0050", "6446"})  # 權證被濾掉

    def test_parser_detects_kind_and_market(self):
        entries = {entry["code"]: entry for entry in tw_directory.parse_isin_html(ISIN_SAMPLE, "上市")}
        self.assertEqual(entries["0050"]["kind"], "etf")
        self.assertEqual(entries["1101"]["kind"], "stock")
        self.assertEqual(entries["6446"]["symbol"], "6446.TWO")
        self.assertEqual(entries["2618"]["symbol"], "2618.TW")

    def test_chinese_name_outside_catalog_is_resolved(self):
        self.assertEqual(symbol_utils.resolve("長榮航")["primary"], "2618.TW")
        self.assertEqual(symbol_utils.resolve("藥華藥")["primary"], "6446.TWO")

    def test_directory_entries_appear_in_search(self):
        codes = [item["code"] for item in symbol_utils.search("長榮", limit=5)]
        self.assertIn("2618", codes)
        self.assertIn("2603", codes)  # 內建字典的長榮也還在

    def test_catalog_entries_take_priority(self):
        # 0050 同時存在於內建字典與證交所清單，結果不應重複
        codes = [item["code"] for item in symbol_utils.search("0050", limit=5)]
        self.assertEqual(codes.count("0050"), 1)

    def test_bad_html_does_not_raise(self):
        self.assertEqual(tw_directory.parse_isin_html("<html>壞掉的頁面</html>", "上市"), [])


class DividendAndSplitTests(unittest.TestCase):
    """配息 / 分割資料整理。"""

    @staticmethod
    def _series(pairs):
        dates = [pd.Timestamp(date) for date, _ in pairs]
        return pd.Series([amount for _, amount in pairs], index=pd.DatetimeIndex(dates))

    def test_quarterly_frequency_detected(self):
        pairs = [(f"{year}-{month:02d}-15", 2.5)
                 for year in (2022, 2023, 2024) for month in (3, 6, 9, 12)]
        summary = fetcher_module._summarize_dividends(self._series(pairs))
        self.assertEqual(summary["frequency"], "quarterly")
        self.assertEqual(summary["frequency_label"], "季配")

    def test_monthly_frequency_detected(self):
        pairs = [(date.strftime("%Y-%m-%d"), 0.1)
                 for date in pd.date_range("2023-01-15", periods=24, freq="ME")]
        summary = fetcher_module._summarize_dividends(self._series(pairs))
        self.assertEqual(summary["frequency_label"], "月配")

    def test_yearly_totals_and_streak(self):
        pairs = [("2021-07-20", 2.0), ("2022-07-20", 2.5), ("2023-07-20", 3.0), ("2024-07-20", 3.2)]
        summary = fetcher_module._summarize_dividends(self._series(pairs))
        self.assertEqual([item["year"] for item in summary["yearly"]], [2021, 2022, 2023, 2024])
        self.assertAlmostEqual(summary["yearly"][-1]["total"], 3.2)
        self.assertEqual(summary["consecutive_years"], 4)
        self.assertEqual(summary["years_paid"], 4)

    def test_records_are_newest_first(self):
        pairs = [("2023-07-20", 2.0), ("2024-07-20", 2.5)]
        summary = fetcher_module._summarize_dividends(self._series(pairs))
        self.assertEqual(summary["records"][0]["date"], "2024-07-20")
        self.assertEqual(summary["latest"]["amount"], 2.5)

    def test_yield_is_computed_from_price(self):
        pairs = [(pd.Timestamp.utcnow().strftime("%Y-%m-%d"), 4.0)]
        payload = {"dividends": fetcher_module._summarize_dividends(self._series(pairs))}
        enriched = fetcher_module._with_yield(payload, 100.0)
        self.assertEqual(enriched["dividends"]["ttm_yield_pct"], 4.0)

    def test_no_dividend_history(self):
        self.assertIsNone(fetcher_module._summarize_dividends(pd.Series(dtype=float)))
        self.assertIsNone(fetcher_module._summarize_dividends(None))

    def test_split_labels(self):
        series = self._series([("2020-08-31", 4.0), ("2023-05-05", 0.2)])
        splits = fetcher_module._summarize_splits(series)
        self.assertEqual(splits["count"], 2)
        labels = {record["date"]: record for record in splits["records"]}
        self.assertEqual(labels["2020-08-31"]["kind"], "split")
        self.assertIn("1 股 → 4 股", labels["2020-08-31"]["label"])
        self.assertEqual(labels["2023-05-05"]["kind"], "reverse_split")
        self.assertIn("5 股 → 1 股", labels["2023-05-05"]["label"])

    def test_no_split_history(self):
        self.assertIsNone(fetcher_module._summarize_splits(pd.Series(dtype=float)))

    def test_timestamp_helpers(self):
        self.assertEqual(fetcher_module._timestamp_to_date(1721260800), "2024-07-18")
        self.assertIsNone(fetcher_module._timestamp_to_date(None))
        self.assertEqual(fetcher_module._ratio_to_pct(0.2345), 23.45)


US_SYMBOL_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust, Series 1|Q|N|N|100|Y|N
ZVZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N
AACIW|Armada Acquisition Corp. II - Warrant|S|N|N|100|N|N
File Creation Time: 0919202601:30|||||||"""

US_OTHER_SAMPLE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Inc. Class B|N|BRK B|N|100|N|BRK.B
ASML|ASML Holding N.V. - Ordinary Shares|Q|ASML|N|100|N|ASML"""


class UsDirectoryTests(unittest.TestCase):
    """美股清單解析與英文名稱查詢。"""

    def setUp(self):
        entries = us_directory.parse_symbol_file(US_SYMBOL_SAMPLE, 0, 1, 6, 3)
        entries += us_directory.parse_symbol_file(US_OTHER_SAMPLE, 0, 1, 4, 6, 2)
        self._original = us_directory._cache._entries
        us_directory._cache._entries = entries
        symbol_utils._directory_cache = None

    def tearDown(self):
        us_directory._cache._entries = self._original
        symbol_utils._directory_cache = None

    def test_test_issues_and_warrants_are_filtered(self):
        codes = {entry["code"] for entry in us_directory.parse_symbol_file(US_SYMBOL_SAMPLE, 0, 1, 6, 3)}
        self.assertEqual(codes, {"AAPL", "QQQ"})

    def test_etf_flag_is_read(self):
        entries = {e["code"]: e for e in us_directory.parse_symbol_file(US_SYMBOL_SAMPLE, 0, 1, 6, 3)}
        self.assertEqual(entries["QQQ"]["kind"], "etf")
        self.assertEqual(entries["AAPL"]["kind"], "stock")

    def test_dotted_symbols_are_converted_for_yfinance(self):
        entries = {e["code"]: e for e in us_directory.parse_symbol_file(US_OTHER_SAMPLE, 0, 1, 4, 6, 2)}
        self.assertIn("BRK-B", entries)

    def test_name_suffix_is_trimmed(self):
        entries = {e["code"]: e for e in us_directory.parse_symbol_file(US_SYMBOL_SAMPLE, 0, 1, 6, 3)}
        self.assertEqual(entries["AAPL"]["name_en"], "Apple Inc.")

    def test_us_company_name_resolves_to_ticker(self):
        self.assertEqual(symbol_utils.resolve("ASML Holding N.V.")["primary"], "ASML")

    def test_us_directory_entries_are_searchable(self):
        codes = [item["code"] for item in symbol_utils.search("ASML", limit=3)]
        self.assertIn("ASML", codes)


class AnalyticsTests(unittest.TestCase):
    """風險指標、定期定額與比較用序列。"""

    def setUp(self):
        self.prices = make_prices(trending_series(n=500, slope=0.15, noise=1.0))

    def test_metrics_are_computed(self):
        metrics = analytics_engine.risk_metrics(self.prices, "1d")
        self.assertEqual(metrics["status"], "ready")
        self.assertGreater(metrics["total_return_pct"], 0)
        self.assertGreater(metrics["annualized_volatility_pct"], 0)
        self.assertLessEqual(metrics["max_drawdown_pct"], 0)

    def test_max_drawdown_matches_known_series(self):
        closes = np.array([100.0, 120.0, 90.0, 110.0], dtype=float)
        drawdown = analytics_engine.max_drawdown(closes)
        self.assertAlmostEqual(drawdown["pct"], -25.0, places=6)
        self.assertEqual(drawdown["peak_index"], 1)
        self.assertEqual(drawdown["trough_index"], 2)

    def test_insufficient_data(self):
        self.assertEqual(analytics_engine.risk_metrics(self.prices[:3])["status"], "insufficient_data")
        self.assertEqual(analytics_engine.risk_metrics([])["status"], "insufficient_data")

    def test_beta_against_itself_is_one(self):
        result = analytics_engine.beta_vs_benchmark(self.prices, self.prices)
        self.assertAlmostEqual(result["beta"], 1.0, places=2)
        self.assertAlmostEqual(result["correlation"], 1.0, places=2)

    def test_beta_needs_enough_overlap(self):
        self.assertIsNone(analytics_engine.beta_vs_benchmark(self.prices[:5], self.prices[:5]))

    def test_dca_on_flat_prices_breaks_even(self):
        flat = [{"date": (pd.Timestamp("2022-01-03") + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                 "open": 50.0, "high": 50.0, "low": 50.0, "close": 50.0, "volume": 1000}
                for i in range(400)]
        result = analytics_engine.simulate_dca(flat, amount=1000)
        self.assertEqual(result["status"], "ready")
        self.assertAlmostEqual(result["total_return_pct"], 0.0, places=6)
        self.assertAlmostEqual(result["average_cost"], 50.0, places=2)

    def test_dca_scales_linearly_with_amount(self):
        base = analytics_engine.simulate_dca(self.prices, amount=1000)
        doubled = analytics_engine.simulate_dca(self.prices, amount=2000)
        self.assertAlmostEqual(doubled["final_value"], base["final_value"] * 2, delta=1.0)
        self.assertAlmostEqual(doubled["total_return_pct"], base["total_return_pct"], places=4)

    def test_dca_counts_dividends(self):
        dividends = [{"date": "2022-07-15", "amount": 2.0}, {"date": "2023-07-14", "amount": 2.0}]
        with_dividends = analytics_engine.simulate_dca(self.prices, dividends, amount=1000)
        without = analytics_engine.simulate_dca(self.prices, None, amount=1000)
        self.assertGreater(with_dividends["dividend_total"], 0)
        self.assertGreater(with_dividends["final_value"], without["final_value"])

    def test_dca_monthly_cadence(self):
        result = analytics_engine.simulate_dca(self.prices, amount=1000)
        self.assertEqual(result["months"], len(result["history"]))
        self.assertAlmostEqual(result["invested"], result["months"] * 1000, places=2)

    def test_normalize_series_starts_at_100(self):
        series = analytics_engine.normalize_series(self.prices)
        self.assertEqual(series["values"][0], 100.0)
        self.assertEqual(len(series["values"]), len(self.prices))

    def test_normalize_empty(self):
        self.assertEqual(analytics_engine.normalize_series([])["values"], [])


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
        def fake_actions(self, symbol, latest_price=None):
            recent = pd.Timestamp.utcnow().normalize().tz_localize(None)
            series = pd.Series(
                [2.0, 2.5],
                index=pd.DatetimeIndex([recent - pd.Timedelta(days=400), recent - pd.Timedelta(days=30)]),
            )
            payload = {
                "status": "ok",
                "dividends": fetcher_module._summarize_dividends(series),
                "splits": None,
            }
            return fetcher_module._with_yield(payload, latest_price)

        fetcher_module.StockDataFetcher.get_corporate_actions = fake_actions
        fetcher_module.StockDataFetcher.get_fund_profile = lambda self, symbol: None
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
                    "market_read", "price_change_detail", "symbol", "corporate_actions"):
            self.assertIn(key, payload)
        self.assertEqual(payload["symbol"]["resolved"], "0050.TW")
        self.assertEqual(payload["forecast"]["status"], "ready")
        self.assertTrue(payload["market_read"]["summary"])

    def test_corporate_actions_are_included(self):
        payload = self.client.get("/api/stock_insight?ticker=0050").get_json()
        dividends = payload["corporate_actions"]["dividends"]
        self.assertEqual(dividends["total_records"], 2)
        self.assertEqual(dividends["ttm_total"], 2.5)  # 只計入近 12 個月
        self.assertGreater(dividends["ttm_yield_pct"], 0)

    def test_corporate_actions_can_be_skipped(self):
        payload = self.client.get("/api/stock_insight?ticker=0050&include_actions=0").get_json()
        self.assertIsNone(payload["corporate_actions"])

    def test_chinese_name_not_found_gives_friendly_message(self):
        response = self.client.get("/api/stock_insight?ticker=完全不存在的公司")
        self.assertEqual(response.status_code, 404)
        payload = response.get_json()
        self.assertIn("找不到", payload["message"])
        self.assertIn("代號", payload["hint"])

    def test_risk_metrics_and_dca_are_included(self):
        payload = self.client.get("/api/stock_insight?ticker=0050&period=2y").get_json()
        self.assertEqual(payload["risk_metrics"]["status"], "ready")
        self.assertIn("max_drawdown_pct", payload["risk_metrics"])
        self.assertEqual(payload["dca"]["status"], "ready")
        self.assertEqual(payload["dca"]["unit_amount"], analytics_engine.DCA_UNIT_AMOUNT)

    def test_compare_endpoint(self):
        response = self.client.get("/api/compare?tickers=0050,2330&period=1y")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["series"][0]["values"][0], 100.0)
        self.assertIsNotNone(payload["best"])

    def test_compare_limits_to_four_symbols(self):
        payload = self.client.get("/api/compare?tickers=0050,2330,0056,00878,2454").get_json()
        self.assertLessEqual(payload["count"], 4)

    def test_compare_requires_tickers(self):
        self.assertEqual(self.client.get("/api/compare").status_code, 400)

    def test_compare_reports_unknown_symbols(self):
        response = self.client.get("/api/compare?tickers=ZZZZ")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.get_json()["failed"])

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


class SecurityTests(unittest.TestCase):
    """本機靜態路由與錯誤訊息的安全性（對應 CodeQL 的路徑穿越與例外外洩告警）。"""

    @classmethod
    def setUpClass(cls):
        import index

        cls.index = index
        cls.client = index.app.test_client()

    def test_static_route_serves_public_files(self):
        self.assertEqual(self.client.get("/styles.css").status_code, 200)
        self.assertEqual(self.client.get("/app.js").status_code, 200)

    def test_path_traversal_is_rejected(self):
        for path in ("/../requirements.txt",
                     "/..%2f..%2frequirements.txt",
                     "/subdir/../../backend/fetcher.py",
                     "/%2e%2e/%2e%2e/requirements.txt"):
            with self.subTest(path=path):
                self.assertNotEqual(self.client.get(path).status_code, 200)

    def test_unknown_static_file_returns_404(self):
        self.assertEqual(self.client.get("/definitely-not-here.txt").status_code, 404)

    def test_server_error_does_not_leak_exception_text(self):
        import fetcher as fetcher_module

        original = fetcher_module.StockDataFetcher.fetch_prices
        secret = "內部堆疊訊息-SHOULD-NOT-LEAK"

        def boom(self, *args, **kwargs):
            raise RuntimeError(secret)

        fetcher_module.StockDataFetcher.fetch_prices = boom
        try:
            response = self.client.get("/api/stock_insight?ticker=0050")
            self.assertEqual(response.status_code, 500)
            body = response.get_data(as_text=True)
            self.assertNotIn(secret, body)
            self.assertIn("請稍後再試", response.get_json()["message"])
        finally:
            fetcher_module.StockDataFetcher.fetch_prices = original

    def test_news_failure_message_is_generic(self):
        original = news_module.fetch_google_news
        secret = "https://internal.example/secret-token"

        def boom(**kwargs):
            raise RuntimeError(secret)

        news_module.fetch_google_news = boom
        try:
            result = ORIGINAL_ANALYZE_TICKER_NEWS(ticker="2330")
            self.assertFalse(result["ok"])
            self.assertNotIn(secret, str(result))
        finally:
            news_module.fetch_google_news = original

    def test_directory_status_reports_category_not_raw_error(self):
        import directory_cache

        cache = directory_cache.DirectoryCache("unit_test_directory", lambda: (_ for _ in ()).throw(
            ConnectionError("proxy 127.0.0.1:9 refused")))
        cache.load()
        self.assertIn(cache.status()["error"], {"network_unavailable", "timeout", "source_error", "unavailable"})


class FetcherHelperTests(unittest.TestCase):
    def test_clamp_period(self):
        import fetcher as fetcher_module

        self.assertEqual(fetcher_module.clamp_period("1y", "15m"), "1mo")
        self.assertEqual(fetcher_module.clamp_period("5d", "5m"), "5d")
        self.assertEqual(fetcher_module.clamp_period("1y", "1d"), "1y")


if __name__ == "__main__":
    unittest.main(verbosity=2)
