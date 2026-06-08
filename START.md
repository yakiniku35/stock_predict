# 🚀 StockSense 快速啟動指南

## 📦 安裝依賴

```bash
# 1. 確保在專案根目錄
cd /Users/peterchiu/stock_predict

# 2. 啟動虛擬環境
source .venv/bin/activate

# 3. 安裝輕量化依賴
pip install -r requirements.txt
```

## 🎯 啟動方式

### 方式一：前端儀表板（推薦）

```bash
cd frontend
python dashboard.py
```

然後訪問 http://127.0.0.1:8501

**功能**：
- 🔍 搜尋股票新聞
- 📊 情緒分析與圖表
- 📈 時間序列特徵

### 方式二：後端 API

```bash
cd backend
python app.py
```

API 端點：http://127.0.0.1:5000

**測試 API**：
```bash
curl "http://127.0.0.1:5000/api/stock_insight?ticker=2330&period=1mo&interval=1d"
```

## 📊 使用範例

### 前端儀表板操作

1. **輸入參數**
   - 股票代碼：`2330` (台積電) 或 `AAPL` (蘋果)
   - 關鍵字：`台積電 AI` 或 `Apple iPhone`
   - 文章數量：`50` (建議 10-100)

2. **點擊搜尋**
   - 系統自動爬取新聞
   - 執行情緒分析
   - 生成圖表

3. **查看結果**
   - 左側：情緒趨勢圖
   - 右側：新聞列表
   - 上方：統計數據

## 🛠️ 專案結構

```
stock_predict/
├── backend/           # Flask API
│   ├── app.py        # 主程式
│   └── fetcher.py    # 資料獲取
├── frontend/          # 前端儀表板
│   ├── dashboard.py  # 主程式
│   └── static/       # CSS 樣式
├── crawler/           # 新聞爬蟲
│   └── news_scraper.py
├── models/            # 情緒分析
│   ├── sentiment_baseline.py
│   └── build_daily_features.py
└── data/              # 資料儲存
    ├── raw/          # 原始新聞
    ├── normalized/   # 情緒標註
    └── features/     # 時間特徵
```

## ✨ 優化成果

- ✅ 移除 TensorFlow (~500MB)
- ✅ 移除 RNN 模型 (~64MB)
- ✅ 簡化依賴套件
- ✅ 美化使用者介面
- ✅ 保留所有核心功能

## 💡 提示

- 建議使用 **Chrome** 或 **Firefox** 瀏覽器
- 首次搜尋可能需要 10-30 秒
- 資料會儲存在 `data/` 目錄
- 詳細報告請查看 `docs/CLEANUP_SUMMARY.md`

## 🐛 常見問題

**Q: 搜尋沒有結果？**
A: 檢查網路連線，或嘗試更換關鍵字

**Q: 圖表沒有顯示？**
A: 確認已執行情緒分析，檢查 `data/features/` 是否有檔案

**Q: 如何清理舊資料？**
A: 刪除 `data/` 目錄下的檔案即可

---

📖 詳細文件：`README.md`
🔧 優化報告：`docs/CLEANUP_SUMMARY.md`
