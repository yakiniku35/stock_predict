"""台股（上市／上櫃）證券中文名稱對照表。

為什麼需要這個模組
------------------
`symbol_catalog.py` 只收錄約 125 檔熱門標的，使用者輸入「長榮航」「京元電子」這類
沒收錄的中文名稱就會查不到。這裡改成直接向 **證交所 ISIN 公開頁面** 取得完整清單
（上市 + 上櫃，包含股票與 ETF），共約 3,000 檔，讓中文查詢可以涵蓋整個台股。

三層設計，確保任何環境都不會壞
------------------------------
1. `backend/data/tw_securities.json`：可選的隨程式碼一起發佈的快照
   （用 `python scripts/update_tw_securities.py` 產生）。
2. `data/runtime/tw_securities.json`：執行時抓到的資料會寫在這裡，7 天內直接沿用。
3. 兩者都沒有且連不到證交所時 → 回傳空清單，系統自動退回內建字典，功能不中斷。
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import requests

ROOT_PATH = Path(__file__).resolve().parent.parent
BUNDLED_SNAPSHOT = Path(__file__).resolve().parent / "data" / "tw_securities.json"
RUNTIME_CACHE = ROOT_PATH / "data" / "runtime" / "tw_securities.json"

# 證交所 ISIN 查詢頁：strMode=2 上市、strMode=4 上櫃
ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600
REQUEST_TIMEOUT = 20

_CODE_PATTERN = re.compile(r"^(\d{4,6}[A-Z]?)$")
_CELL_PATTERN = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_ROW_PATTERN = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")

_lock = threading.Lock()
_entries: list[dict] | None = None
_load_error: str | None = None


def _clean(cell: str) -> str:
    text = _TAG_PATTERN.sub("", cell)
    text = text.replace("&nbsp;", " ").replace("　", " ")
    return " ".join(text.split()).strip()


def _kind_from_cfi(cfi_code: str) -> str | None:
    """用 CFICode 判斷證券種類，只保留股票與 ETF。"""
    code = (cfi_code or "").upper()
    if code.startswith("ES"):
        return "stock"
    if code.startswith("CE"):
        return "etf"
    return None


def parse_isin_html(html: str, default_market: str) -> list[dict]:
    """解析證交所 ISIN 頁面，回傳 [{code, symbol, name_zh, market, kind, listed_at, industry}]。"""
    results: list[dict] = []
    for row_html in _ROW_PATTERN.findall(html):
        cells = [_clean(cell) for cell in _CELL_PATTERN.findall(row_html)]
        if len(cells) < 6:
            continue  # 分類標題列只有一格

        code_name = cells[0]
        parts = code_name.split()
        if len(parts) < 2:
            continue
        code, name = parts[0], " ".join(parts[1:])
        if not _CODE_PATTERN.match(code):
            continue

        kind = _kind_from_cfi(cells[5])
        if kind is None:
            continue  # 略過權證、債券、存託憑證等

        market_text = cells[3] or default_market
        market = "TWO" if "上櫃" in market_text else "TW"
        suffix = ".TWO" if market == "TWO" else ".TW"

        results.append({
            "code": code,
            "symbol": f"{code}{suffix}",
            "name_zh": name,
            "name_en": "",
            "market": market,
            "kind": kind,
            "listed_at": cells[2],
            "industry": cells[4],
            "source": "twse_isin",
        })
    return results


def fetch_from_twse() -> list[dict]:
    """向證交所抓取上市 + 上櫃清單（需要網路）。"""
    entries: list[dict] = []
    for mode, default_market in ((2, "上市"), (4, "上櫃")):
        response = requests.get(
            ISIN_URL.format(mode=mode),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        # 證交所頁面是 MS950（Big5）編碼
        response.encoding = response.apparent_encoding or "ms950"
        entries.extend(parse_isin_html(response.text, default_market))
    return entries


def _read_json(path: Path) -> list[dict] | None:
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("entries") if isinstance(payload, dict) else payload
        return entries if isinstance(entries, list) and entries else None
    except Exception:
        return None


def _write_cache(entries: list[dict]) -> None:
    try:
        RUNTIME_CACHE.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_CACHE.write_text(
            json.dumps({"updated_at": time.time(), "entries": entries}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # 唯讀檔案系統（例如 Serverless）就跳過，不影響功能


def _cache_is_fresh(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        updated_at = float(payload.get("updated_at", 0))
        return (time.time() - updated_at) < CACHE_MAX_AGE_SECONDS
    except Exception:
        return False


def load_entries(force_refresh: bool = False) -> list[dict]:
    """取得完整台股清單；任何失敗都回傳空清單（呼叫端自動退回內建字典）。"""
    global _entries, _load_error

    with _lock:
        if _entries is not None and not force_refresh:
            return _entries

        if not force_refresh:
            bundled = _read_json(BUNDLED_SNAPSHOT)
            if bundled:
                _entries = bundled
                return _entries
            if RUNTIME_CACHE.is_file() and _cache_is_fresh(RUNTIME_CACHE):
                cached = _read_json(RUNTIME_CACHE)
                if cached:
                    _entries = cached
                    return _entries

        try:
            entries = fetch_from_twse()
            if entries:
                _write_cache(entries)
                _entries = entries
                _load_error = None
                return _entries
            _load_error = "證交所回傳空清單"
        except Exception as exc:
            _load_error = str(exc)

        # 抓不到就退回過期的快取（總比沒有好）
        stale = _read_json(RUNTIME_CACHE)
        _entries = stale or []
        return _entries


def status() -> dict:
    """給 /api/health 顯示目前名稱對照表的狀態。"""
    entries = load_entries()
    return {
        "loaded": len(entries),
        "source": (entries[0].get("source") if entries else None),
        "bundled_snapshot": BUNDLED_SNAPSHOT.is_file(),
        "runtime_cache": RUNTIME_CACHE.is_file(),
        "error": _load_error,
    }
