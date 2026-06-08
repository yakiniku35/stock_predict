# Stock Predict Final VS Code 版本

這是整理過的最終資料夾，只保留網站需要的檔案。

## 用 VS Code 執行

1. 用 VS Code 開啟這整個資料夾：`stock_predict_final_vscode`
2. 按 `Ctrl + Shift + P`
3. 選 `Tasks: Run Task`
4. 選 `Install Python dependencies`
5. 安裝完成後按 `F5`
6. 打開瀏覽器：

```text
http://127.0.0.1:8501
```

## 功能

- 搜尋股票代碼
- 搜尋關鍵字
- 設定文章數量
- 顯示平均情緒
- 顯示正面比例
- 顯示負面比例
- 顯示文章連結
- 顯示三段式圖表：平均情緒、新聞數量、正面/中立/負面比例

## 內容說明

- `frontend/app.py`：網站與 API
- `crawler/news_scraper.py`：原始新聞爬蟲
- `models/run_sentiment_batch.py`：原始情緒分析流程
- `models/build_daily_features.py`：原始時間序列特徵產生流程
- `requirements-dashboard.txt`：網站需要的套件
- `requirements-full-ml.txt`：如果之後要跑 RNN/LSTM，才需要完整 ML 套件

## 常見問題

如果輸入改了但結果沒變，先在 VS Code Terminal 按 `Ctrl + C` 停止舊 server，再按 `F5` 重開。

如果 Python 套件缺少，重新執行 `Tasks: Run Task` -> `Install Python dependencies`。
