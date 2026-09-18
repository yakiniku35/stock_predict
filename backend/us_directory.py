"""美股（含 ETF）代號與公司名稱對照表。

資料來源：NASDAQ Trader 公開的證券清單（純文字、以 `|` 分隔），
涵蓋 NASDAQ 與其他交易所（NYSE、NYSE American、CBOE…）共約 11,000 檔，
而且有 ETF 旗標，可以正確區分個股與 ETF。

    https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
    https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt

載入策略與台股相同（快照 → 執行時快取 → 線上抓取 → 退回內建字典），
細節見 `directory_cache.py`。
"""

from __future__ import annotations

import re

import requests

try:
    from .directory_cache import DirectoryCache
except ImportError:  # pragma: no cover - 由執行方式決定
    from directory_cache import DirectoryCache

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
REQUEST_TIMEOUT = 25

# 去掉證券名稱後面的類別描述，例如 "Apple Inc. - Common Stock"
_NAME_SUFFIX = re.compile(
    r"\s*-\s*(Common Stock.*|Class [A-Z].*|Ordinary Shares.*|American Depositary Shares.*|"
    r"Depositary Shares.*|Warrant.*|Unit.*|Preferred.*|Right.*)$",
    re.IGNORECASE,
)
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# 這些關鍵字代表權證 / 特別股 / SPAC 單位，一般使用者不會查，直接排除
_EXCLUDE_KEYWORDS = ("warrant", "% notes", "depositary share, each", " unit", "right")


def _clean_name(raw: str) -> str:
    name = _NAME_SUFFIX.sub("", (raw or "").strip())
    return name.strip(" -")


def _to_yahoo_symbol(symbol: str) -> str:
    """NASDAQ 用 `BRK.B`，yfinance 用 `BRK-B`。"""
    return symbol.strip().upper().replace(".", "-")


def parse_symbol_file(text: str, symbol_index: int, name_index: int,
                      etf_index: int | None, test_index: int | None,
                      exchange_index: int | None = None) -> list[dict]:
    """解析 NASDAQ Trader 的 `|` 分隔檔。"""
    entries: list[dict] = []
    for line_number, line in enumerate(text.splitlines()):
        if not line.strip() or line.startswith("File Creation Time"):
            continue
        parts = line.split("|")
        if line_number == 0 or len(parts) <= max(
            filter(None, [symbol_index, name_index, etf_index, test_index, exchange_index])
        ):
            continue

        if test_index is not None and parts[test_index].strip().upper() == "Y":
            continue  # 測試用代號

        raw_symbol = parts[symbol_index].strip().upper()
        if not raw_symbol or not _SYMBOL_PATTERN.match(raw_symbol):
            continue

        raw_name = parts[name_index].strip()
        lowered = raw_name.lower()
        if any(keyword in lowered for keyword in _EXCLUDE_KEYWORDS):
            continue

        is_etf = etf_index is not None and parts[etf_index].strip().upper() == "Y"
        entries.append({
            "code": _to_yahoo_symbol(raw_symbol),
            "symbol": _to_yahoo_symbol(raw_symbol),
            "name_zh": "",
            "name_en": _clean_name(raw_name),
            "market": "US",
            "kind": "etf" if is_etf else "stock",
            "exchange": parts[exchange_index].strip() if exchange_index is not None else "NASDAQ",
            "source": "nasdaq_trader",
        })
    return entries


def fetch_from_nasdaq() -> list[dict]:
    """抓取 NASDAQ 與其他交易所的完整清單。"""
    headers = {"User-Agent": "Mozilla/5.0 (StockSense symbol directory)"}

    nasdaq = requests.get(NASDAQ_URL, headers=headers, timeout=REQUEST_TIMEOUT)
    nasdaq.raise_for_status()
    # Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
    entries = parse_symbol_file(nasdaq.text, symbol_index=0, name_index=1, etf_index=6, test_index=3)

    other = requests.get(OTHER_URL, headers=headers, timeout=REQUEST_TIMEOUT)
    other.raise_for_status()
    # ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
    entries.extend(parse_symbol_file(
        other.text, symbol_index=0, name_index=1, etf_index=4, test_index=6, exchange_index=2,
    ))

    deduped: dict[str, dict] = {}
    for entry in entries:
        deduped.setdefault(entry["code"], entry)
    return list(deduped.values())


_cache = DirectoryCache("us_securities", fetch_from_nasdaq)


def load_entries(force_refresh: bool = False) -> list[dict]:
    return _cache.load(force_refresh=force_refresh)


def status() -> dict:
    return _cache.status()
