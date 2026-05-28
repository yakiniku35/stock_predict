# 股票預測

[English README](README.md)

台股與美股走勢預測專案。目標是結合歷史行情、財務指標、新聞與社群情緒訊號，協助進行價格趨勢分析與視覺化呈現。

> 專案狀態：已完成第一階段（多來源新聞爬蟲）與第二階段 baseline（情緒標註與時間桶特徵聚合）。目前重點是擴充模型品質與預測模組。

## 功能

- 使用 [yfinance](https://github.com/ranaroussi/yfinance) 取得歷史股價與財務指標。
- 透過爬蟲蒐集新聞、社群討論等輔助市場資訊。
- 目前使用詞典規則 baseline 分析情緒訊號（非 RNN），後續可替換為 RNN/LSTM 或 transformer。
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
source .venv/bin/activate
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

## 第二階段：情緒 Baseline（已可執行）

先將第一階段輸出的新聞批次標註情緒（可調整平行度）：

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/run_sentiment_batch.py \
  --input data/raw/news_latest.jsonl \
  --output data/normalized/news_with_sentiment.jsonl \
  --summary-output data/normalized/news_with_sentiment_summary.json \
  --workers 4
```

再將已標註情緒的新聞聚合為時間桶特徵（可細到 15 分鐘）：

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/build_daily_features.py \
  --input data/normalized/news_with_sentiment.jsonl \
  --output data/features/sentiment_features_hour.csv \
  --timeframe hour \
  --timezone Asia/Taipei
```

可用時間粒度：

- `--timeframe day`
- `--timeframe hour`
- `--timeframe 30min`
- `--timeframe 15min`

速度與模型狀態說明：

- `models/run_sentiment_batch.py` 會在 summary 內輸出 `records_per_second`。
- `--workers 0` 或 `1` 使用單批次模式，`--workers >= 2` 使用 thread pool。
- `--model-type lexicon` 時 `runtime.is_rnn=false`；`--model-type rnn` 時 `runtime.is_rnn=true`。

第二階段輸出：

- data/normalized/news_with_sentiment.jsonl
- data/normalized/news_with_sentiment_summary.json
- data/features/sentiment_features_hour.csv（或依 `--timeframe` 自訂檔名）

備註：目前為 baseline（詞典規則）版本，目標是先建立可重現、可驗證的端到端管線，後續可替換為 RNN/LSTM 或 transformer 模型。

## 第三階段：真 RNN/LSTM（訓練與推論）

### 快準平衡部署策略（建議）

- 線上即時：先用 lexicon 快速打分（延遲低、穩定高）。
- 離線排程：定期重訓 RNN（例如每日或每週），追求準確度。
- 權重切換：重訓完成後只更新 active model pointer，線上流程無需改程式即可切到最新權重。

### 1) 訓練 BiLSTM 情緒模型

若輸入資料已含 `sentiment_label`，可直接監督訓練；若沒有，預設會先用 lexicon 自動產生弱標籤再訓練。

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/train_rnn_sentiment.py \
  --input data/normalized/news_with_sentiment.jsonl \
  --output-dir models/artifacts/rnn_sentiment \
  --summary-output models/artifacts/rnn_sentiment/train_summary.json \
  --label-source auto \
  --epochs 8 \
  --batch-size 64 \
  --max-len 256 \
  --vocab-size 20000
```

若要「訓練完自動升級為最新權重」，可直接使用整合腳本：

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/retrain_rnn_and_promote.py \
  --input data/normalized/news_with_sentiment.jsonl \
  --registry-dir models/rnn_registry \
  --eval-input data/normalized/news_with_sentiment.jsonl \
  --eval-label-source field \
  --rollback-metric macro_f1 \
  --rollback-min-improvement 0.002 \
  --label-source field \
  --epochs 8 \
  --batch-size 64 \
  --summary-output models/rnn_registry/last_retrain_summary.json
```

回滾機制說明：

- 若新模型在指定評估指標（例如 `macro_f1`）未達到最小增益，會自動保留舊 active 權重。
- 可用 `--disable-rollback` 暫時關閉回滾；可用 `--force-promote` 強制升級。
- 回滾決策與分數比較會寫在 `last_retrain_summary.json` 的 `rollback` 與 `evaluation` 欄位。
- 可用 `--event-log` 追加事件記錄，並搭配 `--notify-hook-url` + `--notify-on rollback` 觸發自動告警 hook。

### 2) 使用 RNN 模型做批次推論

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/predict_rnn_sentiment.py \
  --input data/raw/news_latest.jsonl \
  --output data/normalized/news_with_sentiment_rnn.jsonl \
  --summary-output data/normalized/news_with_sentiment_rnn_summary.json \
  --model-dir models/rnn_registry \
  --batch-size 128
```

### 3) 透過同一條批次管線切換到 RNN

`models/run_sentiment_batch.py` 現在支援 `--model-type rnn`，此時 summary 的 `runtime.is_rnn` 會是 `true`：

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/run_sentiment_batch.py \
  --input data/raw/news_latest.jsonl \
  --output data/normalized/news_with_sentiment.jsonl \
  --summary-output data/normalized/news_with_sentiment_summary.json \
  --model-type rnn \
  --rnn-model-dir models/rnn_registry \
  --rnn-batch-size 128
```

### 4) 線上 lexicon 即時打分（低延遲）

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/run_sentiment_batch.py \
  --input data/raw/news_latest.jsonl \
  --output data/normalized/news_with_sentiment_live.jsonl \
  --summary-output data/normalized/news_with_sentiment_live_summary.json \
  --model-type lexicon \
  --workers 4
```

### 5) 手動切換 active RNN 權重（可選）

當你有多個訓練版本時，可手動 promote 指定目錄：

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/promote_rnn_model.py \
  --registry-dir models/rnn_registry \
  --model-dir models/rnn_registry/runs/20260528_223500
```

### 6) 線上 A/B 流量切分（lexicon vs RNN）

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/run_sentiment_batch.py \
  --input data/raw/news_latest.jsonl \
  --output data/normalized/news_with_sentiment_ab.jsonl \
  --summary-output data/monitoring/ab_runs/summary_latest.json \
  --ab-enabled \
  --ab-rnn-ratio 0.35 \
  --ab-key-field id \
  --ab-salt stock_predict_ab_v1 \
  --rnn-model-dir models/rnn_registry \
  --rnn-batch-size 128 \
  --workers 4 \
  --ab-report-output data/monitoring/ab_runs/report_latest.json
```

A/B 監控重點：

- `ab-report-output` 會輸出雙臂吞吐、錯誤率、標籤分布（rnn/lexicon 各自統計）。
- 每筆輸出新增 `sentiment_model`，可追蹤該筆是由哪個模型打分。
- 流量切分採固定 key + salt 的哈希分流，重跑時同一 key 會穩定落在同一臂。

### 7) 監控報表彙總

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/generate_ab_monitoring_report.py \
  --input-glob "data/monitoring/ab_runs/report_*.json" \
  --eval-summary models/rnn_registry/last_retrain_summary.json \
  --output data/monitoring/ab_report_daily.json \
  --markdown-output data/monitoring/ab_report_daily.md \
  --ratio-config models/rnn_registry/traffic_policy.json \
  --write-ratio-config
```

輸出重點：

- `ab_report_daily.json`：彙總統計 + 日級資料 + 7/30 日趨勢資料。
- `ab_report_daily.md`：內含 7/30 日 Mermaid 趨勢圖（RNN vs Lexicon 吞吐）。
- `traffic_policy.json`：自適應建議的 `rnn_ratio`，供 A/B 線上分流自動讀取。

自適應流量分配說明：

- 會結合最近評估準確率（RNN 與 Lexicon）與近 7 日吞吐量，計算下一版 `rnn_ratio`。
- `--weight-accuracy` 與 `--weight-throughput` 可調整權重（預設 0.75 / 0.25）。
- `--max-ratio-step` 限制單次調整幅度，避免流量劇烈震盪。

### 8) 定時排程樣板（cron）

完整樣板請看：

- `docs/cron_templates.md`

快準建議（實務）

- 先用 lexicon 版本快速標註新資料，再定期重訓 RNN（例如每天或每週）。
- 推論時優先調整 `--rnn-batch-size`（例如 128、256）來換取更高吞吐。
- 訓練時保留 EarlyStopping，搭配 `--epochs 6~12`，避免過擬合與浪費時間。
- 若你有人工標註資料，建議 `--label-source field`，準確率通常會比弱標籤更好。
