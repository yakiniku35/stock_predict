# StockSense 前端儀表板

輕量化股票情緒分析儀表板，使用純 Python HTTP Server + 原生 JavaScript。

## 功能特色

- 📊 即時新聞爬蟲與情緒分析
- 📈 互動式情緒趨勢圖表
- 🎨 美化的深色主題介面
- ⚡ 輕量化設計，無需複雜依賴

## 啟動方式

```bash
cd /Users/peterchiu/stock_predict/frontend
python dashboard.py
```

訪問 http://127.0.0.1:8501

## 使用說明

1. 輸入股票代碼（例如：2330、AAPL）
2. 輸入關鍵字（例如：台積電 AI）
3. 設定文章數量（10-100篇）
4. 點擊搜尋

系統會自動：
- 爬取相關新聞
- 執行情緒分析（使用詞彙分析）
- 產生時間序列特徵
- 繪製情緒趨勢圖表

## 技術架構

- **後端**: Python HTTP Server (內建)
- **前端**: 原生 HTML/CSS/JavaScript
- **情緒分析**: 詞彙基準模型
- **資料處理**: Pandas + NumPy
