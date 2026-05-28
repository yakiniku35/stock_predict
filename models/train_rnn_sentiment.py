from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import numpy as np

from rnn_sentiment import (
    RNNSentimentConfig,
    build_lstm_model,
    build_text,
    create_tokenizer,
    labels_to_ids,
    load_jsonl,
    save_artifacts,
    texts_to_padded,
)
from sentiment_baseline import LexiconSentimentAnalyzer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train BiLSTM sentiment model from news JSONL.")
    parser.add_argument("--input", type=Path, default=Path("data/normalized/news_with_sentiment.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("models/artifacts/rnn_sentiment"))
    parser.add_argument("--summary-output", type=Path, default=Path("models/artifacts/rnn_sentiment/train_summary.json"))
    parser.add_argument("--label-source", choices=["auto", "field", "lexicon"], default="auto")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--validation-split", type=float, default=0.2)
    parser.add_argument("--vocab-size", type=int, default=20000)
    parser.add_argument("--max-len", type=int, default=256)
    parser.add_argument("--embedding-dim", type=int, default=96)
    parser.add_argument("--lstm-units", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _resolve_label_source(rows: list[dict], label_source: str) -> str:
    if label_source in {"field", "lexicon"}:
        return label_source
    has_field = any(str(row.get("sentiment_label") or "").strip() for row in rows)
    return "field" if has_field else "lexicon"


def _extract_labels(rows: list[dict], label_source: str) -> tuple[list[str], str]:
    resolved = _resolve_label_source(rows, label_source)
    if resolved == "field":
        labels = [str(row.get("sentiment_label") or "neutral").lower() for row in rows]
        return labels, resolved

    analyzer = LexiconSentimentAnalyzer()
    labels: list[str] = []
    for row in rows:
        text = build_text(row)
        labels.append(analyzer.predict(text).label)
    return labels, resolved


def _class_weight_dict(y: np.ndarray) -> dict[int, float]:
    counts = np.bincount(y, minlength=3).astype(np.float32)
    total = float(np.sum(counts))
    weights: dict[int, float] = {}
    for i, count in enumerate(counts.tolist()):
        if count <= 0:
            weights[i] = 1.0
        else:
            weights[i] = total / (3.0 * float(count))
    return weights


def _shuffle_in_unison(x: np.ndarray, y: np.ndarray, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    idx = np.arange(len(x))
    rng.shuffle(idx)
    return x[idx], y[idx]


def main() -> int:
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)

    t0 = time.perf_counter()
    rows, bad_lines = load_jsonl(args.input)
    if not rows:
        raise SystemExit(f"No rows found in {args.input}")

    texts = [build_text(row) for row in rows]
    labels, resolved_source = _extract_labels(rows, args.label_source)

    config = RNNSentimentConfig(
        vocab_size=args.vocab_size,
        max_len=args.max_len,
        embedding_dim=args.embedding_dim,
        lstm_units=args.lstm_units,
    )

    tokenizer = create_tokenizer(texts, vocab_size=config.vocab_size)
    x = texts_to_padded(tokenizer, texts, max_len=config.max_len)
    y = labels_to_ids(labels)

    x, y = _shuffle_in_unison(x, y, seed=args.seed)

    model = build_lstm_model(config)

    val_split = min(0.4, max(0.05, args.validation_split))
    class_weight = _class_weight_dict(y)

    import tensorflow as tf

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_accuracy",
            patience=2,
            mode="max",
            restore_best_weights=True,
        )
    ]

    history = model.fit(
        x,
        y,
        epochs=max(1, args.epochs),
        batch_size=max(8, args.batch_size),
        validation_split=val_split,
        class_weight=class_weight,
        callbacks=callbacks,
        verbose=0,
    )

    save_artifacts(model, tokenizer, config, args.output_dir)

    hist = history.history
    best_val_acc = max(hist.get("val_accuracy", [0.0]))
    final_train_acc = hist.get("accuracy", [0.0])[-1]
    used_epochs = len(hist.get("loss", []))

    elapsed = max(1e-9, time.perf_counter() - t0)
    summary = {
        "input": str(args.input),
        "output_dir": str(args.output_dir),
        "records": len(rows),
        "bad_lines_skipped": bad_lines,
        "label_source": resolved_source,
        "training": {
            "epochs_requested": args.epochs,
            "epochs_used": used_epochs,
            "batch_size": max(8, args.batch_size),
            "validation_split": val_split,
            "class_weight": {str(k): round(v, 4) for k, v in class_weight.items()},
            "final_train_accuracy": round(float(final_train_acc), 4),
            "best_val_accuracy": round(float(best_val_acc), 4),
        },
        "runtime": {
            "seconds": round(elapsed, 4),
            "records_per_second": round(len(rows) / elapsed, 2),
            "is_rnn": True,
            "model": "bilstm_sentiment_v1",
        },
        "config": {
            "vocab_size": config.vocab_size,
            "max_len": config.max_len,
            "embedding_dim": config.embedding_dim,
            "lstm_units": config.lstm_units,
        },
    }

    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
