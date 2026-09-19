"""資料獲取模組：yfinance 股價 / 基本面 / ETF 資訊 + 本地新聞情緒檔。

相較於舊版的改動：
* 支援 ETF 與上櫃股票：`0050`、`00878`、`006208`、`6488` 都能查到
  （透過 `symbols.candidate_symbols()` 依序嘗試 `.TW` / `.TWO`）。
* 加入記憶體快取（TTL），避免同一個代號在短時間內重複打 yfinance。
* `get_company_overview()` 會依標的種類回傳股票或 ETF 專屬欄位。
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - 部署環境一定會安裝
    yf = None

try:
    from . import symbols as symbol_utils
except ImportError:  # pragma: no cover - 由執行方式決定
    import symbols as symbol_utils


logger = logging.getLogger(__name__)

INTRADAY_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}

# yfinance 對 intraday 有天數限制，超過會直接回空表；先在這裡把 period 修正掉
MAX_PERIOD_BY_INTERVAL = {
    "1m": "5d",
    "2m": "1mo",
    "5m": "1mo",
    "15m": "1mo",
    "30m": "1mo",
    "60m": "2y",
    # yfinance 對 90m 的上限是 60 天；這裡要用 _PERIOD_ORDER 裡有的值才會真的被限制
    "90m": "1mo",
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
            logger.warning("%s 價格抓取失敗: %s", symbol, exc)
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
            logger.warning("%s 概況讀取失敗: %s", symbol, exc)
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
            "exchange": info.get("exchange") or info.get("fullExchangeName"),
            "market": info.get("market"),
            "website": info.get("website"),
            "description": info.get("longBusinessSummary") or info.get("description"),
            "market_cap": info.get("marketCap"),
            "dividend_yield": info.get("dividendYield") or info.get("yield"),
            "dividend_rate": info.get("dividendRate") or info.get("trailingAnnualDividendRate"),
            "trailing_dividend_yield": info.get("trailingAnnualDividendYield"),
            "five_year_avg_dividend_yield": info.get("fiveYearAvgDividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            "ex_dividend_date": _timestamp_to_date(info.get("exDividendDate")),
            "last_split_factor": info.get("lastSplitFactor"),
            "last_split_date": _timestamp_to_date(info.get("lastSplitDate")),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "fifty_two_week_change_pct": _ratio_to_pct(info.get("52WeekChange")),
            "average_volume": info.get("averageVolume"),
            "average_volume_10d": info.get("averageDailyVolume10Day"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "previous_close": info.get("previousClose"),
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
                "inception_date": _timestamp_to_date(info.get("fundInceptionDate")),
                "legal_type": info.get("legalType"),
                "holdings_turnover": info.get("annualHoldingsTurnover"),
            })
        else:
            overview.update({
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "country": info.get("country"),
                "city": info.get("city"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("trailingPegRatio") or info.get("pegRatio"),
                "eps": info.get("trailingEps"),
                "forward_eps": info.get("forwardEps"),
                "book_value": info.get("bookValue"),
                "price_to_book": info.get("priceToBook"),
                "price_to_sales": info.get("priceToSalesTrailing12Months"),
                "profit_margin": info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "gross_margin": info.get("grossMargins"),
                "roe": info.get("returnOnEquity"),
                "roa": info.get("returnOnAssets"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "total_revenue": info.get("totalRevenue"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "free_cashflow": info.get("freeCashflow"),
                "beta": info.get("beta"),
                "employees": info.get("fullTimeEmployees"),
                "target_mean_price": info.get("targetMeanPrice"),
                "recommendation": info.get("recommendationKey"),
                "analyst_count": info.get("numberOfAnalystOpinions"),
                "earnings_date": _timestamp_to_date(info.get("earningsTimestamp")),
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
            logger.warning("讀取新聞情緒資料錯誤: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # 配息與分割（公司行動）
    # ------------------------------------------------------------------ #
    def get_corporate_actions(self, symbol: str, latest_price: float | None = None) -> dict:
        """取得歷年配息與股票分割紀錄。

        回傳的 `dividends.yearly` 是「每年合計配息」，前端用來畫歷年配息長條圖；
        `records` 則是每一次的除息明細。
        """
        if not symbol or yf is None:
            return {"status": "unavailable", "dividends": None, "splits": None}

        cache_key = ("actions", symbol)
        cached = self._profile_cache.get(cache_key)
        if cached is not None:
            return _with_yield(cached, latest_price)

        try:
            ticker = yf.Ticker(symbol)
            dividends = ticker.dividends
            splits = ticker.splits
        except Exception as exc:  # pragma: no cover - 網路例外
            logger.warning("%s 配息 / 分割讀取失敗: %s", symbol, exc)
            return {"status": "unavailable", "dividends": None, "splits": None}

        payload = {
            "status": "ok",
            "dividends": _summarize_dividends(dividends),
            "splits": _summarize_splits(splits),
        }
        if not payload["dividends"] and not payload["splits"]:
            payload["status"] = "empty"
        self._profile_cache.set(cache_key, payload)
        return _with_yield(payload, latest_price)

    # ------------------------------------------------------------------ #
    # ETF 成分（前十大持股 / 產業分布）
    # ------------------------------------------------------------------ #
    def get_fund_profile(self, symbol: str) -> dict | None:
        """ETF 專屬資料；yfinance 版本或資料缺漏時回傳 None。"""
        if not symbol or yf is None:
            return None

        cache_key = ("fund", symbol)
        cached = self._profile_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            funds_data = yf.Ticker(symbol).funds_data
            overview = dict(getattr(funds_data, "fund_overview", None) or {})
            holdings_frame = getattr(funds_data, "top_holdings", None)
            sectors = dict(getattr(funds_data, "sector_weightings", None) or {})
            description = getattr(funds_data, "description", None)
        except Exception:
            return None

        holdings: list[dict] = []
        try:
            if holdings_frame is not None and not holdings_frame.empty:
                for index, row in holdings_frame.head(10).iterrows():
                    weight = _clean_number(row.get("Holding Percent"))
                    holdings.append({
                        "symbol": str(index),
                        "name": str(row.get("Name") or index),
                        "weight_pct": round(weight * 100.0, 2) if weight is not None and weight <= 1 else weight,
                    })
        except Exception:
            holdings = []

        profile = {
            "description": description,
            "overview": {key: _clean_number(value) if isinstance(value, (int, float)) else value
                         for key, value in overview.items()},
            "top_holdings": holdings,
            "sector_weightings": [
                {"sector": key, "weight_pct": round(float(value) * 100.0, 2)}
                for key, value in sorted(sectors.items(), key=lambda item: -float(item[1] or 0))
                if value is not None
            ][:10],
        }
        if not holdings and not profile["sector_weightings"] and not overview:
            return None
        self._profile_cache.set(cache_key, profile)
        return profile

    # 舊介面：保留給既有腳本 / 測試使用
    def get_historical_prices(self, ticker: str, period: str = "1mo", interval: str = "1d"):
        return self.fetch_prices(ticker, period=period, interval=interval)["prices"]


# --------------------------------------------------------------------------- #
# 配息 / 分割整理（純函式，方便測試）
# --------------------------------------------------------------------------- #
FREQUENCY_LABELS = {
    "monthly": "月配",
    "quarterly": "季配",
    "semi_annual": "半年配",
    "annual": "年配",
    "irregular": "不定期",
    "unknown": "—",
}


def _timestamp_to_date(value) -> str | None:
    """yfinance 的日期欄位多半是 Unix timestamp，轉成 YYYY-MM-DD。"""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d")
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return None


def _ratio_to_pct(value) -> float | None:
    numeric = _clean_number(value)
    if numeric is None:
        return None
    return round(numeric * 100.0, 2)


def _clean_number(value):
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _to_date_string(value) -> str | None:
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return None


def _detect_frequency(yearly: list[dict]) -> str:
    """用最近幾個完整年度的配息次數判斷配息頻率。"""
    current_year = datetime.now(timezone.utc).year
    counts = [item["count"] for item in yearly if item["year"] < current_year][-3:]
    if not counts:
        return "unknown"
    average = sum(counts) / len(counts)
    if average >= 10:
        return "monthly"
    if average >= 3.4:
        return "quarterly"
    if average >= 1.6:
        return "semi_annual"
    if average >= 0.8:
        return "annual"
    return "irregular"


def _consecutive_years(yearly: list[dict]) -> int:
    """從最近一個有配息的年度往回數，連續配息幾年。"""
    years = {item["year"] for item in yearly if item["total"] > 0}
    if not years:
        return 0
    cursor = max(years)
    streak = 0
    while cursor in years:
        streak += 1
        cursor -= 1
    return streak


def _summarize_dividends(series) -> dict | None:
    """把 yfinance 的配息 Series 整理成前端好用的結構。"""
    if series is None or len(series) == 0:
        return None

    points: list[tuple[str, float]] = []
    for timestamp, value in series.items():
        amount = _clean_number(value)
        date_text = _to_date_string(timestamp)
        if amount is None or amount <= 0 or not date_text:
            continue
        points.append((date_text, round(amount, 4)))
    if not points:
        return None

    points.sort(key=lambda item: item[0])

    yearly_map: dict[int, dict] = {}
    for date_text, amount in points:
        year = int(date_text[:4])
        entry = yearly_map.setdefault(year, {"year": year, "total": 0.0, "count": 0})
        entry["total"] += amount
        entry["count"] += 1
    yearly = [
        {"year": item["year"], "total": round(item["total"], 4), "count": item["count"]}
        for item in sorted(yearly_map.values(), key=lambda item: item["year"])
    ][-15:]

    today = pd.Timestamp.utcnow().tz_localize(None)
    ttm_total = round(sum(
        amount for date_text, amount in points
        if (today - pd.Timestamp(date_text)).days <= 365
    ), 4)

    current_year = datetime.now(timezone.utc).year
    complete_years = [item for item in yearly if item["year"] < current_year]
    average_3y = round(sum(item["total"] for item in complete_years[-3:]) / len(complete_years[-3:]), 4) if complete_years else None

    frequency = _detect_frequency(yearly)
    latest_date, latest_amount = points[-1]

    return {
        # 完整歷史（新到舊）：定期定額試算需要每一筆配息，
        # 只有前端表格會自己截斷顯示筆數。上限 600 筆純粹是防呆。
        "records": [
            {"date": date_text, "amount": amount}
            for date_text, amount in reversed(points[-600:])
        ],
        "yearly": yearly,
        "ttm_total": ttm_total,
        "average_3y": average_3y,
        "frequency": frequency,
        "frequency_label": FREQUENCY_LABELS.get(frequency, "—"),
        "years_paid": len([item for item in yearly if item["total"] > 0]),
        "consecutive_years": _consecutive_years(yearly),
        "latest": {"date": latest_date, "amount": latest_amount},
        "total_records": len(points),
        "first_date": points[0][0],
    }


def _summarize_splits(series) -> dict | None:
    """整理股票分割（拆股 / 反向分割）紀錄。"""
    if series is None or len(series) == 0:
        return None

    records: list[dict] = []
    for timestamp, value in series.items():
        ratio = _clean_number(value)
        date_text = _to_date_string(timestamp)
        if not ratio or ratio <= 0 or not date_text:
            continue
        if ratio >= 1:
            label = f"1 股 → {_format_ratio(ratio)} 股（分割）"
            kind = "split"
        else:
            label = f"{_format_ratio(1 / ratio)} 股 → 1 股（反向分割）"
            kind = "reverse_split"
        records.append({"date": date_text, "ratio": round(ratio, 4), "label": label, "kind": kind})

    if not records:
        return None
    records.sort(key=lambda item: item["date"], reverse=True)
    return {"records": records[:20], "count": len(records), "latest": records[0]}


def _format_ratio(value: float) -> str:
    return f"{value:.0f}" if abs(value - round(value)) < 1e-6 else f"{value:.2f}"


def _with_yield(payload: dict, latest_price: float | None) -> dict:
    """依最新股價換算現金殖利率（快取的內容不含價格，所以每次重算）。"""
    dividends = payload.get("dividends")
    if not dividends:
        return payload

    enriched = dict(payload)
    dividend_block = dict(dividends)
    price = _clean_number(latest_price)
    if price and price > 0:
        ttm = dividend_block.get("ttm_total") or 0.0
        average = dividend_block.get("average_3y")
        dividend_block["ttm_yield_pct"] = round(ttm / price * 100.0, 2)
        dividend_block["average_3y_yield_pct"] = (
            round(average / price * 100.0, 2) if average else None
        )
    enriched["dividends"] = dividend_block
    return enriched
