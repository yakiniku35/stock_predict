from fetcher import StockDataFetcher  # 引入你寫的 Fetcher 模組
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
# 啟用跨域 (CORS)，確保鞏冠崙的 Frontend (Plotly/Dash) 可以跨 Port 順利呼叫 API
CORS(app)

# 實例化你的資料獲取器
fetcher = StockDataFetcher()


@app.route("/api/stock_insight", methods=["GET"])
def get_stock_insight():
    """核心 API 端點：接收股票代碼，整合回傳股價走勢與情緒數據"""
    # 獲取前端傳入的參數，例如 ?ticker=2330&period=1mo
    ticker = request.args.get("ticker")
    period = request.args.get("period", "1mo")
    interval = request.args.get("interval", "1d")

    if not ticker:
        return jsonify({"status": "error", "message": "缺少必要的股票代碼參數 (ticker)"}), 400

    # 1. 執行你負責的 yfinance 資料鏈路
    prices = fetcher.get_historical_prices(
        ticker, period=period, interval=interval
    )

    if prices is None:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"無法取得代碼 {ticker} 的股價資料，請檢查代碼是否正確",
                }
            ),
            404,
        )

    # 2. 執行對接組員的情緒資料鏈路
    news_sentiment = fetcher.get_news_sentiment_from_pipeline(ticker)

    # 3. 後端整合：將兩者打包成結構化的 JSON 回傳
    response_payload = {
        "status": "success",
        "ticker": ticker,
        "metrics": {
            "total_fetched_prices": len(prices),
            "total_fetched_news": len(news_sentiment),
        },
        "stock_price_trends": prices,  # 提供給前端 Plotly 繪製 K 線圖
        "news_sentiment_list": news_sentiment,  # 提供給前端呈現 AI 標註列表
    }

    return jsonify(response_payload)


@app.route("/api/health", methods=["GET"])
def health_check():
    """系統健康檢查端點"""
    return jsonify({"status": "healthy", "service": "stock_predict_backend"})


if __name__ == "__main__":
    # 啟動後端本地伺服器，預設 Port 5000
    app.run(host="0.0.0.0", port=5000, debug=True)