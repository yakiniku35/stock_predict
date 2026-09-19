"""台股除權息資料（證交所「除權除息計算結果表」）。

為什麼需要這個模組
------------------
yfinance 的 `Ticker.dividends` 只有**現金股利**；台股的**除權（股票股利）**
不會出現在裡面，只會以「分割」的形式反映在 `Ticker.splits`（例如配股 1 元 →
ratio 1.1）。單看 ratio 無法分辨「真正的分割」與「配股」，也拿不到
「除權息前收盤價 / 參考價 / 權值息值」這些台股特有欄位。

因此這裡另外接證交所的除權除息計算結果表（TWT49U），取得權威資料；
抓不到時呼叫端會退回用 `splits` 推算（見 `fetcher._summarize_rights`）。

資料來源（兩個都試，先試有日期區間的那個）：
    https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=&endDate=&response=json
    https://openapi.twse.com.tw/v1/exchangeReport/TWT49U

注意：這個環境的網路政策擋掉了證交所，所以線上抓取的部分無法實測，
欄位對應是照證交所公開的欄位名稱做「依名稱比對、找不到再依位置」的寬鬆解析，
任何解析失敗都會安靜地回傳空結果，不影響其他功能。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

RWD_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
OPENAPI_URL = "https://openapi.twse.com.tw/v1/exchangeReport/TWT49U"
REQUEST_TIMEOUT = 8
CACHE_TTL_SECONDS = 12 * 3600
# 抓不到時只快取 30 分鐘，避免一次失敗就整天都查不到
FAILURE_TTL_SECONDS = 30 * 60

# 證交所欄位名稱 → 內部欄位。
# 先比對完全相同的標題，再退而求其次用「包含」；每個標題只會對應到一個欄位，
# 否則像「除權息前收盤價」這種標題會同時被 before_price 與 kind 的關鍵字命中。
# 證交所的 openapi 版本偶爾會給英文鍵名，一併列進來當保險。
_FIELD_EXACT: dict[str, tuple[str, ...]] = {
    "date": ("資料日期", "除權息日期", "日期", "Date"),
    "code": ("股票代號", "證券代號", "代號", "Code"),
    "name": ("股票名稱", "證券名稱", "名稱", "Name"),
    "before_price": ("除權息前收盤價", "前收盤價", "ForeclosePrice"),
    "reference_price": ("除權息參考價", "參考價", "減除股利參考價", "LimitUPrice"),
    "value": ("權值+息值", "權值及息值", "權值息值", "RightsValuePlusDividendValue"),
    "kind": ("權/息", "權息", "除權息類別", "類別", "RightsOrDividend"),
}
_FIELD_CONTAINS: dict[str, tuple[str, ...]] = {
    "date": ("資料日期", "除權息日期"),
    "code": ("股票代號", "證券代號"),
    "name": ("股票名稱", "證券名稱"),
    "before_price": ("前收盤價",),
    "reference_price": ("參考價",),
    "value": ("權值", "息值"),
    "kind": (),                      # 「權/息」太短，只接受完全相同的標題
}

_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict]]] = {}
# key → 開始抓取的時間戳。Serverless 回應後容器會被凍結，背景執行緒可能永遠跑不完，
# 所以要記時間，超過 LOADING_STALE_SECONDS 就當作沒人在抓，允許重試。
_loading: dict[str, float] = {}
LOADING_STALE_SECONDS = 90.0


def _normalize_number(value) -> float | None:
    """證交所的數字欄位可能帶逗號或 '-'。"""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in {"-", "--", "X"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_date(value) -> str | None:
    """支援民國年（114/07/18、1140718）與西元年（2025-07-18、20250718）。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    digits = re.sub(r"[^0-9]", "", text)
    if re.fullmatch(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", text):          # 2025-07-18
        year, month, day = (int(part) for part in re.split(r"[/-]", text))
    elif re.fullmatch(r"\d{2,3}[/-]\d{1,2}[/-]\d{1,2}", text):      # 114/07/18
        year, month, day = (int(part) for part in re.split(r"[/-]", text))
    elif len(digits) == 8:                                          # 20250718
        year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
    elif len(digits) == 7:                                          # 1140718（民國）
        year, month, day = int(digits[:3]), int(digits[3:5]), int(digits[5:])
    else:
        return None

    if year < 1911:                      # 民國年 → 西元年
        year += 1911
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _match_field(title: str) -> str | None:
    """把一個證交所欄位標題對應到內部欄位（一個標題只會對應一個欄位）。"""
    clean = str(title).strip()
    for key, titles in _FIELD_EXACT.items():
        if clean in titles:
            return key
    for key, hints in _FIELD_CONTAINS.items():
        if any(hint in clean for hint in hints):
            return key
    return None


def _build_column_map(fields: list[str]) -> dict[str, int]:
    """把證交所的欄位標題對應到內部欄位名稱。"""
    mapping: dict[str, int] = {}
    for index, title in enumerate(fields):
        key = _match_field(title)
        if key and key not in mapping:
            mapping[key] = index
    return mapping


def parse_payload(payload: dict) -> list[dict]:
    """解析證交所回傳的 JSON（同時支援 rwd 與 openapi 兩種格式）。"""
    if not isinstance(payload, dict):
        # openapi 直接回傳陣列的情況
        rows = payload if isinstance(payload, list) else []
        return _parse_dict_rows(rows)

    rows = payload.get("data") or payload.get("aaData") or []
    fields = payload.get("fields") or payload.get("fields0") or []
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return _parse_dict_rows(rows)
    return _parse_list_rows(rows, list(fields))


def _parse_dict_rows(rows: list) -> list[dict]:
    """openapi 版本：每一列都是 {欄位名稱: 值}。"""
    records: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        picked: dict[str, object] = {}
        for title, value in row.items():
            key = _match_field(title)
            if key and key not in picked:
                picked[key] = value
        record = _build_record(picked)
        if record:
            records.append(record)
    return records


def _parse_list_rows(rows: list, fields: list[str]) -> list[dict]:
    """rwd 版本：fields 是標題、data 是二維陣列。"""
    column_map = _build_column_map(fields)
    if "code" not in column_map:
        return []

    records: list[dict] = []
    for row in rows:
        if not isinstance(row, (list, tuple)):
            continue
        picked = {
            key: (row[index] if index < len(row) else None)
            for key, index in column_map.items()
        }
        record = _build_record(picked)
        if record:
            records.append(record)
    return records


def _build_record(picked: dict) -> dict | None:
    """把抓出來的欄位組成一筆紀錄；沒有代號或日期就當這一列無效。"""
    code = str(picked.get("code") or "").strip()
    event_date = _normalize_date(picked.get("date"))
    if not code or not event_date:
        return None

    kind_text = str(picked.get("kind") or "").strip()
    if "權息" in kind_text:
        kind = "both"
    elif "權" in kind_text:
        kind = "rights"
    elif "息" in kind_text:
        kind = "dividend"
    else:
        kind = "unknown"

    return {
        "date": event_date,
        "code": code,
        "name": str(picked.get("name") or "").strip(),
        "kind": kind,
        "kind_label": kind_text or "—",
        "before_price": _normalize_number(picked.get("before_price")),
        "reference_price": _normalize_number(picked.get("reference_price")),
        "value": _normalize_number(picked.get("value")),
        "source": "twse_twt49u",
    }


def _fetch(url: str, params: dict | None = None) -> list[dict]:
    """打一次證交所的端點並解析回傳內容（連線或解析失敗由呼叫端處理）。"""
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0 (StockSense)"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return parse_payload(response.json())


def fetch_records(years: int = 5) -> list[dict]:
    """抓取最近幾年的除權除息紀錄（全市場）。任何失敗都回傳空清單。"""
    end = date.today()
    start = end - timedelta(days=365 * max(1, years))

    attempts = (
        (RWD_URL, {"startDate": start.strftime("%Y%m%d"),
                   "endDate": end.strftime("%Y%m%d"),
                   "response": "json"}),
        (OPENAPI_URL, None),
    )
    for url, params in attempts:
        try:
            records = _fetch(url, params)
            if records:
                return records
        except Exception as exc:
            logger.warning("證交所除權息資料抓取失敗 (%s): %s", url, exc)
    return []


def _cached_records(key: str) -> list[dict] | None:
    """取回仍在有效期內的快取；沒有或過期回傳 None。"""
    entry = _cache.get(key)
    if not entry:
        return None
    stamp, records = entry
    ttl = CACHE_TTL_SECONDS if records else FAILURE_TTL_SECONDS
    if (time.time() - stamp) >= ttl:
        return None
    return records


def _is_loading(key: str) -> bool:
    """呼叫前要先拿 `_lock`。"""
    started = _loading.get(key)
    if started is None:
        return False
    if (time.time() - started) >= LOADING_STALE_SECONDS:
        _loading.pop(key, None)      # 上一輪大概被 Serverless 凍死了
        return False
    return True


def _load_in_background(key: str, years: int) -> None:
    """背景抓取，避免 API 請求卡在證交所的連線上。"""
    with _lock:
        if _is_loading(key):
            return
        _loading[key] = time.time()

    def worker() -> None:
        """在背景抓完之後把結果寫進快取，順便清掉「抓取中」的標記。"""
        try:
            records = fetch_records(years=years)
        except Exception as exc:                 # pragma: no cover - 保險
            logger.warning("證交所除權息背景載入失敗: %s", exc)
            records = []
        with _lock:
            _cache[key] = (time.time(), records)
            _loading.pop(key, None)

    thread = threading.Thread(target=worker, name=f"twse-exrights-{key}", daemon=True)
    thread.start()


def get_records_for(code: str, years: int = 5, blocking: bool = False) -> list[dict]:
    """取得單一股票代號的除權息紀錄。

    預設**不會**阻塞：快取沒資料時丟一條背景執行緒去抓，先回空清單，
    下一次查詢就拿得到（證交所偶爾很慢，API 不該跟著一起慢）。
    `blocking=True` 給離線腳本 / 測試用。
    """
    key = str(years)
    with _lock:
        records = _cached_records(key)

    if records is None:
        if blocking:
            records = fetch_records(years=years)
            with _lock:
                _cache[key] = (time.time(), records)
        else:
            _load_in_background(key, years)
            records = []

    wanted = str(code).upper().split(".")[0]
    return sorted(
        (record for record in records if record["code"].upper() == wanted),
        key=lambda record: record["date"],
        reverse=True,
    )


def is_loading() -> bool:
    """是否正在背景抓取（前端用來顯示「載入中」）。"""
    with _lock:
        return any(_is_loading(key) for key in list(_loading))


def reset_cache() -> None:
    """測試用。"""
    with _lock:
        _cache.clear()
        _loading.clear()
