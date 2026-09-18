"""資料獲取模組：yfinance 股價 / 基本面 / ETF 資訊 + 本地新聞情緒檔。

相較於舊版的改動：
* 支援 ETF 與上櫃股票：`0050`、`00878`、`006208`、`6488` 都能查到
  （透過 `symbols.candidate_symbols()` 依序嘗試 `.TW` / `.TWO`）。
* 加入記憶體快取（TTL），避免同一個代號在短時間內重複打 yfinance。
* `get_company_overview()` 會依標的種類回傳股票或 ETF 專屬欄位。
"""

from __future__ import annotations

import json
import os
import threading
import time

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - 部署環境一定會安裝
    yf = None

try:
    from . import symbols as symbol_utils
except ImportError:  # pragma: no cover - 由執行方式決定
    import symbols as symbol_utils


INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}

# yfinance 對 intraday 有天數限制，超過會直接回空表；先在這裡把 period 修正掉
MAX_PERIOD_BY_INTERVAL = {
    "1m": "5d",
    "2m": "1mo",
    "5m": "1mo",
    "15m": "1mo",
    "30m": "1mo",
    "60m": "2y",
    "90m": "60d",
    "1h": "2y",
}

_PERIOD_ORDER = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]
_PERIOD_RANK = {period: index for index, period in enumerate(_PERIOD_ORDER)}


class _TTLCache:
    """極簡的執行緒安全 TTL 快取（Serverless 冷啟動後自然清空）。"""

    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 128):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._store: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if expires_at < time.time():
                self._store.pop(key, None)
                return None
            return value

    def set(self, key, value):
        with self._lock:
            if len(self._store) >= self.max_entries:
                oldest = min(self._store.items(), key=lambda item: item[1][0])[0]
                self._store.pop(oldest, None)
            self._store[key] = (time.time() + self.ttl, value)


def clamp_period(period: str, interval: str) -> str:
    """把 period 修正成該 interval 允許的最大範圍。"""
    limit = MAX_PERIOD_BY_INTERVAL.get(interval)
    if not limit:
        return period
    if _PERIOD_RANK.get(period, 0) > _PERIOD_RANK.get(limit, len(_PERIOD_ORDER)):
        return limit
    return period


