"""股票 / ETF 代號解析與搜尋。

主要解決兩件事：
1. 使用者只輸入 `0050`、`00878`、`006208`、`6488` 這種台灣 ETF / 上櫃代號時，
   自動補上正確的 yfinance 後綴（`.TW` 上市、`.TWO` 上櫃），必要時兩個都試。
2. 使用者輸入中文名稱（台積電、高股息、元大台灣50）也能對應到代號，
   並提供給前端做自動完成。
"""

from __future__ import annotations

import re
import unicodedata

try:  # 支援 `python backend/app.py` 與 `from backend import ...` 兩種載入方式
    from .symbol_catalog import CATALOG, QUICK_PICKS
except ImportError:  # pragma: no cover - 由執行方式決定
    from symbol_catalog import CATALOG, QUICK_PICKS

__all__ = [
    "normalize_query",
    "resolve",
    "candidate_symbols",
    "search",
    "quick_picks",
    "classify_quote_type",
]


# 台灣代號：4~6 碼數字，可帶一個英文字尾（例如 00679B 債券 ETF、00631L 槓桿 ETF）
_TW_CODE_PATTERN = re.compile(r"^(\d{4,6})([A-Z]?)$")
_SUFFIXED_PATTERN = re.compile(r"^[\w.\-^]+$")

_BY_CODE: dict[str, dict] = {}
_BY_SYMBOL: dict[str, dict] = {}
_BY_NAME: dict[str, dict] = {}
for _entry in CATALOG:
    _BY_CODE.setdefault(_entry["code"].upper(), _entry)
    _BY_SYMBOL.setdefault(_entry["symbol"].upper(), _entry)
    _BY_NAME.setdefault(_entry["name_zh"].upper(), _entry)
    _BY_NAME.setdefault(_entry["name_en"].upper(), _entry)


def _lookup(text: str) -> dict | None:
    """以代號 / yfinance 符號 / 中英文全名查字典。"""
    return _BY_CODE.get(text) or _BY_SYMBOL.get(text) or _BY_NAME.get(text)


def normalize_query(raw: str | None) -> str:
    """去除全形字元、空白與常見雜訊，統一成大寫代號字串。"""
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", str(raw)).strip()
    text = text.replace("　", " ").strip()
    # 使用者常貼上 "2330 台積電" 或 "TW:2330"
    text = text.split()[0] if text and " " in text else text
    text = text.removeprefix("TW:").removeprefix("US:")
    return text.upper()


def classify_quote_type(quote_type: str | None) -> str:
    """把 yfinance 的 quoteType 轉成本專案使用的種類。"""
    value = (quote_type or "").upper()
    if value == "ETF":
        return "etf"
    if value in {"MUTUALFUND", "MONEYMARKET"}:
        return "fund"
    if value == "INDEX":
        return "index"
    if value in {"CRYPTOCURRENCY", "CURRENCY"}:
        return "crypto"
    if value == "EQUITY":
        return "stock"
    return "unknown"


def candidate_symbols(query: str) -> list[str]:
    """回傳要依序嘗試的 yfinance 代號清單（第一個優先）。"""
    text = normalize_query(query)
    if not text:
        return []

    known = _lookup(text)
    candidates: list[str] = []

    if known:
        candidates.append(known["symbol"])

    if "." in text or text.startswith("^"):
        # 已經自帶後綴或指數符號，直接使用
        candidates.append(text)
    elif _TW_CODE_PATTERN.match(text):
        # 台灣代號：上市（.TW）優先，找不到再試上櫃（.TWO）
        candidates.extend([f"{text}.TW", f"{text}.TWO"])
    elif re.fullmatch(r"[A-Z0-9\-]{1,10}", text):
        # 英數字視為美股代號
        candidates.append(text)
        if not known and len(text) >= 4:
            # 例如輸入 "TESLA"：代號本身查不到資料時，改用字典中最相近的標的
            best = search(text, limit=1)
            if best:
                candidates.append(best[0]["symbol"])
    elif not known:
        # 中文名稱（例如「台積電」「高股息」）：用離線字典找最接近的標的
        best = search(text, limit=1)
        if best:
            candidates.append(best[0]["symbol"])

    # 去重但保留順序
    seen: set[str] = set()
    ordered: list[str] = []
    for symbol in candidates:
        if symbol and symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    return ordered


def resolve(query: str) -> dict:
    """解析使用者輸入，回傳代號候選與已知的字典資訊。"""
    text = normalize_query(query)
    candidates = candidate_symbols(text)
    known = _lookup(text)
    if not known and candidates:
        known = _BY_SYMBOL.get(candidates[0].upper())

    market = None
    if known:
        market = known["market"]
    elif candidates and candidates[0].endswith(".TW"):
        market = "TW"
    elif candidates and candidates[0].endswith(".TWO"):
        market = "TWO"
    elif candidates:
        market = "US"

    return {
        "input": text,
        "candidates": candidates,
        "primary": candidates[0] if candidates else "",
        "display_code": known["code"] if known else text,
        "catalog": known,
        "market": market,
        "kind": known["kind"] if known else None,
    }


def _score_entry(entry: dict, query: str) -> int:
    """搜尋排序分數，分數越高越前面；0 代表不匹配。"""
    code = entry["code"].upper()
    symbol = entry["symbol"].upper()
    name_zh = entry["name_zh"]
    name_en = entry["name_en"].upper()
    tags = [tag.upper() for tag in entry.get("tags", [])]

    if query == code or query == symbol:
        return 1000
    if code.startswith(query) or symbol.startswith(query):
        return 900 - len(code)
    if query == name_zh:
        return 880
    if name_zh.startswith(query):
        return 800 - len(name_zh)
    if name_en.startswith(query):
        return 780 - len(name_en)
    if query in name_zh:
        return 600
    if query in name_en:
        return 560
    if any(query == tag for tag in tags):
        return 540
    if any(query in tag for tag in tags):
        return 480
    if query in code or query in symbol:
        return 400
    return 0


def search(query: str, limit: int = 10, kind: str | None = None) -> list[dict]:
    """在離線字典中搜尋標的，供前端自動完成使用。"""
    text = normalize_query(query)
    pool = [entry for entry in CATALOG if not kind or entry["kind"] == kind]
    if text in _BY_CODE or text in _BY_SYMBOL:
        pass

    if not text:
        picks = [_BY_CODE[code] for code in QUICK_PICKS if code in _BY_CODE]
        return [_public(entry) for entry in picks][:limit]

    scored: list[tuple[int, dict]] = []
    for entry in pool:
        score = _score_entry(entry, text)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], item[1]["code"]))
    return [_public(entry) for _, entry in scored[:limit]]


def _public(entry: dict) -> dict:
    """輸出給前端的欄位（不含內部 tags）。"""
    return {
        "code": entry["code"],
        "symbol": entry["symbol"],
        "name_zh": entry["name_zh"],
        "name_en": entry["name_en"],
        "market": entry["market"],
        "kind": entry["kind"],
    }


def quick_picks() -> list[dict]:
    """首頁快速選取清單。"""
    return [_public(_BY_CODE[code]) for code in QUICK_PICKS if code in _BY_CODE]
