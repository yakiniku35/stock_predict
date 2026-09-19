# Stock Predict

[繁體中文](docs/README.zh-TW.md)

A stock trend prediction project for Taiwan and U.S. markets. The goal is to combine historical market data, financial indicators, and news or social sentiment signals to support price trend analysis and visualization.

> Project status: Phase 1 (multi-source crawler), Phase 2 (sentiment baseline + time-bucket features), and Phase 3 (RNN/LSTM training, deployment, rollback, and A/B monitoring) are implemented.

## Features

- Analyze **both stocks and ETFs** across Taiwan (listed + OTC) and U.S. markets, with symbol search in Chinese or English.
- Fetch historical price data and financial indicators with [yfinance](https://github.com/ranaroussi/yfinance).
- Collect auxiliary market context, such as news and social discussions, through crawlers.
- Analyze sentiment signals with both lexicon baseline and RNN/LSTM models (switchable by runtime flags).
- Read every technical indicator automatically and turn it into a plain Traditional Chinese explanation of the current market state.
- Predict price trends with a backtest-weighted ensemble of six time-series models (with confidence band).
- Present interactive charts and analysis results with [Plotly](https://github.com/plotly/plotly.py).

## Quick Start

Clone the repository:

```bash
git clone https://github.com/yakiniku35/stock_predict.git
cd stock_predict
```

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Backend/frontend service entry points are still evolving, but the data pipeline, sentiment training, inference, rollback, and monitoring scripts are runnable now.

### News Scraper (Phase 1 runnable)

Run the scraper and export normalized news records to JSONL:

```bash
python -m crawler.news_scraper \
  --config crawler/news_sources.json \
  --output data/raw/news_latest.jsonl \
  --ticker 2330 \
  --content-extract-mode auto \
  --max-articles 200
```

Common flags:

- `--append`: append records instead of overwriting output.
- `--max-articles`: cap record count for one run.
- `--ticker`: set default stock ticker for each record.
- `--query`: dynamic query for sources with `{query}` / `{query_encoded}` placeholders.
- `--per-source-max-items`: cap records per source for throughput/source balance.
- `--content-extract-mode`: `source` | `auto` | `html` | `r.jina.ai` | `markdown.new`.
  - `auto` tries `r.jina.ai` and `markdown.new` to get cleaner article body, then falls back to HTML selector parsing.
- `--disable-content-extract-fallback`: disable HTML fallback after remote extraction failure.
- `--content-extract-timeout`: override timeout (seconds) for remote extraction.
- `--summary-output`: write run-level crawler summary JSON.

Output schema (one JSON object per line):

- `id`, `source`, `headline`, `content`, `url`
- `published_at` (UTC ISO timestamp)
- `fetched_at` (UTC ISO timestamp)
- `language`, `ticker`
- `sentiment_score`, `sentiment_label` (filled in Phase 2)

## Web App (v2)

Run everything with one command:

```bash
./start.sh          # http://127.0.0.1:5000
python tests/test_stocksense.py   # 94 offline tests, no network needed
```

Highlights:

- **Stocks and ETFs**: Taiwan listed/OTC codes are resolved automatically (`0050`, `00878`, `006208` -> `.TW`, `6488` -> `.TWO`), plus US tickers and ETFs (`SPY`, `QQQ`, `NVDA`). Chinese names work too (`台積電`, `高股息`).
- **Dark / light / auto theme**: switchable in the header, persisted in `localStorage`; charts re-theme with the UI.
- **Auto signal reading**: 11 indicators (trend, RSI, MACD, KD, Bollinger, BIAS, volume/OBV, 52w position, volatility, news sentiment, model forecast) are scored into a -100..+100 verdict with a generated Traditional Chinese explanation.
- **Backtested forecasting**: six real time-series models, weighted by walk-forward backtest error instead of hard-coded constants.

### 中文名稱查詢

輸入中文（例如「台積電」「長榮航」「高股息」）也能找到標的：

1. `backend/symbol_catalog.py` bundles ~125 popular symbols with Chinese and English names.
2. `backend/tw_directory.py` pulls the full TWSE/TPEx listing (~3,000 stocks and ETFs) from the
   exchange ISIN page.
3. `backend/us_directory.py` pulls the full U.S. listing (~11,000 stocks and ETFs, with an ETF flag)
   from the NASDAQ Trader symbol files, so English company names such as "Palantir" resolve too.
4. Both are cached under `data/runtime/` for 7 days and degrade to the bundled catalog offline.
5. Optional offline snapshot for deployment: `python scripts/update_symbol_directory.py`.

### Dividends and splits

`/api/stock_insight` also returns `corporate_actions`:

- `dividends.yearly`: dividend total and payment count per year (drives the bar chart).
- `dividends.records`: every ex-dividend date and amount.
- `dividends.ttm_total` / `ttm_yield_pct` / `average_3y`: trailing 12-month dividend and yield.
- `dividends.frequency`: monthly / quarterly / semi-annual / annual, detected from payment counts.
- `dividends.consecutive_years`: consecutive years with a dividend.
- `splits.records`: split and reverse-split history with readable labels.
- `fund_profile` (ETF only): top 10 holdings and sector weightings.

### Risk, DCA and comparison

- `risk_metrics` (in `/api/stock_insight`): total and annualized return, annualized volatility, max drawdown
  with its peak/trough dates, Sharpe, Sortino, monthly win rate, plus beta and correlation against the local
  benchmark (`^TWII` for Taiwan, `^GSPC` for the U.S.).
- `dca` (in `/api/stock_insight`): monthly dollar-cost-averaging simulation with dividend reinvestment,
  computed for a unit contribution so the UI can rescale instantly; includes a lump-sum comparison.
- `GET /api/compare?tickers=0050,006208,00878&period=1y`: up to four symbols rebased to 100 with their
  risk/return metrics side by side.

The front end also has a watchlist (stored in the browser), shareable URLs
(`?ticker=&period=&interval=&horizon=`) and CSV export of prices and indicators.

### API endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Service and feature flags |
| `GET /api/symbol_search?q=00878` | Offline symbol autocomplete (stocks + ETFs) |
| `GET /api/stock_insight?ticker=0050&period=1y&interval=1d&forecast_horizon=7` | Prices, indicators, forecast, auto reading, news |
| `GET /api/search?ticker=2330` | News sentiment only |

`/api/stock_insight` returns:

- `symbol`: resolved yfinance symbol, market, instrument kind (`stock` / `etf` / `index`).
- `company_overview`: stock fundamentals, or ETF fields (expense ratio, total assets, NAV, trailing returns).
- `technical_indicators`: `SMA(5/20/60/120/240)`, `EMA`, `BB`, `MACD`, `KD`, `RSI`, `BIAS`, `AD`, `ATR`, `OBV`.
- `price_change_detail`: intraday / 1D / 1W / 1M / 3M changes.
- `forecast`: `holt_damped`, `theta`, `ridge_ar`, `knn_analog`, `drift`, `ema_momentum` plus a weighted ensemble with an 80% confidence band. Every model reports its walk-forward MAPE, directional accuracy and weight.
- `market_read`: verdict score, stance, per-indicator reading and a Traditional Chinese summary paragraph.

Forecast horizons: `5`, `7`, `14`, `30` days.

## Phase 2: Sentiment Baseline + Time-Bucket Features

### 1) Batch sentiment labeling

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/run_sentiment_batch.py \
  --input data/raw/news_latest.jsonl \
  --output data/normalized/news_with_sentiment.jsonl \
  --summary-output data/normalized/news_with_sentiment_summary.json \
  --model-type lexicon \
  --workers 4
```

Sentiment score scale:

- `100`: super positive
- `0`: neutral
- `-100`: super negative

Default lexicon thresholds are `20` (positive) and `-20` (negative).

### 2) Build time-bucket features

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/build_daily_features.py \
  --input data/normalized/news_with_sentiment.jsonl \
  --output data/features/sentiment_features_hour.csv \
  --timeframe hour \
  --timezone Asia/Taipei
```

Supported `--timeframe` values:

- `day`
- `hour`
- `30min`
- `15min`

## Phase 3: RNN/LSTM Training and Inference

### Speed-accuracy balance strategy

- Online path: use lexicon for low-latency scoring.
- Offline path: retrain RNN periodically for better quality.
- Deployment: switch weights by updating the active model pointer.

### 1) Train BiLSTM model

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/train_rnn_sentiment.py \
  --input data/normalized/news_with_sentiment.jsonl \
  --output-dir models/rnn_artifacts \
  --summary-output models/rnn_artifacts/train_summary.json \
  --label-source auto \
  --epochs 8 \
  --batch-size 64 \
  --max-len 256 \
  --vocab-size 20000
```

### 2) Offline retrain with auto rollback decision

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

Rollback behavior:

- If the new model does not beat active model by required margin, promotion is skipped.
- Use `--disable-rollback` to bypass checks.
- Use `--force-promote` to promote regardless of metric comparison.
- Use `--event-log` to append rollback/promotion events and `--notify-hook-url` + `--notify-on rollback` for webhook alerts.

### 3) RNN inference

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/predict_rnn_sentiment.py \
  --input data/raw/news_latest.jsonl \
  --output data/normalized/news_with_sentiment_rnn.jsonl \
  --summary-output data/normalized/news_with_sentiment_rnn_summary.json \
  --model-dir models/rnn_registry \
  --batch-size 128
```

### 4) Unified batch entrypoint with RNN mode

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/run_sentiment_batch.py \
  --input data/raw/news_latest.jsonl \
  --output data/normalized/news_with_sentiment.jsonl \
  --summary-output data/normalized/news_with_sentiment_summary.json \
  --model-type rnn \
  --rnn-model-dir models/rnn_registry \
  --rnn-batch-size 128
```

### 5) Online A/B traffic split (lexicon vs RNN)

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

### 6) Aggregate A/B monitoring reports

```bash
/Users/peterchiu/stock_predict/.venv/bin/python models/generate_ab_monitoring_report.py \
  --input-glob "data/monitoring/ab_runs/report_*.json" \
  --eval-summary models/rnn_registry/last_retrain_summary.json \
  --output data/monitoring/ab_report_daily.json \
  --markdown-output data/monitoring/ab_report_daily.md \
  --ratio-config models/rnn_registry/traffic_policy.json \
  --write-ratio-config
```

Outputs:

- `ab_report_daily.json`: aggregated stats + daily metrics + 7/30 day trend datasets.
- `ab_report_daily.md`: human-readable report with Mermaid trend charts.
- `traffic_policy.json`: adaptive `rnn_ratio` policy consumed by AB inference.

Adaptive traffic policy notes:

- The next `rnn_ratio` is computed from both quality (accuracy from evaluation summary) and speed (7-day throughput).
- Use `--weight-accuracy` and `--weight-throughput` to tune priorities.
- Use `--max-ratio-step` to cap per-run ratio changes and avoid oscillation.

### 7) Cron templates

See `docs/cron_templates.md` for scheduling templates:

- Daily offline retrain + rollback checks
- 5-minute online A/B inference runs
- Daily A/B summary report generation

## Project Structure

```text
stock_predict/
├── api/
│   └── index.py              # Flask app: all HTTP routes (also used by Vercel)
├── backend/
│   ├── app.py                # Local dev entry point (reuses api/index.py)
│   ├── fetcher.py            # yfinance access, ETF/OTC resolution, TTL cache
│   ├── symbols.py            # Symbol resolution and offline search
│   ├── tw_directory.py       # Full TWSE/TPEx listing (Chinese name lookup)
│   ├── us_directory.py       # Full U.S. listing (English name lookup)
│   ├── directory_cache.py    # Shared snapshot / cache / fetch plumbing
│   ├── analytics.py          # Risk metrics, DCA simulation, comparison series
│   ├── symbol_catalog.py     # Offline catalog of popular TW/US stocks and ETFs
│   ├── indicators.py         # Technical indicator series + latest snapshot
│   ├── forecast.py           # Six forecasting models + walk-forward backtest
│   ├── signals.py            # Auto indicator reading -> Traditional Chinese text
│   └── news.py               # Google News RSS + RNN/lexicon sentiment
├── public/
│   ├── index.html            # Single-page UI
│   ├── styles.css            # Design system (dark / light tokens)
│   └── app.js                # State, charts, theme switching
├── models/                   # Sentiment training / inference scripts + artifacts
├── crawler/                  # Multi-source news crawler
├── tests/
│   └── test_stocksense.py    # 94 offline tests (synthetic data, no network)
├── data/                     # Local datasets and pipeline output
├── scripts/
│   └── update_symbol_directory.py   # Refresh the offline name snapshots
├── start.sh / stop.sh        # Start and stop the local service
└── vercel.json               # Deployment config
```

## Data Sources

- Historical prices and financial indicators: [yfinance](https://github.com/ranaroussi/yfinance)
- Market context: news articles, social discussions, and other public sources collected through crawlers

Please review the terms of service and usage limits of each data provider before collecting or redistributing data.

## Contributors

Thanks to all contributors.

[![Contributors](https://contrib.rocks/image?repo=yakiniku35/stock_predict)](https://github.com/yakiniku35/stock_predict/graphs/contributors)

## Development Notes

- Keep reproducible setup steps in this README whenever dependencies or entry points change.
- Store secrets and API keys in local environment variables or ignored `.env` files.
- Avoid committing raw datasets, model checkpoints, or generated cache files unless they are intentionally versioned.
- Add tests alongside core data processing, model, and API modules as the project grows.
- Prefer registry-based model switching (`models/rnn_registry/active_model.json`) for safe online weight upgrades.

## Disclaimer

This project is for research and educational purposes only. It does not provide financial advice, investment recommendations, or guaranteed prediction results.
