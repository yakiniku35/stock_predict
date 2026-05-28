from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rnn_sentiment import build_text as build_rnn_text
from rnn_sentiment import load_artifacts, predict_many
from sentiment_baseline import LexiconSentimentAnalyzer


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run baseline sentiment tagging on news JSONL.")
    parser.add_argument("--input", type=Path, default=Path("data/raw/news_latest.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/normalized/news_with_sentiment.jsonl"))
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/normalized/news_with_sentiment_summary.json"),
    )
    parser.add_argument("--positive-threshold", type=float, default=0.2)
    parser.add_argument("--negative-threshold", type=float, default=-0.2)
    parser.add_argument("--workers", type=int, default=0, help="0 means auto use single-thread batch mode")
    parser.add_argument("--model-type", choices=["lexicon", "rnn"], default="lexicon")
    parser.add_argument("--rnn-model-dir", type=Path, default=Path("models/rnn_registry"))
    parser.add_argument("--rnn-batch-size", type=int, default=128)
    return parser.parse_args()


def _build_text(row: dict) -> str:
    headline = str(row.get("headline") or "")
    content = str(row.get("content") or "")
    return f"{headline} {content}".strip()


def _predict_parallel(rows: list[dict], analyzer: LexiconSentimentAnalyzer, workers: int) -> tuple[int, dict[str, int]]:
    errors = 0
    distribution = {"positive": 0, "neutral": 0, "negative": 0}

    texts = [_build_text(row) for row in rows]

    def one(text: str):
        return analyzer.predict(text)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(one, texts))

    for row, result in zip(rows, results):
        try:
            row["sentiment_score"] = result.score
            row["sentiment_label"] = result.label
            distribution[result.label] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            distribution["neutral"] += 1

    return errors, distribution


def _predict_single(rows: list[dict], analyzer: LexiconSentimentAnalyzer) -> tuple[int, dict[str, int]]:
    errors = 0
    distribution = {"positive": 0, "neutral": 0, "negative": 0}

    texts = [_build_text(row) for row in rows]
    results = analyzer.predict_many(texts)

    for row, result in zip(rows, results):
        try:
            row["sentiment_score"] = result.score
            row["sentiment_label"] = result.label
            distribution[result.label] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            distribution["neutral"] += 1

    return errors, distribution


def _predict_rnn(rows: list[dict], model_dir: Path, batch_size: int) -> tuple[int, dict[str, int], str]:
    errors = 0
    distribution = {"positive": 0, "neutral": 0, "negative": 0}

    model, tokenizer, meta = load_artifacts(model_dir)
    max_len = int(meta.get("max_len", 256))
    texts = [build_rnn_text(row) for row in rows]
    preds = predict_many(model, tokenizer, texts, max_len=max_len, batch_size=max(1, batch_size))

    for row, pred in zip(rows, preds):
        try:
            row["sentiment_score"] = pred["sentiment_score"]
            row["sentiment_label"] = pred["sentiment_label"]
            distribution[pred["sentiment_label"]] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            distribution["neutral"] += 1

    model_name = str(meta.get("model_name", "bilstm_sentiment_v1"))
    return errors, distribution, model_name


def main() -> int:
    args = parse_args()
    t0 = time.perf_counter()
    rows = read_jsonl(args.input)

    workers = max(0, args.workers)
    if args.model_type == "rnn":
        errors, distribution, model_name = _predict_rnn(rows, args.rnn_model_dir, args.rnn_batch_size)
        execution_mode = "rnn_batch"
        is_rnn = True
        used_workers = 1
        used_thresholds = None
    else:
        analyzer = LexiconSentimentAnalyzer(
            positive_threshold=args.positive_threshold,
            negative_threshold=args.negative_threshold,
        )
        if workers <= 1:
            errors, distribution = _predict_single(rows, analyzer)
            execution_mode = "single_batch"
        else:
            errors, distribution = _predict_parallel(rows, analyzer, workers)
            execution_mode = "thread_pool"
        model_name = analyzer.model_name
        is_rnn = False
        used_workers = workers
        used_thresholds = {
            "positive": args.positive_threshold,
            "negative": args.negative_threshold,
        }

    write_jsonl(args.output, rows)

    elapsed = max(1e-9, time.perf_counter() - t0)
    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "records": len(rows),
        "errors": errors,
        "distribution": distribution,
        "thresholds": used_thresholds,
        "runtime": {
            "execution_mode": execution_mode,
            "workers": used_workers,
            "seconds": round(elapsed, 4),
            "records_per_second": round(len(rows) / elapsed, 2),
            "model": model_name,
            "is_rnn": is_rnn,
        },
        "model_type": args.model_type,
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
