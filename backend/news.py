"""新聞抓取與情緒分析（RNN + 詞典校準）。

原本這段程式寫在 `api/index.py` 裡，現在抽成獨立模組，
讓 Vercel 的 `api/index.py` 與本機的 `backend/app.py` 共用同一份邏輯。
"""

from __future__ import annotations

import hashlib
import logging
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

ROOT_PATH = Path(__file__).resolve().parent.parent
MODELS_PATH = ROOT_PATH / "models"
if str(MODELS_PATH) not in sys.path:
    sys.path.insert(0, str(MODELS_PATH))

_rnn_runtime = None
_rnn_runtime_error: str | None = None
_lexicon_analyzer = None

POSITIVE_THRESHOLD = 12.0
NEGATIVE_THRESHOLD = -12.0


# --------------------------------------------------------------------------- #
# 抓取
# --------------------------------------------------------------------------- #
def _parse_rss_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _record_id(url: str, headline: str, published_at: str | None) -> str:
    key = f"{url}|{headline}|{published_at or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def fetch_google_news(ticker: str, query: str = "", max_articles: int = 60,
                      timeout: int = 20) -> list[dict]:
    """用 Google News RSS 抓取中文財經新聞。"""
    search_text = " ".join(part for part in [ticker, query] if part).strip() or ticker or query
    url = (
        "https://news.google.com/rss/search?q="
        + quote(search_text)
        + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    response.raise_for_status()
    root = ET.fromstring(response.content)

    records: list[dict] = []
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


# --------------------------------------------------------------------------- #
# 模型
# --------------------------------------------------------------------------- #
def _load_rnn_runtime():
    global _rnn_runtime, _rnn_runtime_error
    if _rnn_runtime is not None:
        return _rnn_runtime
    if _rnn_runtime_error is not None:
        raise RuntimeError(_rnn_runtime_error)
    try:
        from rnn_sentiment import build_text, load_artifacts, predict_many

        model_dir = MODELS_PATH / "artifacts" / "rnn_sentiment"
        model, tokenizer, meta = load_artifacts(model_dir)
        _rnn_runtime = (build_text, predict_many, model, tokenizer, meta)
        return _rnn_runtime
    except Exception as exc:
        _rnn_runtime_error = str(exc)
        raise


def get_lexicon_analyzer():
    global _lexicon_analyzer
    if _lexicon_analyzer is None:
        from sentiment_baseline import LexiconSentimentAnalyzer

        _lexicon_analyzer = LexiconSentimentAnalyzer(
            positive_threshold=POSITIVE_THRESHOLD,
            negative_threshold=NEGATIVE_THRESHOLD,
        )
    return _lexicon_analyzer


def _normalize_score(score) -> float:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return 0.0
    return round(max(-100.0, min(100.0, numeric)), 2)


def apply_lexicon_sentiment(records: list[dict]) -> tuple[str, dict]:
    analyzer = get_lexicon_analyzer()
    distribution = {"positive": 0, "neutral": 0, "negative": 0}
    for record in records:
        text = f"{record.get('headline') or ''} {record.get('content') or ''}".strip()
        result = analyzer.predict(text)
        record["sentiment_score"] = result.score
        record["sentiment_label"] = result.label
        record["sentiment_model"] = "lexicon"
        distribution[result.label] = distribution.get(result.label, 0) + 1
    return "lexicon_baseline_v2", distribution


def _calibrate(record: dict, pred: dict, analyzer):
    """RNN 判中立、但標題有明確財經用詞時，用詞典結果校正。"""
    text = f"{record.get('headline') or ''} {record.get('content') or ''}".strip()
    lex = analyzer.predict(text)
    rnn_label = pred.get("sentiment_label", "neutral")
    rnn_score = _normalize_score(pred.get("sentiment_score", 0.0))

    label = rnn_label if rnn_label in {"positive", "neutral", "negative"} else "neutral"
    score = rnn_score
    calibration = "rnn"

    lex_is_clear = lex.label != "neutral" and abs(float(lex.score)) >= POSITIVE_THRESHOLD
    rnn_is_weak = label == "neutral" or abs(rnn_score) < POSITIVE_THRESHOLD
    if lex_is_clear and rnn_is_weak:
        label = lex.label
        score = round((rnn_score * 0.35) + (float(lex.score) * 0.65), 2)
        calibration = "lexicon_override"
    elif lex.label != "neutral" and label == lex.label:
        score = round((rnn_score * 0.7) + (float(lex.score) * 0.3), 2)
        calibration = "lexicon_confirmed"
    return label, score, calibration, lex


def apply_rnn_sentiment(records: list[dict]) -> tuple[str, dict]:
    build_text, predict_many, model, tokenizer, meta = _load_rnn_runtime()
    max_len = int(meta.get("max_len", 256))
    texts = [build_text(record) for record in records]
    preds = predict_many(model, tokenizer, texts, max_len=max_len, batch_size=64)
    analyzer = get_lexicon_analyzer()
    distribution = {"positive": 0, "neutral": 0, "negative": 0}
    for record, pred in zip(records, preds):
        label, score, calibration, lex = _calibrate(record, pred, analyzer)
        record["sentiment_score"] = score
        record["sentiment_label"] = label
        record["sentiment_model"] = "rnn+lexicon"
        record["sentiment_calibration"] = calibration
        record["lexicon_score"] = lex.score
        record["lexicon_label"] = lex.label
        distribution[label if label in distribution else "neutral"] += 1
    return str(meta.get("model_name", "bilstm_sentiment_v1")), distribution


def summarize(records: list[dict], distribution: dict, model_type: str, model_used: str,
              model_status: str, model_error: str | None = None) -> dict:
    scores: list[float] = []
    for record in records:
        try:
            scores.append(float(record.get("sentiment_score") or 0.0))
        except (TypeError, ValueError):
            scores.append(0.0)

    total = len(records)
    denominator = max(1, total)
    positive_ratio = distribution.get("positive", 0) / denominator
    neutral_ratio = distribution.get("neutral", 0) / denominator
    negative_ratio = distribution.get("negative", 0) / denominator
    score_mean = sum(scores) / denominator if scores else 0.0
    polarity_balance = positive_ratio - negative_ratio

    if score_mean >= POSITIVE_THRESHOLD or polarity_balance >= 0.12:
        dominant_label = "positive"
    elif score_mean <= NEGATIVE_THRESHOLD or polarity_balance <= -0.12:
        dominant_label = "negative"
    else:
        dominant_label = "neutral"

    summary = {
        "records": total,
        "score_mean": round(score_mean, 2),
        "positive_ratio": round(positive_ratio, 4),
        "neutral_ratio": round(neutral_ratio, 4),
        "negative_ratio": round(negative_ratio, 4),
        "polarity_balance": round(polarity_balance, 4),
        "dominant_label": dominant_label,
        "model_type": model_type,
        "model_used": model_used,
        "model_status": model_status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if model_error:
        summary["model_error"] = model_error
    return summary


def analyze_ticker_news(ticker: str, query: str = "", max_articles: int = 60,
                        model_type: str = "rnn") -> dict:
    """一次完成「抓新聞 + 跑情緒模型 + 統計摘要」。"""
    model_type = (model_type or "rnn").lower()
    try:
        records = fetch_google_news(ticker=ticker, query=query, max_articles=max_articles)
    except Exception as exc:
        # 詳細錯誤只寫進伺服器日誌，回傳給前端的是固定訊息
        logger.warning("新聞抓取失敗 (%s): %s", ticker, exc)
        return {
            "ok": False,
            "error": "新聞服務暫時無法使用，請稍後再試",
            "summary": summarize([], {}, model_type, "none", "news_fetch_failed"),
            "news": [],
        }

    model_status = "ok"
    model_error = None
    if model_type == "rnn":
        try:
            model_used, distribution = apply_rnn_sentiment(records)
        except Exception as exc:
            logger.warning("RNN 情緒模型載入失敗，改用詞典模型: %s", exc)
            model_error = "rnn_model_unavailable"
            model_status = "rnn_unavailable_fallback_lexicon"
            model_used, distribution = apply_lexicon_sentiment(records)
    else:
        model_type = "lexicon"
        model_used, distribution = apply_lexicon_sentiment(records)

    return {
        "ok": True,
        "summary": summarize(records, distribution, model_type, model_used, model_status, model_error),
        "news": records,
    }
