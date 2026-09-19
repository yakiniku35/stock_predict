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

try:
    from . import tw_exrights
except ImportError:  # pragma: no cover - 由執行方式決定
    import tw_exrights


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
            return {"status": "unavailable", "dividends": None, "splits": None, "rights": None}

        cache_key = ("actions", symbol)
        cached = self._profile_cache.get(cache_key)
        if cached is not None:
            return _with_yield(cached, latest_price)

        dividends = splits = None
        yfinance_ok = True
        try:
            ticker = yf.Ticker(symbol)
            dividends = ticker.dividends
            splits = ticker.splits
        except Exception as exc:  # pragma: no cover - 網路例外
            # yfinance 掛了不代表證交所的除權資料也拿不到，所以不直接 return
            logger.warning("%s 配息 / 分割讀取失敗: %s", symbol, exc)
            yfinance_ok = False

        payload = {
            "status": "ok",
            "dividends": _summarize_dividends(dividends),
            "splits": _summarize_splits(splits, symbol),
            "rights": _summarize_rights(splits, symbol, _tw_exrights_for(symbol)),
        }
        if not payload["dividends"] and not payload["splits"] and not payload["rights"]:
            payload["status"] = "empty" if yfinance_ok else "unavailable"
        if _is_tw_symbol(symbol) and tw_exrights.is_loading():
            # 證交所資料還在背景抓。這時 payload["rights"] 可能已經有值（由 splits 推算），
            # 但還少了證交所的參考價，所以一樣要標記 pending —— 否則這份「推算版」會被
            # 快取住，要等 TTL 過了才換成權威資料。
            payload["rights_pending"] = True
        if not payload.get("rights_pending"):
            self._profile_cache.set(cache_key, payload)
        return _with_yield(payload, latest_price)

    # ------------------------------------------------------------------ #
    # ETF 成分（前十大持股 / 產業分布）
    # ------------------------------------------------------------------ #
    def get_fund_profile(self, symbol: str) -> dict | None:
        """ETF 專屬資料。

        Yahoo 對台股 ETF 幾乎都沒有成分股，所以查不到時不是直接回 None，
        而是回一個只有 `holdings_reference`（發行商資訊）的結果，
        讓前端可以把「請到發行商官網查」這件事講清楚。
        """
        if not symbol:
            return None

        cache_key = ("fund", symbol)
        cached = self._profile_cache.get(cache_key)
        if cached is not None:
            return cached

        overview: dict = {}
        sectors: dict = {}
        holdings: list[dict] = []
        description = None

        if yf is not None:
            funds_data = _funds_data(yf.Ticker(symbol))
            if funds_data is not None:
                overview = dict(_safe_attr(funds_data, "fund_overview") or {})
                sectors = dict(_safe_attr(funds_data, "sector_weightings") or {})
                description = _safe_attr(funds_data, "description")
                holdings = _parse_top_holdings(_safe_attr(funds_data, "top_holdings"))

        # 產業權重：Yahoo 有時給比例、有時給百分比，也可能塞進非數字，所以先清洗再排序
        cleaned_sectors = [
            (key, weight) for key, weight in
            ((key, _clean_number(value)) for key, value in sectors.items())
            if weight is not None
        ]
        # 比例還是百分比要看「全部加起來」，逐筆判斷會讓 40 與 0.9 混在一起時
        # 變成 40% 與 90%（跟 _parse_top_holdings 同一個道理）
        sector_scale = _scale_weights([weight for _, weight in cleaned_sectors])
        sector_weightings = [
            {"sector": key, "weight_pct": round(weight * sector_scale, 2)}
            for key, weight in sorted(cleaned_sectors, key=lambda item: -abs(item[1]))
        ][:10]

        profile = {
            "description": description,
            "overview": {key: _clean_number(value) if isinstance(value, (int, float)) else value
                         for key, value in overview.items()},
            "top_holdings": holdings,
            "sector_weightings": sector_weightings,
        }

        if not holdings:
            reference = _tw_etf_issuer(symbol)
            if reference:
                profile["holdings_reference"] = reference

        if not holdings and not sector_weightings and not overview and not profile.get("holdings_reference"):
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

    today = pd.Timestamp.now("UTC").tz_localize(None)
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


def _summarize_splits(series, symbol: str | None = None) -> dict | None:
    """整理股票分割（拆股 / 反向分割）紀錄。

    台股的配股也躺在 splits 裡，但那是「除權」不是分割，
    會被 `_summarize_rights()` 接走，所以這裡直接跳過。
    """
    if series is None or len(series) == 0:
        return None

    tw = _is_tw_symbol(symbol)
    records: list[dict] = []
    for timestamp, value in series.items():
        ratio = _clean_number(value)
        date_text = _to_date_string(timestamp)
        if not ratio or ratio <= 0 or not date_text:
            continue
        if tw and _looks_like_tw_rights(ratio):
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


