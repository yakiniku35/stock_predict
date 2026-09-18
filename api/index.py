"""StockSense API（Vercel Serverless / 本機共用）。

端點
----
GET /api/health          健康檢查
GET /api/symbol_search   股票 / ETF 自動完成
GET /api/stock_insight   核心端點：價格 + 指標 + 預測 + 自動判讀 + 新聞
GET /api/search          單獨的新聞情緒查詢（保留舊介面）
"""

from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

ROOT_PATH = Path(__file__).resolve().parent.parent
BACKEND_PATH = ROOT_PATH / "backend"
PUBLIC_PATH = ROOT_PATH / "public"
for path in (str(BACKEND_PATH), str(ROOT_PATH / "models")):
    if path not in sys.path:
        sys.path.insert(0, path)

import forecast as forecast_engine  # noqa: E402
import indicators as indicator_engine  # noqa: E402
import news as news_engine  # noqa: E402
import signals as signal_engine  # noqa: E402
import symbols as symbol_utils  # noqa: E402
from fetcher import StockDataFetcher  # noqa: E402

app = Flask(__name__)
CORS(app)

fetcher = StockDataFetcher()

VALID_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
VALID_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
VALID_FORECAST_HORIZONS = {5, 7, 14, 30}
API_VERSION = "2.0.0"


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _change_from_reference(latest: float, reference: float | None) -> dict:
    if reference is None or reference == 0:
        return {"change": 0.0, "pct": 0.0}
    change = latest - reference
    return {"change": round(change, 2), "pct": round((change / reference) * 100.0, 2)}


def _price_change_detail(prices: list[dict]) -> dict:
    empty = {"change": 0.0, "pct": 0.0}
    if not prices:
        return {"intraday": empty, "one_day": empty, "one_week": empty,
                "one_month": empty, "three_month": empty}

    latest = prices[-1]
    latest_close = indicator_engine.to_float_or_none(latest.get("close")) or 0.0
    latest_open = indicator_engine.to_float_or_none(latest.get("open")) or latest_close

    def close_at(offset: int) -> float | None:
        index = len(prices) - offset
        if index < 0:
            return None
        return indicator_engine.to_float_or_none(prices[index].get("close"))

    return {
        "intraday": _change_from_reference(latest_close, latest_open),
        "one_day": _change_from_reference(latest_close, close_at(2)),
        "one_week": _change_from_reference(latest_close, close_at(6)),
        "one_month": _change_from_reference(latest_close, close_at(21)),
        "three_month": _change_from_reference(latest_close, close_at(63)),
    }


def _bad_request(message: str, status: int = 400):
    return jsonify({"status": "error", "message": message}), status


# --------------------------------------------------------------------------- #
# 端點
# --------------------------------------------------------------------------- #
@app.route("/")
def home():
    """本機開發時直接把前端畫面送出；Vercel 上這條路由不會被用到（靜態檔由 CDN 提供）。"""
    if (PUBLIC_PATH / "index.html").exists():
        return send_from_directory(PUBLIC_PATH, "index.html")
    return service_info()


@app.route("/api")
def service_info():
    return jsonify({
        "service": "StockSense API",
        "status": "running",
        "version": API_VERSION,
        "endpoints": [
            "/api/health",
            "/api/symbol_search?q=0050",
            "/api/stock_insight?ticker=0050&period=1y&interval=1d&forecast_horizon=7",
            "/api/search?ticker=2330",
        ],
    })


@app.route("/api/health")
def health_check():
    rnn_ready = (ROOT_PATH / "models" / "artifacts" / "rnn_sentiment" / "model.keras").exists()
    return jsonify({
        "status": "healthy",
        "service": "stock_predict_backend",
        "version": API_VERSION,
        "features": {
            "etf_support": True,
            "symbol_search": True,
            "forecast_models": list(forecast_engine.MODEL_LABELS.keys()),
            "auto_signal_reading": True,
        },
        "sentiment_models": {
            "default": "rnn",
            "available": ["rnn", "lexicon"],
            "rnn_artifacts_included": rnn_ready,
        },
    })


@app.route("/api/symbol_search")
def symbol_search():
    """股票 / ETF 自動完成（離線字典，不需要外網）。"""
    query = request.args.get("q", "") or request.args.get("query", "")
    kind = (request.args.get("kind") or "").strip().lower() or None
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    limit = max(1, min(30, limit))

    if kind and kind not in {"etf", "stock", "index"}:
        kind = None

    results = symbol_utils.search(query, limit=limit, kind=kind)
    return jsonify({
        "status": "success",
        "query": symbol_utils.normalize_query(query),
        "count": len(results),
        "results": results,
        "quick_picks": symbol_utils.quick_picks(),
    })


