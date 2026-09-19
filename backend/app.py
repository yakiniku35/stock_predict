"""本機開發用的啟動入口。

實際的路由與商業邏輯都寫在 `api/index.py`（Vercel 也是用同一份），
這裡只負責把它載入並啟動 Flask 伺服器，避免兩邊邏輯不一致。

用法：
    python backend/app.py                     # http://127.0.0.1:5000
    PORT=8080 python backend/app.py           # 換連接埠
    HOST=0.0.0.0 python backend/app.py        # 讓區域網路的其他裝置也能連
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parent.parent
for path in (str(ROOT_PATH), str(ROOT_PATH / "api"), str(ROOT_PATH / "backend")):
    if path not in sys.path:
        sys.path.insert(0, path)

from index import app  # noqa: E402  (api/index.py)

__all__ = ["app"]


if __name__ == "__main__":
    # 預設只綁本機；要讓區域網路連進來請設 HOST=0.0.0.0
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    print(f"StockSense API 啟動中 → http://127.0.0.1:{port}")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