class StockDataFetcher:
    """負責 yfinance 串接與組員新聞資料整合。"""

    def __init__(self, project_root: str | None = None, cache_ttl: float = 300.0):
        if project_root is None:
            self.project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..")
            )
        else:
            self.project_root = project_root
        self._price_cache = _TTLCache(ttl_seconds=cache_ttl)
        self._profile_cache = _TTLCache(ttl_seconds=cache_ttl * 4)

    # ------------------------------------------------------------------ #
    # 價格
    # ------------------------------------------------------------------ #
    def fetch_prices(self, query: str, period: str = "1mo", interval: str = "1d") -> dict:
        """回傳 {'prices': [...], 'symbol': 實際使用的代號, 'resolution': {...}}。

        找不到資料時 prices 為 None，並在 `error` 說明原因。
        """
        resolution = symbol_utils.resolve(query)
        candidates = resolution["candidates"]
        effective_period = clamp_period(period, interval)

        if not candidates:
            return {"prices": None, "symbol": None, "resolution": resolution,
                    "error": "請輸入股票或 ETF 代號"}
        if yf is None:  # pragma: no cover
            return {"prices": None, "symbol": None, "resolution": resolution,
                    "error": "yfinance 套件未安裝"}

        tried: list[str] = []
        for symbol in candidates:
            tried.append(symbol)
            cache_key = (symbol, effective_period, interval)
            cached = self._price_cache.get(cache_key)
            if cached is not None:
                return {"prices": cached, "symbol": symbol, "resolution": resolution,
                        "period": effective_period, "cached": True, "tried": tried}

            prices = self._download(symbol, effective_period, interval)
            if prices:
                self._price_cache.set(cache_key, prices)
                return {"prices": prices, "symbol": symbol, "resolution": resolution,
                        "period": effective_period, "cached": False, "tried": tried}

        return {
            "prices": None,
            "symbol": None,
            "resolution": resolution,
            "period": effective_period,
            "tried": tried,
            "error": f"查無 {resolution['input']} 的價格資料（已嘗試 {', '.join(tried)}）",
        }

    def _download(self, symbol: str, period: str, interval: str) -> list[dict] | None:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval, auto_adjust=False)
            if df is None or df.empty:
                return None
            return self._clean(df, interval)
        except Exception as exc:  # pragma: no cover - 網路例外
            print(f"[fetcher] {symbol} 抓取失敗: {exc}")
            return None

    @staticmethod
    def _clean(df: pd.DataFrame, interval: str) -> list[dict] | None:
        """資料清洗：統一日期欄位、去除缺值、轉成前端需要的結構。"""
        df = df.reset_index()
        date_col = "Datetime" if "Datetime" in df.columns else "Date"
        if date_col not in df.columns:
            return None

        date_values = pd.to_datetime(df[date_col], errors="coerce")
        if interval in INTRADAY_INTERVALS:
            df["display_date"] = date_values.dt.strftime("%Y-%m-%d %H:%M")
        else:
            df["display_date"] = date_values.dt.strftime("%Y-%m-%d")

        required = ["Open", "High", "Low", "Close"]
        if any(column not in df.columns for column in required):
            return None
        df = df.dropna(subset=required + ["display_date"])
        if df.empty:
            return None

        prices: list[dict] = []
        for _, row in df.iterrows():
            volume = row.get("Volume", 0)
            prices.append({
                "date": row["display_date"],
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(volume) if pd.notna(volume) else 0,
            })
        return prices

    # ------------------------------------------------------------------ #
    # 標的概況（股票 / ETF 分開處理）
    # ------------------------------------------------------------------ #
    def get_company_overview(self, symbol: str, catalog_entry: dict | None = None) -> dict | None:
        """取得標的概況；ETF 會回傳費用率、追蹤標的等 ETF 專屬欄位。"""
        if not symbol or yf is None:
            return None

        cached = self._profile_cache.get(symbol)
        if cached is not None:
            return cached

        try:
            info = yf.Ticker(symbol).info or {}
        except Exception as exc:  # pragma: no cover - 網路例外
            print(f"[fetcher] {symbol} 概況讀取失敗: {exc}")
            info = {}

        kind = symbol_utils.classify_quote_type(info.get("quoteType"))
        if kind == "unknown" and catalog_entry:
            kind = catalog_entry.get("kind", "unknown")

        name = (
            info.get("longName")
            or info.get("shortName")
            or (catalog_entry or {}).get("name_zh")
            or symbol
        )

        overview = {
            "symbol": info.get("symbol") or symbol,
            "name": name,
            "name_zh": (catalog_entry or {}).get("name_zh"),
            "kind": kind,
            "kind_label": {"etf": "ETF", "stock": "股票", "index": "指數",
                           "fund": "基金", "crypto": "加密貨幣"}.get(kind, "標的"),
            "currency": info.get("currency") or ("TWD" if symbol.endswith((".TW", ".TWO")) else "USD"),
            "exchange": info.get("exchange"),
            "website": info.get("website"),
            "description": info.get("longBusinessSummary") or info.get("description"),
            "market_cap": info.get("marketCap"),
            "dividend_yield": info.get("dividendYield") or info.get("yield"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "average_volume": info.get("averageVolume"),
        }

        if kind == "etf":
            overview.update({
                "fund_family": info.get("fundFamily"),
                "category": info.get("category"),
                "total_assets": info.get("totalAssets"),
                "expense_ratio": info.get("netExpenseRatio") or info.get("annualReportExpenseRatio"),
                "nav_price": info.get("navPrice"),
                "ytd_return": info.get("ytdReturn"),
                "three_year_return": info.get("threeYearAverageReturn"),
                "five_year_return": info.get("fiveYearAverageReturn"),
                "beta": info.get("beta3Year") or info.get("beta"),
                "inception_date": info.get("fundInceptionDate"),
            })
        else:
            overview.update({
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "eps": info.get("trailingEps"),
                "profit_margin": info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "roe": info.get("returnOnEquity"),
                "debt_to_equity": info.get("debtToEquity"),
                "beta": info.get("beta"),
                "employees": info.get("fullTimeEmployees"),
                "price_to_book": info.get("priceToBook"),
                "revenue_growth": info.get("revenueGrowth"),
            })

        self._profile_cache.set(symbol, overview)
        return overview

    # ------------------------------------------------------------------ #
    # 新聞情緒（組員 Phase 2/3 管線產出）
    # ------------------------------------------------------------------ #
    def get_news_sentiment_from_pipeline(self, ticker: str) -> list[dict]:
        news_file_path = os.path.join(
            self.project_root, "data", "normalized", "news_with_sentiment.jsonl"
        )
        if not os.path.exists(news_file_path):
            return []

        # 允許 2330 / 2330.TW 互相對應
        wanted = {str(ticker).upper(), str(ticker).upper().split(".")[0]}
        matched: list[dict] = []
        try:
            with open(news_file_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    record_ticker = str(record.get("ticker") or "").upper()
                    if record_ticker in wanted or record_ticker.split(".")[0] in wanted:
                        matched.append({
                            "id": record.get("id"),
                            "source": record.get("source"),
                            "headline": record.get("headline"),
                            "url": record.get("url"),
                            "published_at": record.get("published_at"),
                            "sentiment_score": record.get("sentiment_score", 0.0),
                            "sentiment_label": record.get("sentiment_label", "neutral"),
                        })
            matched.sort(key=lambda item: item.get("published_at") or "", reverse=True)
            return matched
        except Exception as exc:
            print(f"[fetcher] 讀取新聞情緒資料錯誤: {exc}")
            return []

    # 舊介面：保留給既有腳本 / 測試使用
    def get_historical_prices(self, ticker: str, period: str = "1mo", interval: str = "1d"):
        return self.fetch_prices(ticker, period=period, interval=interval)["prices"]
