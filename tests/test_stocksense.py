"""StockSense 離線測試（不需要網路，使用合成資料）。

執行方式：
    python tests/test_stocksense.py
    python -m unittest discover tests
"""

from __future__ import annotations

import math
import sys
import time
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
import tw_exrights  # noqa: E402
import us_directory  # noqa: E402


START_DATE = pd.Timestamp("2022-01-03")


# ApiTests 會替換掉 news.analyze_ticker_news，先保留原本的實作供安全性測試使用
ORIGINAL_ANALYZE_TICKER_NEWS = news_module.analyze_ticker_news

# ApiTests 也會換掉 StockDataFetcher 上的幾個方法；這些是類別層級的替換，
# 不還原的話會影響到後面跑的測試（例如 FundHoldingsTests）。
PATCHED_FETCHER_METHODS = ("_download", "get_corporate_actions", "get_fund_profile", "get_company_overview")
ORIGINAL_FETCHER_METHODS = {
    name: getattr(fetcher_module.StockDataFetcher, name) for name in PATCHED_FETCHER_METHODS
}


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
        pairs = [(pd.Timestamp.now("UTC").strftime("%Y-%m-%d"), 4.0)]
        payload = {"dividends": fetcher_module._summarize_dividends(self._series(pairs))}
        enriched = fetcher_module._with_yield(payload, 100.0)
        self.assertEqual(enriched["dividends"]["ttm_yield_pct"], 4.0)

    def test_full_dividend_history_is_kept_for_simulation(self):
        """配息紀錄不能被截斷，否則定期定額會少算早期的配息（Copilot #4052009879）。"""
        pairs = [(date.strftime("%Y-%m-%d"), 0.1)
                 for date in pd.date_range("2016-01-15", periods=120, freq="ME")]
        summary = fetcher_module._summarize_dividends(self._series(pairs))
        self.assertEqual(summary["total_records"], 120)
        self.assertEqual(len(summary["records"]), 120)
        self.assertEqual(summary["records"][-1]["date"], "2016-01-31")  # 最早一筆仍在

    def test_dca_uses_every_dividend(self):
        prices = make_prices(trending_series(n=520, slope=0.02, noise=0.3))
        dividends = [{"date": record["date"], "amount": 1.0}
                     for record in prices[::21]]      # 每月一次
        result = analytics_engine.simulate_dca(prices, dividends, amount=1000)
        self.assertGreater(result["dividend_total"], 0)
        partial = analytics_engine.simulate_dca(prices, dividends[:3], amount=1000)
        self.assertGreater(result["dividend_total"], partial["dividend_total"])

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

        # 先掛還原再開始替換：setUpClass 中途失敗的話 tearDownClass 不會被呼叫，
        # 被換掉的類別方法就會一路污染到後面的測試類別。
        cls.addClassCleanup(cls._restore_patches)

        cls.prices = make_prices(trending_series())
        fetcher_module.StockDataFetcher._download = (
            lambda self, symbol, period, interval: cls.prices if symbol.endswith(".TW") or symbol == "SPY" else None
        )
        def fake_actions(self, symbol, latest_price=None):
            recent = pd.Timestamp.now("UTC").normalize().tz_localize(None)
            series = pd.Series(
                [2.0, 2.5],
                index=pd.DatetimeIndex([recent - pd.Timedelta(days=400), recent - pd.Timedelta(days=30)]),
            )
            splits = pd.Series([1.1], index=pd.DatetimeIndex([recent - pd.Timedelta(days=800)]))
            payload = {
                "status": "ok",
                "dividends": fetcher_module._summarize_dividends(series),
                "splits": fetcher_module._summarize_splits(splits, symbol),
                "rights": fetcher_module._summarize_rights(splits, symbol, []),
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

    @staticmethod
    def _restore_patches():
        """把 setUpClass 換掉的類別方法還原，免得污染後面的測試。"""
        for name, original in ORIGINAL_FETCHER_METHODS.items():
            setattr(fetcher_module.StockDataFetcher, name, original)
        news_module.analyze_ticker_news = ORIGINAL_ANALYZE_TICKER_NEWS

    def test_health(self):
        payload = self.client.get("/api/health").get_json()
        self.assertEqual(payload["status"], "healthy")
        self.assertTrue(payload["features"]["etf_support"])

    def test_stock_insight_carries_the_rights_block(self):
        payload = self.client.get("/api/stock_insight?ticker=0050&period=1y").get_json()
        rights = payload["corporate_actions"]["rights"]
        self.assertEqual(rights["records"][0]["kind"], "rights")
        self.assertAlmostEqual(rights["records"][0]["shares_per_1000"], 100.0)
        # 台股的配股不該重複出現在「分割」分頁
        self.assertIsNone(payload["corporate_actions"]["splits"])

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

    def test_health_never_triggers_a_network_load(self):
        """/api/health 不能同步載入名稱清單，否則冷啟動會卡住（Copilot #4052009872）。"""
        import directory_cache
        import symbols as symbols_module

        calls = []

        def should_not_run():
            calls.append(1)
            raise AssertionError("health check 不應該觸發抓取")

        cache = directory_cache.DirectoryCache("unit_test_health", should_not_run)
        original_tw_status = symbols_module.tw_directory.status
        symbols_module.tw_directory.status = cache.status
        try:
            payload = self.client.get("/api/health").get_json()
            self.assertEqual(payload["status"], "healthy")
            self.assertFalse(payload["symbol_directory"]["taiwan"]["ready"])
            self.assertEqual(calls, [])
        finally:
            symbols_module.tw_directory.status = original_tw_status

    def test_status_and_local_load_do_not_fetch_synchronously(self):
        import directory_cache

        fetches = []

        def slow_fetcher():
            fetches.append(1)
            raise ConnectionError("不該擋住請求")

        cache = directory_cache.DirectoryCache("unit_test_nonblocking", slow_fetcher)
        self.assertEqual(cache.status()["loaded"], 0)
        self.assertEqual(fetches, [])          # status 完全不抓

        self.assertEqual(cache.load_local(), [])   # 只讀本機，立刻回來
        for _ in range(60):                        # 背景執行緒最終會跑完
            if not cache.status()["loading"]:
                break
            time.sleep(0.05)
        self.assertFalse(cache.status()["loading"])
        self.assertEqual(fetches, [1])             # 背景確實抓過一次（且只有一次）

    def test_directory_status_reports_category_not_raw_error(self):
        import directory_cache

        cache = directory_cache.DirectoryCache("unit_test_directory", lambda: (_ for _ in ()).throw(
            ConnectionError("proxy 127.0.0.1:9 refused")))
        cache.load()
        self.assertIn(cache.status()["error"], {"network_unavailable", "timeout", "source_error", "unavailable"})


class ReviewFollowUpTests(unittest.TestCase):
    """CodeRabbit review 指出的問題的回歸測試。"""

    def test_boolean_flags_are_normalized(self):
        """FALSE / " false " / OFF 都要算關閉（#4052xxxx：旗標未正規化）。"""
        import index

        for raw in ("0", "false", "FALSE", " false ", "No", "OFF", " 0 "):
            with index.app.test_request_context(f"/api/stock_insight?include_news={raw}"):
                self.assertFalse(index._flag("include_news"), raw)

        for raw in ("1", "true", "TRUE", "yes", "anything"):
            with index.app.test_request_context(f"/api/stock_insight?include_news={raw}"):
                self.assertTrue(index._flag("include_news"), raw)

        with index.app.test_request_context("/api/stock_insight"):
            self.assertTrue(index._flag("include_news"))          # 預設開啟
            self.assertFalse(index._flag("include_news", "0"))     # 預設可覆寫

    def test_ninety_minute_period_is_clamped(self):
        """90m 的上限必須是 _PERIOD_ORDER 裡有的值，否則完全不會被限制。"""
        import fetcher as fetcher_module

        self.assertIn(fetcher_module.MAX_PERIOD_BY_INTERVAL["90m"], fetcher_module._PERIOD_ORDER)
        self.assertEqual(fetcher_module.clamp_period("1y", "90m"), "1mo")
        self.assertEqual(fetcher_module.clamp_period("5y", "90m"), "1mo")
        self.assertEqual(fetcher_module.clamp_period("5d", "90m"), "5d")

    def test_us_exclusions_use_whole_words(self):
        """排除權證 / 單位時不可誤殺 Brightcove（right）、United（unit）這類公司。"""
        sample = "\n".join([
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "BCOV|Brightcove Inc. - Common Stock|Q|N|N|100|N|N",
            "UNTD|United Natural Foods Inc. - Common Stock|Q|N|N|100|N|N",
            "RGHT|Wright Investors Service Holdings|Q|N|N|100|N|N",
            "ABCW|Some SPAC Corp. - Warrant|S|N|N|100|N|N",
            "ABCU|Some SPAC Corp. - Unit|S|N|N|100|N|N",
            "ABCR|Some SPAC Corp. - Rights|S|N|N|100|N|N",
        ])
        codes = {entry["code"] for entry in us_directory.parse_symbol_file(sample, 0, 1, 6, 3)}
        self.assertEqual(codes, {"BCOV", "UNTD", "RGHT"})

    def test_holt_fitting_window_is_bounded(self):
        """長序列不應讓 Holt 的格點搜尋變慢（只用最近 HOLT_FIT_WINDOW 期擬合）。"""
        long_series = np.asarray(trending_series(n=3000, slope=0.05, noise=1.0), dtype=float)
        short_series = long_series[-forecast_engine.HOLT_FIT_WINDOW:]
        self.assertTrue(np.allclose(
            forecast_engine._holt_damped(long_series, 7),
            forecast_engine._holt_damped(short_series, 7),
        ))


class FetcherHelperTests(unittest.TestCase):
    def test_clamp_period(self):
        import fetcher as fetcher_module

        self.assertEqual(fetcher_module.clamp_period("1y", "15m"), "1mo")
        self.assertEqual(fetcher_module.clamp_period("5d", "5m"), "5d")
        self.assertEqual(fetcher_module.clamp_period("1y", "1d"), "1y")


class TwExRightsParserTests(unittest.TestCase):
    """證交所除權除息計算結果表（TWT49U）的解析。"""

    def setUp(self):
        tw_exrights.reset_cache()

    def tearDown(self):
        tw_exrights.reset_cache()

    def test_rwd_payload_with_fields_and_rows(self):
        payload = {
            "fields": ["資料日期", "股票代號", "股票名稱", "除權息前收盤價",
                       "除權息參考價", "權值+息值", "權/息"],
            "data": [
                ["114/07/18", "2330", "台積電", "1,100.00", "1,086.00", "14.00", "息"],
                ["113/08/15", "2317", "鴻海", "200.00", "195.50", "5.20", "權息"],
            ],
        }
        records = tw_exrights.parse_payload(payload)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["date"], "2025-07-18")
        self.assertEqual(records[0]["code"], "2330")
        self.assertEqual(records[0]["kind"], "dividend")
        self.assertAlmostEqual(records[0]["before_price"], 1100.0)
        self.assertEqual(records[1]["kind"], "both")

    def test_openapi_payload_with_dict_rows(self):
        payload = {"data": [{
            "資料日期": "20250718", "股票代號": "0050", "股票名稱": "元大台灣50",
            "除權息前收盤價": "190.00", "除權息參考價": "187.00",
            "權值+息值": "3.00", "權/息": "權",
        }]}
        records = tw_exrights.parse_payload(payload)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "rights")
        self.assertEqual(records[0]["date"], "2025-07-18")
        self.assertEqual(records[0]["name"], "元大台灣50")

    def test_english_field_names_are_also_understood(self):
        payload = {"data": [{
            "Date": "20250718", "Code": "0050", "Name": "元大台灣50",
            "RightsOrDividend": "息",
        }]}
        records = tw_exrights.parse_payload(payload)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["code"], "0050")
        self.assertEqual(records[0]["kind"], "dividend")

    def test_one_title_never_maps_to_two_fields(self):
        """「除權息前收盤價」曾經同時被 before_price 與 kind 命中。"""
        self.assertEqual(tw_exrights._match_field("除權息前收盤價"), "before_price")
        self.assertEqual(tw_exrights._match_field("權/息"), "kind")
        self.assertEqual(tw_exrights._match_field("權值+息值"), "value")

    def test_date_formats(self):
        for raw, expected in [
            ("114/07/18", "2025-07-18"),
            ("1140718", "2025-07-18"),
            ("20250718", "2025-07-18"),
            ("2025-07-18", "2025-07-18"),
        ]:
            self.assertEqual(tw_exrights._normalize_date(raw), expected, raw)
        for bad in ["", None, "民國", "99"]:
            self.assertIsNone(tw_exrights._normalize_date(bad))

    def test_broken_payload_returns_empty_list(self):
        self.assertEqual(tw_exrights.parse_payload({}), [])
        self.assertEqual(tw_exrights.parse_payload({"data": [["x"]], "fields": ["無關"]}), [])
        self.assertEqual(tw_exrights.parse_payload({"data": [None, 3]}), [])

    def test_network_failure_is_silent(self):
        original = tw_exrights._fetch
        tw_exrights._fetch = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.assertEqual(tw_exrights.fetch_records(), [])
        finally:
            tw_exrights._fetch = original

    def test_get_records_for_filters_by_code_and_does_not_block(self):
        tw_exrights._cache["5"] = (time.time(), [
            {"date": "2025-07-18", "code": "2330", "kind": "dividend"},
            {"date": "2024-07-11", "code": "2330", "kind": "rights"},
            {"date": "2025-07-18", "code": "2317", "kind": "both"},
        ])
        records = tw_exrights.get_records_for("2330.TW")
        self.assertEqual([item["code"] for item in records], ["2330", "2330"])
        self.assertEqual(records[0]["date"], "2025-07-18")   # 新到舊

    def test_stale_in_flight_marker_is_retried(self):
        """Serverless 凍結容器會讓背景執行緒跑不完，不能因此永遠卡住。"""
        tw_exrights._loading["5"] = time.time() - tw_exrights.LOADING_STALE_SECONDS - 1
        self.assertFalse(tw_exrights.is_loading())
        self.assertNotIn("5", tw_exrights._loading)

        tw_exrights._loading["5"] = time.time()
        self.assertTrue(tw_exrights.is_loading())

    def test_empty_result_uses_the_short_ttl(self):
        stale = time.time() - tw_exrights.FAILURE_TTL_SECONDS - 1
        tw_exrights._cache["5"] = (stale, [])
        self.assertIsNone(tw_exrights._cached_records("5"))
        fresh = time.time() - tw_exrights.FAILURE_TTL_SECONDS + 60
        tw_exrights._cache["5"] = (fresh, [])
        self.assertEqual(tw_exrights._cached_records("5"), [])


