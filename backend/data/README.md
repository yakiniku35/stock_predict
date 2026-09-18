# backend/data/

放置隨程式碼一起發佈的靜態資料。

## tw_securities.json（可選）

台股上市／上櫃證券的中文名稱對照表（含 ETF），用來支援「輸入中文名稱查股票」。

這個檔案**不在版控中**（第一次使用時會自動抓取並快取到 `data/runtime/`），
如果你想讓部署環境（例如 Vercel）不必連證交所就能使用中文查詢，
可以在本機執行下面指令產生快照後再一起 commit：

```bash
python scripts/update_tw_securities.py
```

資料來源：臺灣證券交易所 ISIN 查詢頁（`isin.twse.com.tw`，strMode=2 上市、strMode=4 上櫃）。

載入優先順序：

1. `backend/data/tw_securities.json`（本目錄的快照）
2. `data/runtime/tw_securities.json`（執行時抓取的快取，7 天內有效）
3. 即時向證交所抓取
4. 以上都失敗 → 退回 `backend/symbol_catalog.py` 的內建字典（約 125 檔熱門標的）