@app.route("/api/stock_insight")
def get_stock_insight():
    ticker = request.args.get("ticker")
    period = request.args.get("period", "1y")
    interval = request.args.get("interval", "1d")
    include_news = request.args.get("include_news", "1") not in {"0", "false", "no"}
    model_type = (request.args.get("model_type") or "rnn").strip().lower()

    try:
        forecast_horizon = int(request.args.get("forecast_horizon", "7"))
    except ValueError:
        forecast_horizon = 7
    if forecast_horizon not in VALID_FORECAST_HORIZONS:
        forecast_horizon = 7

    if not ticker:
        return _bad_request("缺少必要的股票代碼參數 (ticker)")
    if period not in VALID_PERIODS:
        return _bad_request(f"不支援的 period: {period}")
    if interval not in VALID_INTERVALS:
        return _bad_request(f"不支援的 interval: {interval}")

    try:
        result = fetcher.fetch_prices(ticker, period=period, interval=interval)
        prices = result.get("prices")
        resolution = result.get("resolution", {})

        if not prices:
            suggestions = symbol_utils.search(ticker, limit=5)
            return jsonify({
                "status": "error",
                "message": result.get("error") or f"無法取得 {ticker} 的價格資料",
                "hint": "台股請輸入 4~6 位代號（例如 2330、0050、00878），美股請輸入英文代號（例如 SPY、QQQ）",
                "suggestions": suggestions,
            }), 404

        symbol = result["symbol"]
        catalog_entry = resolution.get("catalog")
        overview = fetcher.get_company_overview(symbol, catalog_entry)
        indicators = indicator_engine.compute_indicators(prices)
        snapshot = indicator_engine.latest_snapshot(prices, indicators)
        forecast_result = forecast_engine.compute_forecast(prices, horizon=forecast_horizon)

        news_bundle = None
        sentiment_summary = None
        if include_news:
            display_code = resolution.get("display_code") or ticker
            news_query = (catalog_entry or {}).get("name_zh") or ""
            news_bundle = news_engine.analyze_ticker_news(
                ticker=display_code, query=news_query, max_articles=60, model_type=model_type,
            )
            sentiment_summary = news_bundle.get("summary")

        instrument_kind = (overview or {}).get("kind") or resolution.get("kind")
        market_read = signal_engine.analyze(
            snapshot=snapshot,
            sentiment_summary=sentiment_summary,
            forecast_result=forecast_result,
            instrument_kind=instrument_kind,
        )

        pipeline_news = fetcher.get_news_sentiment_from_pipeline(resolution.get("display_code") or ticker)

        return jsonify({
            "status": "success",
            "ticker": ticker,
            "symbol": {
                "input": resolution.get("input"),
                "resolved": symbol,
                "display_code": resolution.get("display_code"),
                "market": resolution.get("market"),
                "kind": instrument_kind,
                "name": (overview or {}).get("name"),
                "name_zh": (catalog_entry or {}).get("name_zh"),
                "tried": result.get("tried", []),
            },
            "request": {
                "period": period,
                "effective_period": result.get("period", period),
                "interval": interval,
                "forecast_horizon": forecast_horizon,
                "include_news": include_news,
            },
            "metrics": {
                "total_fetched_prices": len(prices),
                "total_fetched_news": len((news_bundle or {}).get("news", [])),
                "cached": result.get("cached", False),
            },
            "stock_price_trends": prices,
            "company_overview": overview,
            "technical_indicators": indicators,
            "indicator_snapshot": snapshot,
            "price_change_detail": _price_change_detail(prices),
            "forecast": forecast_result,
            "market_read": market_read,
            "news": (news_bundle or {}).get("news", []),
            "news_summary": sentiment_summary,
            "news_sentiment_list": pipeline_news,
        })
    except Exception as exc:  # pragma: no cover - 保底錯誤處理
        return jsonify({
            "status": "error",
            "message": f"處理請求時發生錯誤: {exc}",
        }), 500


@app.route("/api/search")
def search_news():
    ticker = (request.args.get("ticker", "2330") or "2330").strip()
    query = (request.args.get("query", "") or "").strip()
    model_type = (request.args.get("model_type", "rnn") or "rnn").strip().lower()
    try:
        max_articles = int(request.args.get("max_articles", "60"))
    except ValueError:
        max_articles = 60
    max_articles = min(200, max(1, max_articles))

    bundle = news_engine.analyze_ticker_news(
        ticker=ticker, query=query, max_articles=max_articles, model_type=model_type,
    )
    return jsonify(bundle), (200 if bundle.get("ok") else 502)


@app.route("/<path:filename>")
def static_assets(filename: str):
    """本機開發用的靜態檔（styles.css / app.js）。"""
    target = PUBLIC_PATH / filename
    if target.is_file():
        return send_from_directory(PUBLIC_PATH, filename)
    return jsonify({"status": "error", "message": "找不到檔案"}), 404


handler = app


if __name__ == "__main__":  # 本機開發：python api/index.py
    app.run(host="0.0.0.0", port=5000, debug=True)
