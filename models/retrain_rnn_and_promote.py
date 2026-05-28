from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rnn_sentiment import set_active_model


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


def main() -> int:
    args = parse_args()

    run_token = args.run_name.strip() or datetime.now().strftime("%Y%m%d_%H%M%S")
    registry_dir = args.registry_dir.resolve()
    run_dir = registry_dir / "runs" / run_token
    train_summary_path = run_dir / "train_summary.json"

    run_dir.mkdir(parents=True, exist_ok=True)
    _run_training(args, run_dir=run_dir, train_summary_path=train_summary_path)

    active_dir = set_active_model(registry_dir, run_dir)
    train_summary = json.loads(train_summary_path.read_text(encoding="utf-8"))

    summary = {
        "registry_dir": str(registry_dir),
        "run_dir": str(run_dir),
        "active_model_dir": str(active_dir),
        "is_rnn": True,
        "train_summary": train_summary,
    }

    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