# --------------------------------------------------------------------------- #
# ETF 成分股解析（yfinance 各版本的欄位名稱不太一樣，這裡做寬鬆比對）
# --------------------------------------------------------------------------- #
_HOLDING_SYMBOL_KEYS = ("Symbol", "symbol", "Holding Symbol", "holdingSymbol", "ticker")
_HOLDING_NAME_KEYS = ("Name", "name", "Holding Name", "holdingName", "holding_name")
_HOLDING_WEIGHT_KEYS = (
    "Holding Percent", "holdingPercent", "holding_percent",
    "Holding Percentage", "Weight", "weight", "weight_pct",
)

# 台股 ETF 的成分股 Yahoo 幾乎都沒有，只能導去發行商官網。
# 這裡刻意只放「官網首頁」而不是每檔 ETF 的深層連結——深層網址常常改版就失效。
_TW_ETF_ISSUERS: tuple[tuple[str, str, str | None], ...] = (
    ("元大", "元大投信", "https://www.yuantaetfs.com/"),
    ("國泰", "國泰投信", "https://www.cathaysite.com.tw/"),
    ("富邦", "富邦投信", "https://www.fubon.com/asset-management/"),
    ("中信", "中國信託投信", "https://www.ctbcinvestments.com/"),
    ("群益", "群益投信", "https://www.capitalfund.com.tw/"),
    ("復華", "復華投信", "https://www.fhtrust.com.tw/"),
    ("野村", "野村投信", "https://www.nomurafunds.com.tw/"),
    ("永豐", "永豐投信", None),
    ("兆豐", "兆豐投信", None),
)


def _safe_attr(obj, name: str):
    """讀取屬性時順便吃掉 yfinance 內部可能丟出的例外。"""
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def _extract_field(row, keys: tuple[str, ...]):
    """從 dict / Series 裡依序找第一個存在的欄位。"""
    for key in keys:
        try:
            value = row[key]
        except (KeyError, IndexError, TypeError):
            continue
        if value is not None and not (isinstance(value, float) and math.isnan(value)):
            return value
    return None


def _holdings_rows(frame) -> list[tuple[object, object]]:
    """把 DataFrame / list[dict] 都轉成 (index, row) 的序列。"""
    if frame is None:
        return []
    if hasattr(frame, "iterrows"):
        try:
            if frame.empty:
                return []
            return list(frame.head(10).iterrows())
        except Exception:
            return []
    if isinstance(frame, dict):
        return list(frame.items())[:10]
    if isinstance(frame, (list, tuple)):
        return [(None, row) for row in frame[:10]]
    return []


def _scale_weights(weights: list[float | None]) -> float:
    """Yahoo 有時給比例（0.0712）有時給百分比（7.12），看總和決定要不要乘 100。"""
    numbers = [value for value in weights if value is not None]
    if not numbers:
        return 1.0
    return 100.0 if sum(numbers) <= 1.5 else 1.0


def _parse_top_holdings(frame) -> list[dict]:
    rows = _holdings_rows(frame)
    if not rows:
        return []

    raw: list[tuple[str, str, float | None]] = []
    for index, row in rows:
        symbol = _extract_field(row, _HOLDING_SYMBOL_KEYS)
        if symbol is None and index is not None:
            symbol = index
        name = _extract_field(row, _HOLDING_NAME_KEYS)
        weight = _clean_number(_extract_field(row, _HOLDING_WEIGHT_KEYS))
        label = str(name or symbol or "").strip()
        if not label:
            continue
        raw.append((str(symbol or "").strip(), label, weight))

    scale = _scale_weights([weight for _, _, weight in raw])
    return [
        {
            "symbol": symbol,
            "name": name,
            "weight_pct": round(weight * scale, 2) if weight is not None else None,
        }
        for symbol, name, weight in raw
    ]


def _funds_data(ticker):
    """yfinance 有的版本是 `funds_data` 屬性、有的是 `get_funds_data()`，兩種都試。"""
    for attribute in ("funds_data", "get_funds_data"):
        try:
            value = getattr(ticker, attribute, None)
            if value is None:
                continue
            return value() if callable(value) else value
        except Exception:
            continue
    return None


def _tw_etf_issuer(symbol: str | None) -> dict | None:
    """台股 ETF 查不到成分股時，至少告訴使用者發行商是誰。"""
    if not _is_tw_symbol(symbol):
        return None
    code = str(symbol).split(".")[0]
    catalog: dict = {}
    try:
        catalog = symbol_utils.resolve(code).get("catalog") or {}
    except Exception:  # pragma: no cover - 字典尚未載入
        catalog = {}
    name = catalog.get("name_zh") or ""
    # 字典已經知道這是普通股就不要給發行商連結（理論上不會走到這裡）
    if not name or catalog.get("kind") == "stock":
        return None

    for keyword, issuer, url in _TW_ETF_ISSUERS:
        if keyword and keyword in name:
            return {"issuer": issuer, "url": url, "fund_name": name}
    return {"issuer": None, "url": None, "fund_name": name}


# --------------------------------------------------------------------------- #
# 除權（股票股利）
# --------------------------------------------------------------------------- #
# 台股「配股」在 yfinance 裡是以 splits 的形式出現：每仟股配 100 股會變成
# ratio 1.1。真正的股票分割台股極少見，而且倍數通常是 2 以上，
# 所以 1 < ratio <= 1.5 一律視為配股；超過的仍當成分割。
TW_RIGHTS_RATIO_MAX = 1.5