class TaiwanRightsTests(unittest.TestCase):
    """台股配股（除權）的判讀與合併。"""

    @staticmethod
    def splits(mapping: dict) -> pd.Series:
        return pd.Series(list(mapping.values()), index=pd.to_datetime(list(mapping.keys())))

    def test_tw_bonus_share_ratio_is_read_as_rights_not_split(self):
        series = self.splits({"2021-07-15": 1.1})
        rights = fetcher_module._summarize_rights(series, "2330.TW", [])
        self.assertIsNotNone(rights)
        record = rights["records"][0]
        self.assertEqual(record["kind"], "rights")
        self.assertAlmostEqual(record["shares_per_1000"], 100.0)
        # 面額不一定是 10 元，所以不換算成「股票股利 N 元」
        self.assertNotIn("stock_dividend", record)
        self.assertNotIn("元", record["label"])
        # 同一筆不應該又出現在「分割」分頁
        self.assertIsNone(fetcher_module._summarize_splits(series, "2330.TW"))

    def test_real_splits_stay_in_the_split_tab(self):
        series = self.splits({"2022-03-01": 2.0, "2023-01-05": 0.5})
        self.assertIsNone(fetcher_module._summarize_rights(series, "2330.TW", []))
        splits = fetcher_module._summarize_splits(series, "2330.TW")
        self.assertEqual(splits["count"], 2)

    def test_us_symbols_have_no_rights_and_keep_every_split(self):
        series = self.splits({"2020-08-31": 4.0, "2021-01-05": 1.1})
        self.assertIsNone(fetcher_module._summarize_rights(series, "AAPL", []))
        self.assertEqual(fetcher_module._summarize_splits(series, "AAPL")["count"], 2)

    def test_twse_records_are_merged_with_the_split_ratio(self):
        series = self.splits({"2021-07-15": 1.1})
        twse = [
            {"date": "2021-07-15", "code": "2330", "kind": "both", "kind_label": "權息",
             "before_price": 600.0, "reference_price": 586.0, "value": 14.0},
            {"date": "2019-06-24", "code": "2330", "kind": "rights", "kind_label": "權",
             "before_price": 100.0, "reference_price": 98.0, "value": 2.0},
            {"date": "2020-06-18", "code": "2330", "kind": "dividend", "kind_label": "息",
             "before_price": 90.0, "reference_price": 87.5, "value": 2.5},
        ]
        rights = fetcher_module._summarize_rights(series, "2330.TW", twse)
        # 純除息不列在除權分頁
        self.assertEqual(len(rights["records"]), 2)
        merged = rights["records"][0]
        self.assertEqual(merged["date"], "2021-07-15")
        self.assertEqual(merged["source"], "twse+splits")
        self.assertAlmostEqual(merged["shares_per_1000"], 100.0)
        self.assertAlmostEqual(merged["reference_price"], 586.0)
        self.assertAlmostEqual(merged["drop_pct"], 2.33)
        self.assertTrue(rights["has_twse"])

    def test_estimate_is_marked_pending_and_not_cached_while_twse_loads(self):
        """證交所還在背景抓的時候，推算版不能被快取住（Copilot review #11）。"""
        series = self.splits({"2021-07-15": 1.1})

        class FakeTicker:
            def __init__(self, symbol):
                self.dividends = pd.Series(dtype=float)
                self.splits = series

        original_yf = fetcher_module.yf
        original_lookup = fetcher_module._tw_exrights_for
        original_is_loading = tw_exrights.is_loading
        fetcher_module.yf = type("FakeYf", (), {"Ticker": FakeTicker})
        fetcher_module._tw_exrights_for = lambda symbol: []        # 證交所還沒回來
        tw_exrights.is_loading = lambda: True
        try:
            fetcher = fetcher_module.StockDataFetcher()
            payload = fetcher.get_corporate_actions("2330.TW")
            # 推算值照樣給使用者看，但要標記還沒拿到證交所資料
            self.assertIsNotNone(payload["rights"])
            self.assertTrue(payload["rights_pending"])
            self.assertIsNone(fetcher._profile_cache.get(("actions", "2330.TW")))

            # 證交所回來之後就可以快取了
            tw_exrights.is_loading = lambda: False
            settled = fetcher.get_corporate_actions("2330.TW")
            self.assertNotIn("rights_pending", settled)
            self.assertIsNotNone(fetcher._profile_cache.get(("actions", "2330.TW")))
        finally:
            fetcher_module.yf = original_yf
            fetcher_module._tw_exrights_for = original_lookup
            tw_exrights.is_loading = original_is_loading

    def test_twse_rights_survive_a_yfinance_failure(self):
        """yfinance 掛掉不代表證交所的除權資料也拿不到（CodeRabbit review #11）。"""
        class ExplodingTicker:
            def __init__(self, symbol):
                raise RuntimeError("yfinance 壞了")

        twse = [{"date": "2019-06-24", "code": "2330", "kind": "rights", "kind_label": "權",
                 "before_price": 100.0, "reference_price": 98.0, "value": 2.0}]

        original_yf = fetcher_module.yf
        original_lookup = fetcher_module._tw_exrights_for
        fetcher_module.yf = type("FakeYf", (), {"Ticker": ExplodingTicker})
        fetcher_module._tw_exrights_for = lambda symbol: twse
        try:
            payload = fetcher_module.StockDataFetcher().get_corporate_actions("2330.TW")
        finally:
            fetcher_module.yf = original_yf
            fetcher_module._tw_exrights_for = original_lookup

        self.assertIsNone(payload["dividends"])
        self.assertIsNone(payload["splits"])
        self.assertEqual(payload["rights"]["count"], 1)
        self.assertEqual(payload["rights"]["records"][0]["reference_price"], 98.0)
        self.assertEqual(payload["status"], "ok")

    def test_status_is_unavailable_when_nothing_can_be_read(self):
        class ExplodingTicker:
            def __init__(self, symbol):
                raise RuntimeError("yfinance 壞了")

        original_yf = fetcher_module.yf
        original_lookup = fetcher_module._tw_exrights_for
        fetcher_module.yf = type("FakeYf", (), {"Ticker": ExplodingTicker})
        fetcher_module._tw_exrights_for = lambda symbol: []
        try:
            payload = fetcher_module.StockDataFetcher().get_corporate_actions("2330.TW")
        finally:
            fetcher_module.yf = original_yf
            fetcher_module._tw_exrights_for = original_lookup

        self.assertEqual(payload["status"], "unavailable")

    def test_empty_inputs_return_none(self):
        self.assertIsNone(fetcher_module._summarize_rights(None, "2330.TW", []))
        self.assertIsNone(fetcher_module._summarize_rights(pd.Series(dtype=float), "2330.TW", []))
        self.assertIsNone(fetcher_module._summarize_rights(self.splits({"2021-07-15": 1.1}), None, []))

    def test_exrights_lookup_never_raises(self):
        original = tw_exrights.get_records_for
        tw_exrights.get_records_for = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.assertEqual(fetcher_module._tw_exrights_for("2330.TW"), [])
        finally:
            tw_exrights.get_records_for = original
        self.assertEqual(fetcher_module._tw_exrights_for("AAPL"), [])


