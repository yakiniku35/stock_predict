# 股票預測

[English README](README.md)

台股與美股走勢預測專案。目標是結合歷史行情、財務指標、新聞與社群情緒訊號，協助進行價格趨勢分析與視覺化呈現。

> 專案狀態：已完成第一階段（多來源新聞爬蟲）與第二階段 baseline（情緒標註與時間桶特徵聚合）。目前重點是擴充模型品質與預測模組。

## 功能

- **股票與 ETF 都支援**：涵蓋台股上市／上櫃與美股，可用中文或英文搜尋標的。
- 使用 [yfinance](https://github.com/ranaroussi/yfinance) 取得歷史股價與財務指標。
- 透過爬蟲蒐集新聞、社群討論等輔助市場資訊。
- 提供詞典規則 baseline，並已支援 RNN/LSTM 情緒模型的訓練與推論流程；後續可再擴充 transformer。
- 自動判讀每一項技術指標，並產生白話的繁體中文說明，直接告訴你現在是什麼狀況。
- 以六個時間序列模型組成的「回測加權整合」預測走勢，並附上信賴區間。
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

## 網頁應用（v2）

一個指令就能啟動：

```bash
./start.sh          # 開啟 http://127.0.0.1:5000
python tests/test_stocksense.py   # 120 個離線測試，不需要網路
```

### 主要功能

- **股票與 ETF 都查得到**：台股上市／上櫃代號會自動補後綴（`0050`、`00878`、`006208` → `.TW`，`6488` → `.TWO`），
  美股與美股 ETF（`SPY`、`QQQ`、`NVDA`）直接輸入即可，也支援中文名稱（`台積電`、`高股息`）。
- **深色 / 淺色 / 自動主題**：右上角切換，選擇會記在瀏覽器裡，圖表配色也會跟著變。
- **指標自動判讀**：系統會計算 11 項訊號（均線結構、RSI、MACD、KD、布林通道、乖離率、量能／OBV、
  波段位階、波動風險、新聞情緒、模型預測），換算成 -100 ~ +100 的多空分數，並自動產生一段繁體中文說明，
  直接告訴你「現在是什麼狀況」。
- **有回測依據的預測**：六個真正的時間序列模型，權重由滾動回測（walk-forward）的誤差決定，而不是寫死的常數。

### 中文名稱查詢（為什麼以前打中文查不到）

舊版只認得代號，中文名稱完全沒有對照表，所以打「台積電」會直接失敗。現在分三層處理：

1. `backend/symbol_catalog.py`：內建約 125 檔熱門標的（含中英文名與別稱，例如「護國神山」「月月配」）。
2. `backend/tw_directory.py`：向證交所 ISIN 頁面取得**完整**上市／上櫃清單（約 3,000 檔，含 ETF）。
   所以「長榮航」「京元電子」「藥華藥」這種沒收錄在內建字典的名稱也查得到。
3. `backend/us_directory.py`：向 NASDAQ Trader 取得**完整美股清單**（NASDAQ + NYSE 等，約 11,000 檔，
   含 ETF 旗標）。所以「ASML Holding」「Palantir」這類英文公司名也能直接查，
   `BRK.B` 會自動轉成 yfinance 用的 `BRK-B`。

兩份清單都快取在 `data/runtime/`（7 天更新一次）；連不到來源時自動退回內建字典，
功能不會中斷，查不到時畫面會提示可能的代號。

想讓部署環境不必連外就能用名稱查詢，可以先產生離線快照：

```bash
python scripts/update_symbol_directory.py             # 台股 + 美股
python scripts/update_symbol_directory.py --market us # 只更新美股
```

### 配息、除權與分割

`/api/stock_insight` 會一併回傳 `corporate_actions`：

| 欄位 | 內容 |
| --- | --- |
| `dividends.yearly` | 每年配息合計與配息次數（前端畫成歷年配息長條圖） |
| `dividends.records` | 每一次的除息日與配息金額 |
| `dividends.ttm_total` / `ttm_yield_pct` | 近 12 個月配息總額與現金殖利率（以最新股價計算） |
| `dividends.average_3y` | 近三年平均年配息 |
| `dividends.frequency` | 月配 / 季配 / 半年配 / 年配（由配息次數自動判斷） |
| `dividends.consecutive_years` | 連續配息年數 |
| `splits.records` | 股票分割與反向分割紀錄，附「1 股 → 4 股（分割）」這類說明 |
| `rights.records` | **除權（配股）紀錄**：除權日、類別、每仟股配股數、除權參考價 |
| `rights.total_shares_per_1000` | 期間內累計每仟股配股數 |
| `rights.has_twse` | 是否取得證交所的權威資料（否則是由還原係數推算） |
| `fund_profile` | ETF 專屬：前十大持股與產業分布；查不到時給 `holdings_reference`（發行商） |

#### 台股的除權是怎麼算出來的

yfinance 的 `dividends` 只有**現金股利**，台股的**配股**不在裡面，而是躲在
`splits` 裡（配 1 元股票股利 → ratio 1.1）。所以做了兩件事：

1. **判讀**：台股 ratio 落在 `1 < ratio <= 1.5` 一律視為配股而非分割，
   還原成「每仟股配 N 股 / 股票股利 M 元」；真正的分割（例如 ratio 2）仍留在分割分頁，
   同一筆不會重複出現在兩個分頁。
2. **補權威資料**：`backend/tw_exrights.py` 另外接證交所的
   [除權除息計算結果表（TWT49U）](https://www.twse.com.tw/zh/trading/exchange/twt49u.html)，
   補上「權/息」類別、除權息前收盤價與參考價。這份資料在**背景執行緒**抓取並快取 12 小時
   （失敗只快取 30 分鐘），API 不會因為證交所變慢而卡住；抓不到就安靜地退回第 1 步的推算。

#### ETF 成分股查不到的時候

Yahoo Finance 對台股 ETF 幾乎都沒有成分股資料。`get_fund_profile()` 因此：

- 同時支援 `funds_data` 屬性與 `get_funds_data()` 方法，欄位名稱（`Holding Percent` /
  `holdingPercent` / `Weight`…）也做寬鬆比對，換 yfinance 版本不會整個壞掉；
- 權重是「比例」還是「百分比」用**總和**判斷（總和 ≤ 1.5 才乘 100），不會把 0.9% 誤放大成 90%；
- 真的查不到時回傳 `holdings_reference`，前端顯示「這檔由元大投信發行，完整持股請看發行商公告」
  並附上官網連結，而不是只丟一句「沒有資料」。

另外基本資料也大幅擴充：

- **個股**：公司所在地、員工數、流通股數、PE / PEG / PB / PS、每股淨值、毛利率、營業利益率、
  淨利率、ROE、ROA、營收與盈餘成長、自由現金流、流動比率、分析師評等與目標價、下次財報日。
- **ETF**：發行商、類別、基金型態、成立日期、資產規模、費用率、週轉率、淨值、
  今年／三年／五年報酬、前次除息日、前十大持股、產業分布。

### 風險與報酬、定期定額、多標的比較

| 功能 | 說明 |
| --- | --- |
| 風險與報酬 | 期間報酬、年化報酬、年化波動、最大回撤（含發生區間）、夏普值、索提諾值、上漲月份比例，以及對大盤（台股用 `^TWII`、美股用 `^GSPC`）的 Beta 與相關係數 |
| 定期定額試算 | 每月第一個交易日固定投入，配息自動再投入；輸出累計投入、目前價值、總損益、年化報酬、累計配息、平均成本，並與「一次全押」對照 |
| 多標的比較 | 最多四檔標的以「起點 = 100」畫在同一張圖，附期間報酬、年化報酬、波動、最大回撤與夏普值表格 |

對應端點：

```text
GET /api/stock_insight?ticker=0050&period=2y     # 內含 risk_metrics 與 dca
GET /api/compare?tickers=0050,006208,00878&period=1y
```

> 定期定額的後端是以「單位金額 1000」試算，前端只要按比例換算就能即時反應金額調整（結果與金額成正比），
> 不必每次都重新呼叫 API。

### 其他前端功能

- **自選股**：星號按鈕把目前標的存進瀏覽器（最多 20 檔），搜尋列下方一鍵切換。
- **分享連結**：網址會同步 `?ticker=&period=&interval=&horizon=`，可直接收藏或傳給別人。
- **CSV 匯出**：圖表工具列的「⬇ CSV」會下載目前區間的 OHLCV 與主要指標。
- **鍵盤操作**：按 `/` 跳到搜尋框，↑ ↓ 選建議、Enter 確認。

### API 端點

| 端點 | 用途 |
| --- | --- |
| `GET /api/health` | 服務狀態與功能旗標 |
| `GET /api/symbol_search?q=00878` | 股票／ETF 自動完成（離線字典，不需外網） |
| `GET /api/stock_insight?ticker=0050&period=1y&interval=1d&forecast_horizon=7` | 價格、指標、預測、判讀、新聞一次取得 |
| `GET /api/search?ticker=2330` | 只取新聞情緒 |

`/api/stock_insight` 會回傳：

- `symbol`：實際使用的 yfinance 代號、市場別、標的種類（`stock` / `etf` / `index`）。
- `company_overview`：個股看基本面；ETF 會改成費用率、資產規模、淨值、歷史報酬等欄位。
- `technical_indicators`：`SMA(5/20/60/120/240)`、`EMA`、`BB`、`MACD`、`KD`、`RSI`、`BIAS`、`AD`、`ATR`、`OBV`。
- `price_change_detail`：日內 / 1日 / 1週 / 1月 / 3月漲跌。
- `forecast`：`holt_damped`、`theta`、`ridge_ar`、`knn_analog`、`drift`、`ema_momentum` 六個模型與加權整合結果，
  附 80% 信賴區間；每個模型都會回報自己的回測誤差（MAPE）、方向準確率與權重。
- `market_read`：多空分數、判定結果、每個指標的判讀，以及一段完整的中文總結。

可選的預測天數：`5`、`7`、`14`、`30` 天。

### 預測模型說明

| 模型 | 說明 |
| --- | --- |
| Holt 阻尼趨勢 | 二次指數平滑加上阻尼係數，參數用格點搜尋擬合 |
| Theta 法 | M3 競賽經典基準，結合線性趨勢與指數平滑 |
| Ridge 自迴歸 | 以落後報酬率、動量、波動度為特徵的脊迴歸（閉式解） |
| 歷史型態比對 | k 近鄰：找出與最近走勢最相似的歷史片段，取其後續走勢平均 |
| 漂移隨機漫步 | ARIMA(0,1,0) with drift，作為誠實的基準線 |
| EMA 動量 | 快慢均線差距外推，並隨時間阻尼衰減 |

## 專案架構

```text
stock_predict/
├── api/
│   └── index.py              # Flask 應用：所有 HTTP 路由（Vercel 也用這份）
├── backend/
│   ├── app.py                # 本機開發入口（直接沿用 api/index.py）
│   ├── fetcher.py            # yfinance 串接、ETF／上櫃代號解析、TTL 快取
│   ├── symbols.py            # 代號解析與離線搜尋
│   ├── tw_directory.py       # 台股完整清單（中文名稱查詢）
│   ├── us_directory.py       # 美股完整清單（英文名稱查詢）
│   ├── directory_cache.py    # 名稱清單的快照 / 快取 / 抓取共用邏輯
│   ├── tw_exrights.py       # 證交所除權除息計算結果表（台股配股 / 除權）
│   ├── analytics.py          # 風險指標、定期定額試算、比較序列
│   ├── symbol_catalog.py     # 熱門台股／美股／ETF 離線字典
│   ├── indicators.py         # 技術指標序列與最新快照
│   ├── forecast.py           # 六個預測模型與滾動回測加權
│   ├── signals.py            # 指標自動判讀 → 繁體中文說明
│   └── news.py               # Google News RSS 與 RNN／詞典情緒分析
├── public/
│   ├── index.html            # 單頁式前端介面
│   ├── styles.css            # 設計系統（深色／淺色變數）
│   └── app.js                # 狀態管理、圖表、主題切換
├── models/                   # 情緒模型訓練／推論腳本與權重
├── crawler/                  # 多來源新聞爬蟲
├── tests/
│   └── test_stocksense.py    # 120 個離線測試（合成資料，不需網路）
├── data/                     # 本機資料集與管線輸出
├── scripts/
│   └── update_symbol_directory.py   # 更新名稱對照表快照
├── start.sh / stop.sh        # 啟動／停止本機服務
└── vercel.json               # 部署設定
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
