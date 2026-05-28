from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sklearn.metrics import accuracy_score, f1_score

from rnn_sentiment import build_text, get_active_model, load_artifacts, load_jsonl, predict_many, set_active_model
from sentiment_baseline import LexiconSentimentAnalyzer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrain RNN model offline and promote it as active model.")
    parser.add_argument("--input", type=Path, default=Path("data/normalized/news_with_sentiment.jsonl"))
    parser.add_argument("--registry-dir", type=Path, default=Path("models/rnn_registry"))
    parser.add_argument("--run-name", type=str, default="")
    parser.add_argument("--label-source", choices=["auto", "field", "lexicon"], default="auto")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--validation-split", type=float, default=0.2)
    parser.add_argument("--vocab-size", type=int, default=20000)
    parser.add_argument("--max-len", type=int, default=256)
    parser.add_argument("--embedding-dim", type=int, default=96)
    parser.add_argument("--lstm-units", type=int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--eval-input", type=Path, default=Path("data/normalized/news_with_sentiment.jsonl"))
    parser.add_argument("--eval-label-source", choices=["auto", "field", "lexicon"], default="auto")
    parser.add_argument("--eval-sample-size", type=int, default=600)
    parser.add_argument("--rollback-metric", choices=["macro_f1", "accuracy"], default="macro_f1")
    parser.add_argument("--rollback-min-improvement", type=float, default=0.0)
    parser.add_argument("--disable-rollback", action="store_true")
    parser.add_argument("--force-promote", action="store_true")
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("models/rnn_registry/last_retrain_summary.json"),
    )
    return parser.parse_args()


def _run_training(args: argparse.Namespace, run_dir: Path, train_summary_path: Path) -> None:
    train_script = Path(__file__).resolve().parent / "train_rnn_sentiment.py"
    cmd = [
        sys.executable,
        str(train_script),
        "--input",
        str(args.input),
        "--output-dir",
        str(run_dir),
        "--summary-output",
        str(train_summary_path),
        "--label-source",
        args.label_source,
        "--epochs",
        str(args.epochs),
        "--batch-size",
        str(args.batch_size),
        "--validation-split",
        str(args.validation_split),
        "--vocab-size",
        str(args.vocab_size),
        "--max-len",
        str(args.max_len),
        "--embedding-dim",
        str(args.embedding_dim),
        "--lstm-units",
        str(args.lstm_units),
        "--seed",
        str(args.seed),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "RNN training failed.\\n"
            f"stdout:\\n{proc.stdout}\\n"
            f"stderr:\\n{proc.stderr}"
        )


def _resolve_eval_labels(rows: list[dict], source: str) -> tuple[list[str], str]:
    has_field = all(str(row.get("sentiment_label") or "").strip() for row in rows)
    resolved = source
    if source == "auto":
        resolved = "field" if has_field else "lexicon"

    if resolved == "field":
        labels = [str(row.get("sentiment_label") or "neutral").lower() for row in rows]
        return labels, resolved

    analyzer = LexiconSentimentAnalyzer()
    labels = [analyzer.predict(build_text(row)).label for row in rows]
    return labels, "lexicon"


def _sample_rows(rows: list[dict], labels: list[str], sample_size: int, seed: int) -> tuple[list[dict], list[str]]:
    if sample_size <= 0 or len(rows) <= sample_size:
        return rows, labels
    indices = list(range(len(rows)))
    rng = random.Random(seed)
    rng.shuffle(indices)
    picked = indices[:sample_size]
    return [rows[i] for i in picked], [labels[i] for i in picked]


def _predict_labels_rnn(model_dir: Path, rows: list[dict], batch_size: int) -> list[str]:
    model, tokenizer, meta = load_artifacts(model_dir)
    max_len = int(meta.get("max_len", 256))
    texts = [build_text(row) for row in rows]
    preds = predict_many(model, tokenizer, texts, max_len=max_len, batch_size=max(1, batch_size))
    return [str(item.get("sentiment_label") or "neutral") for item in preds]


def _metrics(y_true: list[str], y_pred: list[str]) -> dict[str, float]:
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    accuracy = float(accuracy_score(y_true, y_pred))
    return {
        "macro_f1": round(macro_f1, 6),
        "accuracy": round(accuracy, 6),
    }


