# 股票預測

[English README](README.md)

台股與美股走勢預測專案。目標是結合歷史行情、財務指標、新聞與社群情緒訊號，協助進行價格趨勢分析與視覺化呈現。

> 專案狀態：早期骨架。目前 repository 主要包含文件與依賴檔案占位，尚未加入實際應用程式碼。

## 功能

- 使用 [yfinance](https://github.com/ranaroussi/yfinance) 取得歷史股價與財務指標。
- 透過爬蟲蒐集新聞、社群討論等輔助市場資訊。
- 使用 RNN 類模型分析情緒訊號。
- 整合價格、指標與情緒特徵，預測股票價格走勢方向。
- 使用 [Plotly](https://github.com/plotly/plotly.py) 呈現互動式圖表與分析結果。

## 快速開始

複製專案：

```bash
git clone https://github.com/yakiniku35/stock_predict.git
cd stock_predict
```

建立並啟用虛擬環境：

```bash
python -m venv .venv
.venv\Scripts\activate
```

安裝依賴：

```bash
pip install -r requirements.txt
```

目前尚未提供後端與前端的啟動入口。待 `backend/`、`frontend/` 等模組加入後，請同步更新本段落的啟動指令。

### 新聞爬蟲（第一階段已可執行）

執行爬蟲並輸出結構化新聞 JSONL：

```bash
python -m crawler.news_scraper \
  --config crawler/news_sources.json \
  --output data/raw/news_latest.jsonl \
  --ticker 2330 \
  --max-articles 200
```

高新聞量模式（加速收斂、提高覆蓋）：

```bash
python -m crawler.news_scraper \
  --config crawler/news_sources.json \
  --output data/raw/news_latest.jsonl \
  --ticker 2330 \
  --query "台積電 台股" \
  --max-articles 600 \
  --per-source-max-items 80 \
  --summary-output data/raw/news_latest_summary.json
```

常用參數：

- `--append`：追加寫入輸出檔案（預設覆寫）。
- `--max-articles`：限制單次輸出筆數。
- `--ticker`：寫入每筆新聞的預設股票代碼。
- `--query`：動態查詢字串，套用到支援 `{query}` / `{query_encoded}` 的來源。
- `--keyword`：以逗號分隔的額外關鍵字（搭配嚴格過濾時使用）。
- `--enforce-keyword-filter`：強制所有來源套用 `--keyword`（精準度高、新聞量較低）。
- `--per-source-max-items`：限制每個來源最多抓取幾則，控制速度與來源平衡。
- `--min-content-length`：內容最短長度門檻，避免雜訊短文。
- `--summary-output`：輸出本次抓取統計報告 JSON。

輸出欄位（JSONL 每行一筆）：

- `id`、`source`、`headline`、`content`、`url`
- `published_at`（UTC ISO 格式）
- `fetched_at`（UTC ISO 格式）
- `language`、`ticker`
- `sentiment_score`、`sentiment_label`（第二階段填值）

目前預設來源（可在 `crawler/news_sources.json` 調整）：

- Yahoo 股市（HTML，抓標題與內文）
- 鉅亨網（HTML，抓標題與內文）
- Yahoo 股市 RSS（抓連結後進文章補全內文）
- Google News RSS（台股總覽、Yahoo、鉅亨、工商、經濟日報、MoneyDJ、CNA、SETN）
- 動態來源（依 `--ticker`、`--query` 產生查詢）

若要新增來源，可使用以下欄位：

- `type`: `rss` 或 `html`
- `list_url`: 列表頁或 RSS 網址
- `article_link_selector`: HTML 模式下抓文章連結
- `title_selector` / `time_selector` / `content_selector`: 文章頁擷取規則
- `article_link_include` / `article_link_exclude`: 連結白名單與黑名單（regex）
- `rss_use_article_content`: RSS 是否進一步進文章頁抓完整內文

## 專案架構

目前結構：

```text
stock_predict/
├── README.md
├── README.zh-TW.md
├── LICENSE
├── requirements.txt
└── .gitignore
```

預計結構：

```text
stock_predict/
├── backend/          # API、資料處理、模型推論
├── frontend/         # Plotly/Dash 或網頁介面
├── data/             # 本機資料集與快取行情資料
├── models/           # 訓練腳本與模型檔案
├── crawlers/         # 新聞與社群資料蒐集器
├── tests/            # 單元測試與整合測試
└── requirements.txt
```

## 資料來源

- 歷史 K 線與財務指標：[yfinance](https://github.com/ranaroussi/yfinance)
- 輔助市場資訊：透過爬蟲蒐集的新聞、社群討論與其他公開來源

蒐集或重新散布資料前，請先確認各資料來源的服務條款與使用限制。

## 分工與貢獻者

感謝所有貢獻者。

[![Contributors](https://contrib.rocks/image?repo=yakiniku35/stock_predict)](https://github.com/yakiniku35/stock_predict/graphs/contributors)

## 開發筆記

- 依賴套件或啟動入口變更時，請同步更新 README 的安裝與執行步驟。
- API key、token 等敏感資訊請放在本機環境變數或被忽略的 `.env` 檔案中。
- 除非有明確版本控管需求，請避免提交原始資料集、模型 checkpoint 或快取檔。
- 核心資料處理、模型與 API 模組加入後，建議同步補上測試。

## 免責聲明

本專案僅供研究與學習用途，不構成任何投資建議、財務建議或保證性預測結果。
