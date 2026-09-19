# backend/data/

放置隨程式碼一起發佈的靜態資料（名稱對照表快照）。

| 檔案 | 內容 | 來源 |
| --- | --- | --- |
| `tw_securities.json` | 台股上市／上櫃股票與 ETF（約 3,000 檔） | 證交所 ISIN 查詢頁 `isin.twse.com.tw` |
| `us_securities.json` | 美股與美股 ETF（約 11,000 檔） | NASDAQ Trader `nasdaqlisted.txt` / `otherlisted.txt` |

這兩個檔案**預設不在版控中**（第一次使用時會自動抓取並快取到 `data/runtime/`）。
如果希望部署環境（例如 Vercel）不必連外就能用名稱查詢，可以在本機產生快照後一起 commit：

```bash
python scripts/update_symbol_directory.py             # 台股 + 美股
python scripts/update_symbol_directory.py --market tw # 只更新台股
```

載入優先順序（見 `backend/directory_cache.py`）：

1. `backend/data/<name>.json`（本目錄的快照）
2. `data/runtime/<name>.json`（執行時抓取的快取，7 天內有效）
3. 即時向資料來源抓取
4. 以上都失敗 → 退回 `backend/symbol_catalog.py` 的內建字典（約 160 檔熱門標的）

可用環境變數關閉線上抓取（例如測試或離線環境）：

```bash
STOCKSENSE_DISABLE_DIRECTORY=1      # 兩個市場都關閉
STOCKSENSE_DISABLE_TW_DIRECTORY=1   # 只關台股
STOCKSENSE_DISABLE_US_DIRECTORY=1   # 只關美股
```