RIGHTS_KIND_LABELS = {
    "rights": "除權",
    "dividend": "除息",
    "both": "除權息",
    "unknown": "—",
}


def _is_tw_symbol(symbol: str | None) -> bool:
    return bool(symbol) and str(symbol).upper().endswith((".TW", ".TWO"))


def _looks_like_tw_rights(ratio: float | None) -> bool:
    """台股 splits 的 ratio 落在配股區間嗎？"""
    return bool(ratio) and 1.0 < ratio <= TW_RIGHTS_RATIO_MAX


def _rights_from_ratio(date_text: str, ratio: float) -> dict:
    """把 splits 的 ratio 還原成配股資訊。

    ratio 1.1 → 每股多拿 0.1 股 → 每仟股配 100 股。

    這裡刻意「只講股數、不講金額」：把配股換算成「股票股利 N 元」要假設面額
    10 元，但證交所允許無面額或非 10 元面額的股票，ratio 本身也看不出面額，
    算出來的金額可能是錯的。股數則是純粹由 ratio 導出，一定正確。
    """
    bonus = ratio - 1.0
    shares = bonus * 1000.0
    return {
        "date": date_text,
        "kind": "rights",
        "kind_label": RIGHTS_KIND_LABELS["rights"],
        "ratio": round(ratio, 6),
        "shares_per_1000": round(shares, 2),
        "label": f"每仟股配 {_format_ratio(shares)} 股",
        "source": "splits",
    }


def _rights_from_twse(record: dict) -> dict:
    """證交所除權除息計算結果表的一列 → 前端用的結構。"""
    kind = record.get("kind") or "unknown"
    reference = record.get("reference_price")
    before = record.get("before_price")
    drop_pct = None
    if before and reference and before > 0:
        drop_pct = round((before - reference) / before * 100.0, 2)
    return {
        "date": record.get("date"),
        "kind": kind,
        "kind_label": record.get("kind_label") or RIGHTS_KIND_LABELS.get(kind, "—"),
        "before_price": before,
        "reference_price": reference,
        "value": record.get("value"),
        "drop_pct": drop_pct,
        "label": _twse_rights_label(kind, record.get("value")),
        "source": "twse",
    }


def _twse_rights_label(kind: str, value: float | None) -> str:
    name = RIGHTS_KIND_LABELS.get(kind, "除權息")
    if value is None:
        return name
    return f"{name}，權值+息值 {_format_ratio(value)} 元"


def _merge_rights(twse_rows: list[dict], split_rows: list[dict]) -> list[dict]:
    """同一天的兩份資料合併：證交所提供價格，splits 提供配股率。"""
    merged: dict[str, dict] = {}
    for row in twse_rows:
        if row.get("date"):
            merged[row["date"]] = dict(row)

    for row in split_rows:
        existing = merged.get(row["date"])
        if existing is None:
            merged[row["date"]] = dict(row)
            continue
        for key in ("ratio", "shares_per_1000"):
            if row.get(key) is not None:
                existing[key] = row[key]
        # 證交所只說「權」或「權息」，配股率是 splits 才有的細節，補進說明裡
        existing["label"] = f"{existing['label']}；{row['label']}"
        existing["source"] = "twse+splits"

    return sorted(merged.values(), key=lambda item: item["date"], reverse=True)


def _tw_exrights_for(symbol: str | None) -> list[dict]:
    """安全地取證交所除權息紀錄；非台股或抓不到都回空清單。"""
    if not _is_tw_symbol(symbol):
        return []
    code = str(symbol).split(".")[0]
    try:
        return tw_exrights.get_records_for(code)
    except Exception as exc:  # pragma: no cover - 網路 / 解析例外
        logger.warning("%s 證交所除權息讀取失敗: %s", symbol, exc)
        return []


def _summarize_rights(series, symbol: str | None = None, twse_records: list[dict] | None = None) -> dict | None:
    """整理除權（股票股利）紀錄；非台股或查無資料回傳 None。"""
    if not _is_tw_symbol(symbol):
        return None

    split_rows: list[dict] = []
    if series is not None and len(series) > 0:
        for timestamp, value in series.items():
            ratio = _clean_number(value)
            date_text = _to_date_string(timestamp)
            if not date_text or not _looks_like_tw_rights(ratio):
                continue
            split_rows.append(_rights_from_ratio(date_text, ratio))

    twse_rows = [
        _rights_from_twse(record)
        for record in (twse_records or [])
        # 純除息已經在「配息」分頁了，這裡只留跟除權有關的
        if record.get("kind") in {"rights", "both"} and record.get("date")
    ]

    records = _merge_rights(twse_rows, split_rows)
    if not records:
        return None

    total_shares = sum(row.get("shares_per_1000") or 0.0 for row in records)
    sources = {row["source"] for row in records}

    return {
        "records": records[:30],
        "count": len(records),
        "latest": records[0],
        "total_shares_per_1000": round(total_shares, 2) if total_shares else None,
        "has_twse": any("twse" in source for source in sources),
        "sources": sorted(sources),
    }


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
