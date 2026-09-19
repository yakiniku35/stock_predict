"""股票 / ETF 代號解析與搜尋。

主要解決兩件事：
1. 使用者只輸入 `0050`、`00878`、`006208`、`6488` 這種台灣 ETF / 上櫃代號時，
   自動補上正確的 yfinance 後綴（`.TW` 上市、`.TWO` 上櫃），必要時兩個都試。
2. 使用者輸入中文名稱（台積電、高股息、元大台灣50）也能對應到代號，
   並提供給前端做自動完成。
"""

from __future__ import annotations

import os
import re
import unicodedata

try:  # 支援 `python backend/app.py` 與 `from backend import ...` 兩種載入方式
    from .symbol_catalog import CATALOG, QUICK_PICKS
    from . import tw_directory, us_directory
except ImportError:  # pragma: no cover - 由執行方式決定
    from symbol_catalog import CATALOG, QUICK_PICKS
    import tw_directory
    import us_directory

__all__ = [
    "normalize_query",
    "resolve",
    "candidate_symbols",
    "search",
    "quick_picks",
    "classify_quote_type",
    "directory_status",
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
    """以代號 / yfinance 符號 / 中英文全名查字典（內建字典優先，再查證交所清單）。"""
    hit = _BY_CODE.get(text) or _BY_SYMBOL.get(text) or _BY_NAME.get(text)
    if hit:
        return hit
    directory = _directory_index()
    return directory["by_code"].get(text) or directory["by_symbol"].get(text) or directory["by_name"].get(text)


# --------------------------------------------------------------------------- #
# 證交所完整清單（約 3,000 檔，讓沒收錄在內建字典的中文名稱也查得到）
# --------------------------------------------------------------------------- #
_directory_cache: dict | None = None
_directory_versions: tuple = ()

_DIRECTORY_MODULES = (
    (tw_directory, "STOCKSENSE_DISABLE_TW_DIRECTORY"),
    (us_directory, "STOCKSENSE_DISABLE_US_DIRECTORY"),
)


def _enabled_modules() -> list:
    if os.environ.get("STOCKSENSE_DISABLE_DIRECTORY") == "1":
        return []
    return [module for module, flag in _DIRECTORY_MODULES if os.environ.get(flag) != "1"]


def _directory_versions_now() -> tuple:
    versions = []
    for module in _enabled_modules():
        try:
            versions.append(module.cache_version())
        except Exception:  # pragma: no cover
            versions.append(-1)
    return tuple(versions)


def _directory_entries() -> list[dict]:
    """台股 + 美股的完整清單。

    只讀本機資料，需要連外時由 `directory_cache` 在背景抓取，
    所以查詢路徑不會卡在網路上（抓好之前先用內建字典回答）。
    """
    entries: list[dict] = []
    for module in _enabled_modules():
        try:
            entries.extend(module.load_local_entries())
        except Exception:  # pragma: no cover - 任何載入問題都不應影響查詢
            continue
    return entries


def _directory_index() -> dict:
    """建立代號 / 名稱索引；背景載入完成（版本改變）時會自動重建。"""
    global _directory_cache, _directory_versions
    versions = _directory_versions_now()
    if _directory_cache is not None and versions == _directory_versions:
        return _directory_cache

    by_code: dict[str, dict] = {}
    by_symbol: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    entries: list[dict] = []

    for entry in _directory_entries():
        code = str(entry.get("code", "")).upper()
        name_zh = str(entry.get("name_zh") or "")
        name_en = str(entry.get("name_en") or "")
        if not code or (not name_zh and not name_en):
            continue
        if code in _BY_CODE:
            continue  # 內建字典已收錄（有中英文名與別稱），以內建為準
        entries.append(entry)
        by_code.setdefault(code, entry)
        by_symbol.setdefault(str(entry.get("symbol", "")).upper(), entry)
        for name in (name_zh, name_en):
            if name:
                by_name.setdefault(name.upper(), entry)

    _directory_cache = {
        "entries": entries,
        "by_code": by_code,
        "by_symbol": by_symbol,
        "by_name": by_name,
    }
    _directory_versions = versions
    return _directory_cache


def directory_status() -> dict:
    """給 /api/health 顯示名稱對照表狀態。

    **不會觸發任何載入或網路請求**：只回報目前記憶體 / 檔案的狀態，
    所以健康檢查不會因為冷啟動而等待外部服務。
    """
    def _safe(module) -> dict:
        try:
            return module.status()
        except Exception:  # pragma: no cover
            return {"loaded": 0, "ready": False, "error": "unavailable"}

    return {
        "catalog_entries": len(CATALOG),
        "merged_entries": len(_directory_cache["entries"]) if _directory_cache else 0,
        "taiwan": _safe(tw_directory),
        "united_states": _safe(us_directory),
    }


def normalize_query(raw: str | None) -> str:
    """統一輸入格式：全形轉半形、壓縮空白、去掉常見前綴，轉成大寫。

    這裡**保留**完整字串（例如 "SCHWAB U.S. DIVIDEND EQUITY ETF"），
    「2330 台積電」這種「代號 + 名稱」的輸入交給 `candidate_symbols()` 處理。
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", str(raw)).replace("\u3000", " ")
    text = " ".join(text.split())
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

    candidates: list[str] = []
    known = _lookup(text)
    if known:
        candidates.append(known["symbol"])

    first_token = text.split(" ")[0] if " " in text else text
    token_known = _lookup(first_token) if first_token != text else None
    if token_known:
        # 例如貼上「2330 台積電」
        candidates.append(token_known["symbol"])

    if "." in text or text.startswith("^"):
        candidates.append(text)                       # 已自帶後綴或指數符號
    elif _TW_CODE_PATTERN.match(text):
        candidates.extend([f"{text}.TW", f"{text}.TWO"])   # 台股：先上市再上櫃
    elif _TW_CODE_PATTERN.match(first_token):
        candidates.extend([f"{first_token}.TW", f"{first_token}.TWO"])
    elif re.fullmatch(r"[A-Z0-9\-]{1,10}", text):
        candidates.append(text)                       # 英數字視為美股代號
        if not known and len(text) >= 4:
            # 例如輸入 "TESLA"、"PALANTIR"：代號查不到時改用名稱最相近的標的
            best = search(text, limit=1)
            if best:
                candidates.append(best[0]["symbol"])
    elif not known:
        # 中文名稱或多字英文公司名（「台積電」「Schwab U.S. Dividend Equity ETF」）
        best = search(text, limit=1)
        if best:
            candidates.append(best[0]["symbol"])

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
    code = str(entry.get("code", "")).upper()
    symbol = str(entry.get("symbol", "")).upper()
    name_zh = str(entry.get("name_zh", ""))
    name_en = str(entry.get("name_en") or "").upper()
    tags = [str(tag).upper() for tag in entry.get("tags", [])]

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

    # 內建字典的結果不足時，再從證交所完整清單補齊（中文名稱查詢主要靠這裡）
    if len(scored) < limit:
        for entry in _directory_index()["entries"]:
            if kind and entry.get("kind") != kind:
                continue
            score = _score_entry(entry, text)
            if score > 0:
                scored.append((score - 5, entry))  # 略低於內建字典，讓熱門標的排前面

    scored.sort(key=lambda item: (-item[0], item[1]["code"]))

    seen: set[str] = set()
    results: list[dict] = []
    for _, entry in scored:
        if entry["code"] in seen:
            continue
        seen.add(entry["code"])
        results.append(_public(entry))
        if len(results) >= limit:
            break
    return results


def _public(entry: dict) -> dict:
    """輸出給前端的欄位（不含內部 tags）。"""
    return {
        "code": entry.get("code", ""),
        "symbol": entry.get("symbol", ""),
        "name_zh": entry.get("name_zh", ""),
        "name_en": entry.get("name_en") or "",
        "market": entry.get("market", ""),
        "kind": entry.get("kind", "stock"),
        "industry": entry.get("industry") or None,
    }


def quick_picks() -> list[dict]:
    """首頁快速選取清單。"""
    return [_public(_BY_CODE[code]) for code in QUICK_PICKS if code in _BY_CODE]
