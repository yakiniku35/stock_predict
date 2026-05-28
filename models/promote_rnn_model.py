from __future__ import annotations

import argparse
import json
from pathlib import Path

from rnn_sentiment import set_active_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote a trained RNN model as active model in registry.")
    parser.add_argument("--registry-dir", type=Path, default=Path("models/rnn_registry"))
    parser.add_argument("--model-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    active_dir = set_active_model(args.registry_dir, args.model_dir)
    summary = {
        "registry_dir": str(args.registry_dir.resolve()),
        "active_model_dir": str(active_dir),
        "is_rnn": True,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
