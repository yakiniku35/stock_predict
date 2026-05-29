# Stock Predict

[繁體中文](docs/README.zh-TW.md)

A stock trend prediction project for Taiwan and U.S. markets. The goal is to combine historical market data, financial indicators, and news or social sentiment signals to support price trend analysis and visualization.

> Project status: Phase 1 (multi-source crawler), Phase 2 (sentiment baseline + time-bucket features), and Phase 3 (RNN/LSTM training, deployment, rollback, and A/B monitoring) are implemented.

## Features

- Fetch historical price data and financial indicators with [yfinance](https://github.com/ranaroussi/yfinance).
- Collect auxiliary market context, such as news and social discussions, through crawlers.
- Analyze sentiment signals with both lexicon baseline and RNN/LSTM models (switchable by runtime flags).
- Predict directional price trends from price, indicator, and sentiment features.
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
  --max-articles 200
```

Common flags:

- `--append`: append records instead of overwriting output.
- `--max-articles`: cap record count for one run.
- `--ticker`: set default stock ticker for each record.
- `--query`: dynamic query for sources with `{query}` / `{query_encoded}` placeholders.
- `--per-source-max-items`: cap records per source for throughput/source balance.
- `--summary-output`: write run-level crawler summary JSON.

Output schema (one JSON object per line):

- `id`, `source`, `headline`, `content`, `url`
- `published_at` (UTC ISO timestamp)
- `fetched_at` (UTC ISO timestamp)
- `language`, `ticker`
- `sentiment_score`, `sentiment_label` (filled in Phase 2)

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

Current structure:

```text
stock_predict/
├── README.md
├── README.zh-TW.md
├── LICENSE
├── requirements.txt
└── .gitignore
```

Planned structure:

```text
stock_predict/
├── backend/          # API, data processing, model inference
├── frontend/         # Plotly/Dash or web interface
├── data/             # Local datasets and cached market data
├── models/           # Training scripts and saved models
├── crawler/          # News and social data collectors
├── tests/            # Unit and integration tests
└── requirements.txt
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
