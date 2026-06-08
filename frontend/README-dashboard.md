# Stock Predict 網站版

這個前端會使用原始專案的實際 pipeline：

1. `crawler/news_scraper.py`
2. `models/run_sentiment_batch.py`
3. `models/build_daily_features.py`
4. `frontend/app.py` 讀取產出的 JSONL / CSV 顯示網站

## 本機啟動

```bash
pip install -r requirements.txt
python frontend/app.py
```

打開：

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
- 顯示三段式情緒圖表
