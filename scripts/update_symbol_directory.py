#!/usr/bin/env python3
"""更新股票 / ETF 名稱對照表快照（台股 + 美股）。

在有網路的環境執行一次，就會把清單存成 `backend/data/*.json`，
之後部署到 Vercel 也能離線使用名稱查詢（不必連證交所或 NASDAQ）。

用法：
    python scripts/update_symbol_directory.py             # 台股 + 美股
    python scripts/update_symbol_directory.py --market tw
    python scripts/update_symbol_directory.py --market us
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
import us_directory  # noqa: E402

SOURCES = {
    "tw": ("台股（上市 + 上櫃，含 ETF）", tw_directory.fetch_from_twse, "tw_securities"),
    "us": ("美股（NASDAQ + 其他交易所，含 ETF）", us_directory.fetch_from_nasdaq, "us_securities"),
}


def update(market: str, output_dir: Path) -> bool:
    label, fetcher, name = SOURCES[market]
    print(f"正在取得{label}清單...")
    try:
        entries = fetcher()
    except Exception as exc:
        print(f"  ✗ 抓取失敗: {exc}", file=sys.stderr)
        return False

    if not entries:
        print("  ✗ 回傳空清單，請稍後再試", file=sys.stderr)
        return False

    stocks = sum(1 for entry in entries if entry["kind"] == "stock")
    etfs = sum(1 for entry in entries if entry["kind"] == "etf")

    output = output_dir / f"{name}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"updated_at": time.time(), "entries": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  ✓ 共 {len(entries)} 檔（股票 {stocks}、ETF {etfs}）→ {output}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="更新股票 / ETF 名稱對照表")
    parser.add_argument("--market", choices=["tw", "us", "all"], default="all")
    parser.add_argument("--output-dir", default=str(ROOT / "backend" / "data"))
    args = parser.parse_args()

    markets = ["tw", "us"] if args.market == "all" else [args.market]
    results = [update(market, Path(args.output_dir)) for market in markets]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
