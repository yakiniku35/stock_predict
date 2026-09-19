"""台股（上市／上櫃）證券中文名稱對照表。

為什麼需要這個模組
------------------
`symbol_catalog.py` 只收錄約 125 檔熱門標的，使用者輸入「長榮航」「京元電子」這類
沒收錄的中文名稱就會查不到。這裡改成直接向 **證交所 ISIN 公開頁面** 取得完整清單
（上市 + 上櫃，包含股票與 ETF），共約 3,000 檔，讓中文查詢可以涵蓋整個台股。

載入策略見 `directory_cache.py`（快照 → 執行時快取 → 線上抓取 → 退回內建字典）。
"""

from __future__ import annotations

import re

import requests

try:
    from .directory_cache import DirectoryCache
except ImportError:  # pragma: no cover - 由執行方式決定
    from directory_cache import DirectoryCache

# 證交所 ISIN 查詢頁：strMode=2 上市、strMode=4 上櫃
ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
REQUEST_TIMEOUT = 15

_CODE_PATTERN = re.compile(r"^(\d{4,6}[A-Z]?)$")
_CELL_PATTERN = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_ROW_PATTERN = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")

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
        # 證交所這個頁面固定以 MS950（Big5）輸出，但 HTTP 標頭沒有標示。
        # 不用 apparent_encoding 偵測：那是統計猜測，中文字少時可能猜成其他編碼，
        # 而且每次都要掃描整份文件。
        response.encoding = "ms950"
        entries.extend(parse_isin_html(response.text, default_market))
    return entries


_cache = DirectoryCache("tw_securities", fetch_from_twse)
BUNDLED_SNAPSHOT = _cache.bundled_path
RUNTIME_CACHE = _cache.runtime_path


def load_entries(force_refresh: bool = False) -> list[dict]:
    """同步載入（必要時連外）；給更新腳本使用。"""
    return _cache.load(force_refresh=force_refresh)


def load_local_entries() -> list[dict]:
    """查詢路徑專用：只讀本機資料，需要連外時改在背景抓取，不會卡住請求。"""
    return _cache.load_local()


def status() -> dict:
    """給 /api/health 顯示目前名稱對照表的狀態（不會觸發載入）。"""
    return _cache.status()


def cache_version() -> int:
    """資料版本；背景載入完成後會改變，供索引判斷是否重建。"""
    return _cache.version
