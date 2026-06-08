from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests

backend_path = Path(__file__).parent.parent / "backend"
root_path = Path(__file__).parent.parent
models_path = root_path / "models"
sys.path.insert(0, str(backend_path))
sys.path.insert(0, str(models_path))

try:
    from fetcher import StockDataFetcher
except ImportError:
    StockDataFetcher = None

app = Flask(__name__)
CORS(app)

fetcher = StockDataFetcher() if StockDataFetcher else None
_rnn_runtime = None
_rnn_runtime_error = None

VALID_PERIODS = {
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
}
VALID_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"
}

def _parse_rss_datetime(value):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        return None

def _record_id(url, headline, published_at):
    key = f"{url}|{headline}|{published_at or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def _fetch_google_news(ticker, query, max_articles):
    search_text = " ".join(part for part in [ticker, query] if part).strip() or ticker or query
    url = (
        "https://news.google.com/rss/search?q="
        + quote(search_text)
        + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)

    records = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    for item in root.findall("./channel/item")[:max_articles]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_node = item.find("source")
        source = (source_node.text or "Google News").strip() if source_node is not None else "Google News"
        published_at = _parse_rss_datetime(item.findtext("pubDate"))
        if not title or not link:
            continue
        records.append({
            "id": _record_id(link, title, published_at),
            "source": source,
            "headline": title,
            "content": title,
            "url": link,
            "published_at": published_at,
            "fetched_at": fetched_at,
            "language": "zh-TW",
            "ticker": ticker,
            "sentiment_score": None,
            "sentiment_label": None,
        })
    return records

def _load_rnn_runtime():
    global _rnn_runtime, _rnn_runtime_error
    if _rnn_runtime is not None:
        return _rnn_runtime
    if _rnn_runtime_error is not None:
        raise RuntimeError(_rnn_runtime_error)
    try:
        from rnn_sentiment import build_text, load_artifacts, predict_many

        model_dir = root_path / "models" / "artifacts" / "rnn_sentiment"
        model, tokenizer, meta = load_artifacts(model_dir)
        _rnn_runtime = (build_text, predict_many, model, tokenizer, meta)
        return _rnn_runtime
    except Exception as exc:
        _rnn_runtime_error = str(exc)
        raise

def _apply_lexicon_sentiment(records):
    from sentiment_baseline import LexiconSentimentAnalyzer

    analyzer = LexiconSentimentAnalyzer()
    distribution = {"positive": 0, "neutral": 0, "negative": 0}
    for record in records:
        text = f"{record.get('headline') or ''} {record.get('content') or ''}".strip()
        result = analyzer.predict(text)
        record["sentiment_score"] = result.score
        record["sentiment_label"] = result.label
        record["sentiment_model"] = "lexicon"
        distribution[result.label] += 1
    return "lexicon_baseline_v2", distribution

def _apply_rnn_sentiment(records):
    build_text, predict_many, model, tokenizer, meta = _load_rnn_runtime()
    max_len = int(meta.get("max_len", 256))
    texts = [build_text(record) for record in records]
    preds = predict_many(model, tokenizer, texts, max_len=max_len, batch_size=64)
    distribution = {"positive": 0, "neutral": 0, "negative": 0}
    for record, pred in zip(records, preds):
        label = pred.get("sentiment_label", "neutral")
        record["sentiment_score"] = pred.get("sentiment_score", 0.0)
        record["sentiment_label"] = label
        record["sentiment_model"] = "rnn"
        distribution[label if label in distribution else "neutral"] += 1
    return str(meta.get("model_name", "bilstm_sentiment_v1")), distribution

def _summarize_news(records, distribution, model_type, model_used, model_status, model_error=None):
    scores = []
    for record in records:
        try:
            scores.append(float(record.get("sentiment_score") or 0.0))
        except (TypeError, ValueError):
            scores.append(0.0)
    total = len(records)
    denominator = max(1, total)
    summary = {
        "records": total,
        "score_mean": sum(scores) / denominator if scores else 0.0,
        "positive_ratio": distribution.get("positive", 0) / denominator,
        "neutral_ratio": distribution.get("neutral", 0) / denominator,
        "negative_ratio": distribution.get("negative", 0) / denominator,
        "model_type": model_type,
        "model_used": model_used,
        "model_status": model_status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if model_error:
        summary["model_error"] = model_error
    return summary

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
        "service": "stock_predict_backend",
        "sentiment_models": {
            "default": "rnn",
            "available": ["rnn", "lexicon"],
            "rnn_artifacts_included": (root_path / "models" / "artifacts" / "rnn_sentiment" / "model.keras").exists()
        }
    })

@app.route("/api/search")
def search_news():
    ticker = (request.args.get("ticker", "2330") or "2330").strip()
    query = (request.args.get("query", "") or "").strip()
    model_type = (request.args.get("model_type", "rnn") or "rnn").strip().lower()
    try:
        max_articles = int(request.args.get("max_articles", "50"))
    except ValueError:
        max_articles = 50
    max_articles = min(100, max(1, max_articles))

    try:
        records = _fetch_google_news(ticker=ticker, query=query, max_articles=max_articles)
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": f"新聞抓取失敗: {exc}",
            "summary": {
                "records": 0,
                "model_type": model_type,
                "model_used": "none",
                "model_status": "news_fetch_failed",
            },
            "news": [],
        }), 502

    model_status = "ok"
    model_error = None
    if model_type == "rnn":
        try:
            model_used, distribution = _apply_rnn_sentiment(records)
        except Exception as exc:
            model_error = str(exc)
            model_status = "rnn_unavailable_fallback_lexicon"
            model_used, distribution = _apply_lexicon_sentiment(records)
    else:
        model_type = "lexicon"
        model_used, distribution = _apply_lexicon_sentiment(records)

    return jsonify({
        "ok": True,
        "summary": _summarize_news(
            records=records,
            distribution=distribution,
            model_type=model_type,
            model_used=model_used,
            model_status=model_status,
            model_error=model_error,
        ),
        "news": records,
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
