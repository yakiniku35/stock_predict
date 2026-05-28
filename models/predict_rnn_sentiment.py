from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rnn_sentiment import build_text, load_artifacts, load_jsonl, predict_many, write_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run trained BiLSTM sentiment model inference on JSONL.")
    parser.add_argument("--input", type=Path, default=Path("data/raw/news_latest.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/normalized/news_with_sentiment_rnn.jsonl"))
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/normalized/news_with_sentiment_rnn_summary.json"),
    )
    parser.add_argument("--model-dir", type=Path, default=Path("models/rnn_registry"))
    parser.add_argument("--batch-size", type=int, default=128)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    t0 = time.perf_counter()

    rows, bad_lines = load_jsonl(args.input)
    model, tokenizer, meta = load_artifacts(args.model_dir)

    max_len = int(meta.get("max_len", 256))
    texts = [build_text(row) for row in rows]
    preds = predict_many(model, tokenizer, texts, max_len=max_len, batch_size=max(1, args.batch_size))

    distribution = {"positive": 0, "neutral": 0, "negative": 0}
    for row, pred in zip(rows, preds):
        row["sentiment_score"] = pred["sentiment_score"]
        row["sentiment_label"] = pred["sentiment_label"]
        distribution[pred["sentiment_label"]] += 1

    write_jsonl(args.output, rows)

    elapsed = max(1e-9, time.perf_counter() - t0)
    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "model_dir": str(args.model_dir),
        "records": len(rows),
        "bad_lines_skipped": bad_lines,
        "distribution": distribution,
        "runtime": {
            "batch_size": max(1, args.batch_size),
            "seconds": round(elapsed, 4),
            "records_per_second": round(len(rows) / elapsed, 2),
            "is_rnn": True,
            "model": str(meta.get("model_name", "bilstm_sentiment_v1")),
        },
    }

    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