class FundHoldingsTests(unittest.TestCase):
    """ETF 前十大持股解析要能吃下 yfinance 各版本的欄位名稱。"""

    def test_fraction_weights_are_scaled_to_percent(self):
        frame = pd.DataFrame(
            {"Name": ["台積電", "鴻海"], "Holding Percent": [0.5712, 0.0421]},
            index=pd.Index(["2330.TW", "2317.TW"], name="Symbol"),
        )
        holdings = fetcher_module._parse_top_holdings(frame)
        self.assertEqual(holdings[0]["symbol"], "2330.TW")
        self.assertAlmostEqual(holdings[0]["weight_pct"], 57.12)
        self.assertAlmostEqual(holdings[1]["weight_pct"], 4.21)

    def test_percent_weights_are_left_alone(self):
        frame = pd.DataFrame({"name": ["Apple", "Microsoft"], "holdingPercent": [7.12, 6.05]},
                             index=["AAPL", "MSFT"])
        holdings = fetcher_module._parse_top_holdings(frame)
        self.assertAlmostEqual(holdings[0]["weight_pct"], 7.12)

    def test_list_of_dicts_is_accepted(self):
        holdings = fetcher_module._parse_top_holdings([
            {"symbol": "A", "name": "Alpha", "weight": 0.33},
            {"symbol": "B", "name": "Beta", "weight": 0.21},
        ])
        self.assertEqual([item["name"] for item in holdings], ["Alpha", "Beta"])
        self.assertAlmostEqual(holdings[0]["weight_pct"], 33.0)

    def test_missing_or_broken_input_returns_empty(self):
        self.assertEqual(fetcher_module._parse_top_holdings(None), [])
        self.assertEqual(fetcher_module._parse_top_holdings(pd.DataFrame()), [])
        self.assertEqual(fetcher_module._parse_top_holdings(object()), [])
        self.assertEqual(fetcher_module._parse_top_holdings([{"foo": "bar"}]), [])

    def test_only_ten_rows_are_kept(self):
        frame = pd.DataFrame({"Name": [f"N{i}" for i in range(25)],
                              "Holding Percent": [0.01] * 25},
                             index=[f"S{i}" for i in range(25)])
        self.assertEqual(len(fetcher_module._parse_top_holdings(frame)), 10)

    def test_funds_data_works_as_property_or_method(self):
        class AsProperty:
            funds_data = "payload"

        class AsMethod:
            def get_funds_data(self):
                return "payload"

        class Broken:
            @property
            def funds_data(self):
                raise RuntimeError("boom")

        self.assertEqual(fetcher_module._funds_data(AsProperty()), "payload")
        self.assertEqual(fetcher_module._funds_data(AsMethod()), "payload")
        self.assertIsNone(fetcher_module._funds_data(Broken()))
        self.assertIsNone(fetcher_module._funds_data(object()))

    def test_fund_profile_survives_broken_sector_weights(self):
        class FakeFundsData:
            fund_overview = {"categoryName": "台股大型股"}
            sector_weightings = {"tech": 0.68, "broken": "n/a", "fin": 0.12}
            description = "測試用"
            top_holdings = None

        class FakeTicker:
            def __init__(self, symbol):
                self.symbol = symbol
            funds_data = FakeFundsData()

        original = fetcher_module.yf
        fetcher_module.yf = type("FakeYf", (), {"Ticker": FakeTicker})
        try:
            profile = fetcher_module.StockDataFetcher().get_fund_profile("0056.TW")
        finally:
            fetcher_module.yf = original

        self.assertEqual([item["sector"] for item in profile["sector_weightings"]], ["tech", "fin"])
        self.assertAlmostEqual(profile["sector_weightings"][0]["weight_pct"], 68.0)
        # 沒有持股就要給發行商資訊，前端才有東西可以顯示
        self.assertEqual(profile["holdings_reference"]["issuer"], "元大投信")

    def test_mixed_sector_weights_use_one_shared_scale(self):
        """百分比與比例混在一起時，不能逐筆判斷（CodeRabbit review #11）。"""
        class FakeFundsData:
            fund_overview = {}
            sector_weightings = {"tech": 40.0, "fin": 0.9}
            description = None
            top_holdings = None

        class FakeTicker:
            def __init__(self, symbol):
                self.symbol = symbol
            funds_data = FakeFundsData()

        original = fetcher_module.yf
        fetcher_module.yf = type("FakeYf", (), {"Ticker": FakeTicker})
        try:
            profile = fetcher_module.StockDataFetcher().get_fund_profile("0056.TW")
        finally:
            fetcher_module.yf = original

        weights = {item["sector"]: item["weight_pct"] for item in profile["sector_weightings"]}
        # 總和 40.9 > 1.5，所以整批都當成百分比；0.9 不可以被放大成 90
        self.assertAlmostEqual(weights["tech"], 40.0)
        self.assertAlmostEqual(weights["fin"], 0.9)

    def test_tw_etf_falls_back_to_the_issuer(self):
        reference = fetcher_module._tw_etf_issuer("0050.TW")
        self.assertEqual(reference["issuer"], "元大投信")
        self.assertTrue(reference["url"].startswith("https://"))
        self.assertEqual(fetcher_module._tw_etf_issuer("00878.TW")["issuer"], "國泰投信")

    def test_issuer_fallback_skips_stocks_and_us_symbols(self):
        self.assertIsNone(fetcher_module._tw_etf_issuer("2330.TW"))
        self.assertIsNone(fetcher_module._tw_etf_issuer("SPY"))
        self.assertIsNone(fetcher_module._tw_etf_issuer(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
