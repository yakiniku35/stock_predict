from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw/news_latest.jsonl"),
        help="Input news JSONL path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/normalized/news_with_sentiment.jsonl"),
        help="Output JSONL path with sentiment fields.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/normalized/news_with_sentiment_summary.json"),
        help="Summary report path.",
    )
    parser.add_argument("--positive-threshold", type=float, default=0.2)
    parser.add_argument("--negative-threshold", type=float, default=-0.2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_jsonl(args.input)

    analyzer = LexiconSentimentAnalyzer(
        positive_threshold=args.positive_threshold,
        negative_threshold=args.negative_threshold,
    )

    errors = 0
    distribution = {"positive": 0, "neutral": 0, "negative": 0}
    for row in rows:
        headline = str(row.get("headline") or "")
        content = str(row.get("content") or "")
        text = f"{headline} {content}".strip()

        try:
            result = analyzer.predict(text)
            row["sentiment_score"] = result.score
            row["sentiment_label"] = result.label
            distribution[result.label] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            distribution["neutral"] += 1

    write_jsonl(args.output, rows)

    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "records": len(rows),
        "errors": errors,
        "distribution": distribution,
        "thresholds": {
            "positive": args.positive_threshold,
            "negative": args.negative_threshold,
        },
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
