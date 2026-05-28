# Stock Predict

[繁體中文](README.zh-TW.md)

A stock trend prediction project for Taiwan and U.S. markets. The goal is to combine historical market data, financial indicators, and news or social sentiment signals to support price trend analysis and visualization.

> Project status: early scaffold. The repository currently contains documentation and dependency placeholders; application code is not included yet.

## Features

- Fetch historical price data and financial indicators with [yfinance](https://github.com/ranaroussi/yfinance).
- Collect auxiliary market context, such as news and social discussions, through crawlers.
- Analyze sentiment signals with an RNN-based model.
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
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

The application entry points are not available yet. Once the backend and frontend modules are added, this section should be updated with the commands to run them.

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

Output schema (one JSON object per line):

- `id`, `source`, `headline`, `content`, `url`
- `published_at` (UTC ISO timestamp)
- `fetched_at` (UTC ISO timestamp)
- `language`, `ticker`
- `sentiment_score`, `sentiment_label` (filled in Phase 2)

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
├── crawlers/         # News and social data collectors
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

## Disclaimer

This project is for research and educational purposes only. It does not provide financial advice, investment recommendations, or guaranteed prediction results.