def _evaluate_model(model_dir: Path, eval_rows: list[dict], eval_labels: list[str], batch_size: int) -> dict:
    pred_labels = _predict_labels_rnn(model_dir, eval_rows, batch_size=batch_size)
    return {
        "model_dir": str(model_dir),
        "metrics": _metrics(eval_labels, pred_labels),
        "records": len(eval_rows),
    }


def _evaluate_lexicon(eval_rows: list[dict], eval_labels: list[str]) -> dict:
    analyzer = LexiconSentimentAnalyzer()
    pred_labels = [analyzer.predict(build_text(row)).label for row in eval_rows]
    return {
        "model": "lexicon_baseline_v2",
        "metrics": _metrics(eval_labels, pred_labels),
        "records": len(eval_rows),
    }


def main() -> int:
    args = parse_args()

    run_token = args.run_name.strip() or datetime.now().strftime("%Y%m%d_%H%M%S")
    registry_dir = args.registry_dir.resolve()
    run_dir = registry_dir / "runs" / run_token
    train_summary_path = run_dir / "train_summary.json"

    run_dir.mkdir(parents=True, exist_ok=True)
    _run_training(args, run_dir=run_dir, train_summary_path=train_summary_path)

    eval_rows_all, eval_bad_lines = load_jsonl(args.eval_input)
    if not eval_rows_all:
        raise SystemExit(f"No evaluation rows found in {args.eval_input}")
    eval_labels_all, resolved_label_source = _resolve_eval_labels(eval_rows_all, args.eval_label_source)
    eval_rows, eval_labels = _sample_rows(
        eval_rows_all,
        eval_labels_all,
        sample_size=max(0, args.eval_sample_size),
        seed=args.seed,
    )

    candidate_eval = _evaluate_model(run_dir, eval_rows, eval_labels, batch_size=args.batch_size)
    baseline_eval = _evaluate_lexicon(eval_rows, eval_labels)

    previous_active_dir: Path | None = None
    previous_active_eval: dict | None = None
    try:
        previous_active_dir = get_active_model(registry_dir)
    except FileNotFoundError:
        previous_active_dir = None

    if previous_active_dir is not None and previous_active_dir.resolve() != run_dir.resolve():
        previous_active_eval = _evaluate_model(previous_active_dir, eval_rows, eval_labels, batch_size=args.batch_size)

    promoted = False
    rollback_triggered = False
    decision_reason = ""

    metric_name = args.rollback_metric
    min_gain = args.rollback_min_improvement

    if args.force_promote:
        promoted = True
        decision_reason = "force_promote=true"
    elif previous_active_eval is None:
        promoted = True
        decision_reason = "no_previous_active_model"
    elif args.disable_rollback:
        promoted = True
        decision_reason = "rollback_disabled"
    else:
        candidate_score = float(candidate_eval["metrics"][metric_name])
        current_score = float(previous_active_eval["metrics"][metric_name])
        gain = candidate_score - current_score
        promoted = gain >= min_gain
        rollback_triggered = not promoted
        decision_reason = (
            f"candidate_{metric_name}={candidate_score:.6f}, "
            f"current_{metric_name}={current_score:.6f}, gain={gain:.6f}, required>={min_gain:.6f}"
        )

    active_dir = previous_active_dir
    if promoted:
        active_dir = set_active_model(registry_dir, run_dir)

    train_summary = json.loads(train_summary_path.read_text(encoding="utf-8"))

    summary = {
        "registry_dir": str(registry_dir),
        "run_dir": str(run_dir),
        "active_model_dir": str(active_dir) if active_dir else None,
        "is_rnn": True,
        "rollback": {
            "enabled": not args.disable_rollback,
            "triggered": rollback_triggered,
            "metric": metric_name,
            "min_improvement": min_gain,
            "promoted": promoted,
            "reason": decision_reason,
        },
        "evaluation": {
            "input": str(args.eval_input),
            "bad_lines_skipped": eval_bad_lines,
            "label_source": resolved_label_source,
            "records": len(eval_rows),
            "candidate": candidate_eval,
            "previous_active": previous_active_eval,
            "lexicon_baseline": baseline_eval,
        },
        "train_summary": train_summary,
    }

    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
