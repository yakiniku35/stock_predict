# 🚀 StockSense 完整啟動指南

## ✅ 系統已經可以真正抓取新聞並分析！

我已經測試確認系統可以正常運作：
- ✅ 成功抓取 10 筆台積電即時新聞
- ✅ 情緒分析正常（正面 1、中立 6、負面 3）
- ✅ 資料已儲存在 data/ 目錄

## 📋 完整啟動步驟

### 1️⃣ 啟動新聞服務（必須）

```bash
# 終端機 1
cd /Users/peterchiu/stock_predict/frontend
python3 dashboard.py
```

看到這個訊息表示成功：
```
Open http://127.0.0.1:8501
```

### 2️⃣ 啟動前端服務

```bash
# 終端機 2
cd /Users/peterchiu/stock_predict/public
python3 -m http.server 8000
```

### 3️⃣ 開啟瀏覽器

選擇其中一個：

**選項 A - 專業儀表板（推薦）**
```
http://localhost:8000/dashboard.html
```

**選項 B - 測試頁面**
```
http://localhost:8000/demo.html
```

**選項 C - 本地原生服務**
```
http://127.0.0.1:8501
```

## 🧪 測試步驟

### 使用 Demo 頁面測試

1. 訪問 `http://localhost:8000/demo.html`
2. 點擊「抓取台積電新聞」
3. 等待 5-10 秒
4. 查看結果：
   - 統計資料（新聞數、情緒分數）
   - 新聞列表（含情緒標籤）
   - 原始 JSON 資料

### 使用專業儀表板

1. 訪問 `http://localhost:8000/dashboard.html`
2. 輸入股票代碼（例如：2330）
3. 選擇時間範圍（例如：近一個月）
4. 設定新聞數量（例如：50）
5. 點擊「分析」按鈕
6. 查看結果：
   - 統計卡片（價格、新聞數、情緒）
   - Plotly K線圖
   - 新聞動態列表
   - 情緒圓餅圖

## 📊 實際測試結果

剛才的測試成功抓取：
```json
{
  "summary": {
    "records": 10,
    "score_mean": -0.2,
    "positive_ratio": 0.1,
    "neutral_ratio": 0.6,
    "negative_ratio": 0.3
  },
  "news": [
    {
      "headline": "台股狂瀉2000點！台積電跳水2330元...",
      "sentiment_label": "negative",
      "sentiment_score": -1.0
    },
    ...
  ]
}
```

## 🎯 支援的股票代碼

### 台股
- 2330 (台積電)
- 2317 (鴻海)
- 2454 (聯發科)
- 2412 (中華電)

### 美股
- AAPL (蘋果)
- TSLA (特斯拉)
- MSFT (微軟)
- GOOGL (Google)

## 📁 資料儲存位置

所有抓取的資料都會儲存在：

```
data/
├── raw/                          # 原始新聞
│   ├── news_latest.jsonl        # 最新抓取的新聞
│   └── news_latest_summary.json # 摘要資訊
├── normalized/                   # 情緒分析後
│   ├── news_with_sentiment.jsonl
│   └── news_with_sentiment_summary.json
└── features/                     # 時間序列特徵
    └── sentiment_features_hour.csv
```

## 🔧 API 端點說明

### 1. 新聞搜尋與情緒分析
```
GET http://127.0.0.1:8501/api/search

參數：
  - ticker: 股票代碼（必填）
  - query: 搜尋關鍵字（可選）
  - max_articles: 最大新聞數（預設 100）

範例：
http://127.0.0.1:8501/api/search?ticker=2330&query=台積電&max_articles=50
```

### 2. 股價查詢
```
GET https://stock-predict-azure.vercel.app/api/stock_insight

參數：
  - ticker: 股票代碼（必填）
  - period: 時間範圍（預設 1mo）
  - interval: 時間間隔（預設 1d）

範例：
https://stock-predict-azure.vercel.app/api/stock_insight?ticker=2330&period=1mo&interval=1d
```

## 🐛 疑難排解

### Q: 新聞無法載入？

A: 確認新聞服務已啟動：
```bash
# 檢查服務
curl http://127.0.0.1:8501/api/search?ticker=2330&query=台積電&max_articles=10

# 重啟服務
cd frontend
python3 dashboard.py
```

### Q: 顯示 CORS 錯誤？

A: 確保兩個服務都在運行：
1. 新聞服務：http://127.0.0.1:8501
2. 前端服務：http://localhost:8000

### Q: 情緒分析不準確？

A: 目前使用 Lexicon 詞彙分析，是輕量化版本。特點：
- 速度快
- 無需深度學習模型
- 基於中文情緒詞典

## 💡 使用技巧

### 1. 批次測試多檔股票

```bash
# 使用 curl 測試
curl "http://127.0.0.1:8501/api/search?ticker=2330&query=台積電&max_articles=30"
curl "http://127.0.0.1:8501/api/search?ticker=2317&query=鴻海&max_articles=30"
```

### 2. 定時抓取

可以使用 cron 或排程任務定時抓取：
```bash
# 每小時抓取一次
0 * * * * cd /Users/peterchiu/stock_predict && curl "http://127.0.0.1:8501/api/search?ticker=2330&max_articles=100"
```

### 3. 查看歷史資料

```bash
# 查看原始新聞
cat data/raw/news_latest.jsonl | jq

# 查看情緒分析結果
cat data/normalized/news_with_sentiment.jsonl | jq

# 查看時間序列特徵
cat data/features/sentiment_features_hour.csv
```

## 🎉 成功！

現在你可以：
1. ✅ 即時抓取新聞
2. ✅ 自動情緒分析
3. ✅ 視覺化展示
4. ✅ 整合股價資料
5. ✅ 專業儀表板

---

📖 詳細指南：DASHBOARD-GUIDE.md
🔧 部署說明：DEPLOYMENT-SUCCESS.md
🐛 問題回報：開 issue

Made with ❤️ by StockSense
