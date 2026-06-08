from flask import Flask, jsonify, request
from flask_cors import CORS
import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

try:
    from fetcher import StockDataFetcher
except ImportError:
    StockDataFetcher = None

app = Flask(__name__)
CORS(app)

fetcher = StockDataFetcher() if StockDataFetcher else None

VALID_PERIODS = {
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
}
VALID_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"
}

@app.route("/")
def home():
    return jsonify({
        "service": "StockSense API",
        "status": "running",
        "version": "1.0.0",
        "endpoints": [
            "/api/health",
            "/api/stock_insight?ticker=2330&period=1mo&interval=1d"
        ]
    })

@app.route("/api/health")
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "stock_predict_backend"
    })

@app.route("/api/stock_insight")
def get_stock_insight():
    ticker = request.args.get("ticker")
    period = request.args.get("period", "1mo")
    interval = request.args.get("interval", "1d")

    if not ticker:
        return jsonify({
            "status": "error",
            "message": "缺少必要的股票代碼參數 (ticker)"
        }), 400

    if period not in VALID_PERIODS:
        return jsonify({
            "status": "error",
            "message": f"不支援的 period: {period}"
        }), 400

    if interval not in VALID_INTERVALS:
        return jsonify({
            "status": "error",
            "message": f"不支援的 interval: {interval}"
        }), 400

    if not fetcher:
        return jsonify({
            "status": "error",
            "message": "資料獲取服務未啟用"
        }), 503

    try:
        prices = fetcher.get_historical_prices(ticker, period=period, interval=interval)
        
        if prices is None:
            return jsonify({
                "status": "error",
                "message": f"無法取得代碼 {ticker} 的股價資料"
            }), 404

        news_sentiment = fetcher.get_news_sentiment_from_pipeline(ticker)

        return jsonify({
            "status": "success",
            "ticker": ticker,
            "request": {"period": period, "interval": interval},
            "metrics": {
                "total_fetched_prices": len(prices),
                "total_fetched_news": len(news_sentiment)
            },
            "stock_price_trends": prices,
            "news_sentiment_list": news_sentiment
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"處理請求時發生錯誤: {str(e)}"
        }), 500

handler = app
