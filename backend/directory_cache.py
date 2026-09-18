"""證券名稱對照表的共用快取層。

台股（`tw_directory.py`）與美股（`us_directory.py`）都用這裡的邏輯：

1. 先找隨程式碼發佈的快照 `backend/data/<name>.json`
2. 再找執行時快取 `data/runtime/<name>.json`（預設 7 天內有效）
3. 都沒有才上網抓，抓到後寫入執行時快取
4. 全部失敗就回傳空清單，呼叫端自動退回內建字典
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

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

    # ------------------------------------------------------------------ #
    def load(self, force_refresh: bool = False) -> list[dict]:
        with self._lock:
            if self._entries is not None and not force_refresh:
                return self._entries

            if not force_refresh:
                bundled = _read_json(self.bundled_path)
                if bundled:
                    self._entries, self._source = bundled, "bundled"
                    return self._entries
                if _is_fresh(self.runtime_path, self.max_age_seconds):
                    cached = _read_json(self.runtime_path)
                    if cached:
                        self._entries, self._source = cached, "runtime_cache"
                        return self._entries

            try:
                entries = self.fetcher()
                if entries:
                    _write_json(self.runtime_path, entries)
                    self._entries, self._source, self._error = entries, "remote", None
                    return self._entries
                self._error = "資料來源回傳空清單"
            except Exception as exc:
                self._error = str(exc)

            stale = _read_json(self.runtime_path)
            self._entries = stale or []
            self._source = "stale_cache" if stale else None
            return self._entries

    def status(self) -> dict:
        entries = self.load()
        return {
            "name": self.name,
            "loaded": len(entries),
            "source": self._source,
            "bundled_snapshot": self.bundled_path.is_file(),
            "runtime_cache": self.runtime_path.is_file(),
            "error": self._error,
        }

    def reset(self) -> None:
        """測試用：清掉記憶體內的資料。"""
        with self._lock:
            self._entries = None
            self._error = None
            self._source = None


# --------------------------------------------------------------------------- #
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
