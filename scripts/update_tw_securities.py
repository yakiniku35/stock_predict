#!/usr/bin/env python3
"""更新台股中文名稱對照表快照。

在有網路的環境執行一次，就會把證交所的上市 / 上櫃清單（含 ETF）存成
`backend/data/tw_securities.json`，之後部署到 Vercel 也能離線使用中文查詢。

用法：
    python scripts/update_tw_securities.py
    python scripts/update_tw_securities.py --output backend/data/tw_securities.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import tw_directory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="更新台股中文名稱對照表")
    parser.add_argument(
        "--output",
        default=str(tw_directory.BUNDLED_SNAPSHOT),
        help="輸出路徑（預設 backend/data/tw_securities.json）",
    )
    args = parser.parse_args()

    print("正在向證交所取得上市 / 上櫃清單...")
    try:
        entries = tw_directory.fetch_from_twse()
    except Exception as exc:
        print(f"抓取失敗: {exc}", file=sys.stderr)
        return 1

    if not entries:
        print("回傳空清單，請稍後再試", file=sys.stderr)
        return 1

    stocks = sum(1 for entry in entries if entry["kind"] == "stock")
    etfs = sum(1 for entry in entries if entry["kind"] == "etf")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"updated_at": time.time(), "entries": entries}, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )

    print(f"完成：共 {len(entries)} 檔（股票 {stocks}、ETF {etfs}）→ {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
