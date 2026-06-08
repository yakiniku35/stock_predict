# 專案優化計劃

## 可刪除的檔案與目錄

### 1. 重複的模型訓練相關檔案 (如果只需要基本功能)
- `models/train_rnn_sentiment.py` - RNN訓練腳本
- `models/retrain_rnn_and_promote.py` - 重新訓練與升級
- `models/predict_rnn_sentiment.py` - RNN預測
- `models/promote_rnn_model.py` - 模型升級
- `models/generate_ab_monitoring_report.py` - A/B測試報告
- `models/rnn_artifacts/` - 訓練產物 (~15MB)
- `models/rnn_registry/` - 模型註冊 (~49MB)

### 2. 重複的 frontend 目錄結構
- `/frontend/frontend/` - 內層重複的 frontend 目錄應該合併

### 3. 不必要的快取檔案
- `**/__pycache__/` - Python 快取
- `.DS_Store` - macOS 系統檔案

### 4. 舊的 requirements 檔案
- `frontend/requirements-dashboard.txt` - 已有主 requirements.txt
- `frontend/requirements-full-ml.txt` - 已有主 requirements.txt

## 輕量化建議

### 前端優化
1. 將 840 行的單一 app.py 拆分成模組
2. 移除內嵌 HTML，改用獨立 HTML 檔案
3. CSS/JS 最小化
4. 使用 CDN 載入外部庫

### 後端優化
1. 只保留核心功能 (詞彙情緒分析，移除 RNN)
2. 簡化 API 回應結構
3. 移除不必要的日誌

### 依賴輕量化
保留核心依賴：
- yfinance (股價資料)
- pandas, numpy (資料處理)
- beautifulsoup4, requests (爬蟲)
- Flask (後端 API)

可移除：
- tensorflow (~500MB) - 如果不需要深度學習
- scikit-learn - 如果不需要機器學習
- plotly - 改用輕量級圖表庫

## 預估節省空間
- 模型檔案: ~64MB
- TensorFlow: ~500MB
- Python快取: ~1-5MB
- 總計: ~570MB+

是否繼續執行優化？
