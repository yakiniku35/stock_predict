"""證券名稱對照表的共用快取層。

台股（`tw_directory.py`）與美股（`us_directory.py`）都用這裡的邏輯：

1. 先找隨程式碼發佈的快照 `backend/data/<name>.json`
2. 再找執行時快取 `data/runtime/<name>.json`（預設 7 天內有效）
3. 都沒有才上網抓，抓到後寫入執行時快取
4. 全部失敗就回傳空清單，呼叫端自動退回內建字典

重要：**請求路徑不會卡在網路上**。
`load_local()` 只讀記憶體與本機檔案，需要連外時改在背景執行緒抓取，
在抓好之前查詢會先用內建字典回答；`status()` 則完全不會觸發載入，
所以 `/api/health` 這類健康檢查不會因為冷啟動而等上數十秒。
完整的同步載入（`load()`）只留給 `scripts/update_symbol_directory.py` 這類工具使用。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

ROOT_PATH = Path(__file__).resolve().parent.parent
BUNDLED_DIR = Path(__file__).resolve().parent / "data"
RUNTIME_DIR = ROOT_PATH / "data" / "runtime"
DEFAULT_MAX_AGE_SECONDS = 7 * 24 * 3600


class DirectoryCache:
    """單一清單的載入器（執行緒安全，行程內只會嘗試抓取一次）。"""

    def __init__(self, name: str, fetcher: Callable[[], list[dict]],
                 max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS):
        self.name = name
        self.fetcher = fetcher
        self.max_age_seconds = max_age_seconds
        self.bundled_path = BUNDLED_DIR / f"{name}.json"
        self.runtime_path = RUNTIME_DIR / f"{name}.json"
        self._lock = threading.Lock()
        self._entries: list[dict] | None = None
        self._error: str | None = None
        self._source: str | None = None
        self._fetching = False
        self.version = 0   # 每次資料更新就 +1，供呼叫端判斷索引是否要重建

    # ------------------------------------------------------------------ #
    def load_local(self) -> list[dict]:
        """只讀記憶體與本機檔案（不會卡住）；需要連外時改在背景抓取。"""
        with self._lock:
            if self._entries is not None:
                return self._entries

            local = self._read_local()
            if local is not None:
                entries, source = local
                self._entries, self._source = entries, source
                self.version += 1
                return self._entries

        self._start_background_fetch()
        return []

    def load(self, force_refresh: bool = False) -> list[dict]:
        """同步載入（必要時會連外）。給更新腳本與明確要求重新整理時使用。"""
        with self._lock:
            if self._entries is not None and not force_refresh:
                return self._entries

            if not force_refresh:
                local = self._read_local()
                if local is not None:
                    entries, source = local
                    self._entries, self._source = entries, source
                    self.version += 1
                    return self._entries

        entries = self._fetch_remote()
        if entries:
            return entries

        with self._lock:
            stale = _read_json(self.runtime_path)
            self._entries = stale or []
            self._source = "stale_cache" if stale else None
            self.version += 1
            return self._entries

    # ------------------------------------------------------------------ #
    def _read_local(self) -> tuple[list[dict], str] | None:
        """讀取隨程式碼發佈的快照或執行時快取（純本機檔案）。"""
        bundled = _read_json(self.bundled_path)
        if bundled:
            return bundled, "bundled"
        if _is_fresh(self.runtime_path, self.max_age_seconds):
            cached = _read_json(self.runtime_path)
            if cached:
                return cached, "runtime_cache"
        return None

    def _fetch_remote(self) -> list[dict]:
        """實際連外抓取；失敗只記錄錯誤類別。"""
        try:
            entries = self.fetcher()
        except Exception as exc:
            logger.warning("%s 清單抓取失敗: %s", self.name, exc)
            with self._lock:
                self._error = _error_category(exc)
            return []

        if not entries:
            with self._lock:
                self._error = "empty_response"
            return []

        _write_json(self.runtime_path, entries)
        with self._lock:
            self._entries, self._source, self._error = entries, "remote", None
            self.version += 1
        return entries

    def _start_background_fetch(self) -> None:
        """在背景抓取，避免任何請求卡在網路上；同時間只會有一個執行緒。"""
        with self._lock:
            if self._fetching or self._entries is not None:
                return
            self._fetching = True

        def worker() -> None:
            try:
                entries = self._fetch_remote()
                if not entries:
                    with self._lock:
                        # 抓不到就退回過期的快取，並記成已載入避免無限重試
                        stale = _read_json(self.runtime_path)
                        self._entries = stale or []
                        self._source = "stale_cache" if stale else None
                        self.version += 1
            finally:
                with self._lock:
                    self._fetching = False

        threading.Thread(target=worker, name=f"directory-{self.name}", daemon=True).start()

    def status(self) -> dict:
        """目前狀態；**不會**觸發任何載入或網路請求（健康檢查安全）。"""
        with self._lock:
            entries = self._entries
            return {
                "name": self.name,
                "loaded": len(entries) if entries is not None else 0,
                "ready": entries is not None,
                "loading": self._fetching,
                "source": self._source,
                "bundled_snapshot": self.bundled_path.is_file(),
                "runtime_cache": self.runtime_path.is_file(),
                "error": self._error,   # 只會是固定的錯誤類別字串
            }

    def reset(self) -> None:
        """測試用：清掉記憶體內的資料。"""
        with self._lock:
            self._entries = None
            self._error = None
            self._source = None
            self._fetching = False
            self.version += 1


# --------------------------------------------------------------------------- #
def _error_category(exc: Exception) -> str:
    """把例外歸類成固定字串，避免把內部細節回傳到 API。"""
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "connection" in name or "proxy" in name or "ssl" in name:
        return "network_unavailable"
    if "http" in name:
        return "source_error"
    return "unavailable"


def _read_json(path: Path) -> list[dict] | None:
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("entries") if isinstance(payload, dict) else payload
        return entries if isinstance(entries, list) and entries else None
    except Exception:
        return None


def _write_json(path: Path, entries: list[dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"updated_at": time.time(), "entries": entries}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # 唯讀檔案系統（Serverless）就跳過


def _is_fresh(path: Path, max_age_seconds: float) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return (time.time() - float(payload.get("updated_at", 0))) < max_age_seconds
    except Exception:
        return False
