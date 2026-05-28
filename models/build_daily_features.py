from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def parse_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build daily sentiment features grouped by ticker and date.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/normalized/news_with_sentiment.jsonl"),
        help="Input JSONL with sentiment fields.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/features/daily_sentiment_features.csv"),
        help="Output CSV for daily features.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_jsonl(args.input)

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        ticker = str(row.get("ticker") or "UNKNOWN")
        date = parse_date(row.get("published_at") or row.get("fetched_at"))
        if not date:
            continue
        grouped[(ticker, date)].append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "date",
                "news_count",
                "score_mean",
                "score_min",
                "score_max",
                "positive_ratio",
                "neutral_ratio",
                "negative_ratio",
            ],
        )
        writer.writeheader()

        for (ticker, date), items in sorted(grouped.items()):
            scores = [float(item.get("sentiment_score") or 0.0) for item in items]
            labels = [str(item.get("sentiment_label") or "neutral") for item in items]
            count = len(items)
            positive = sum(1 for label in labels if label == "positive")
            neutral = sum(1 for label in labels if label == "neutral")
            negative = sum(1 for label in labels if label == "negative")

            writer.writerow(
                {
                    "ticker": ticker,
                    "date": date,
                    "news_count": count,
                    "score_mean": round(sum(scores) / count, 6) if count else 0.0,
                    "score_min": round(min(scores), 6) if count else 0.0,
                    "score_max": round(max(scores), 6) if count else 0.0,
                    "positive_ratio": round(positive / count, 6) if count else 0.0,
                    "neutral_ratio": round(neutral / count, 6) if count else 0.0,
                    "negative_ratio": round(negative / count, 6) if count else 0.0,
                }
            )

    print(
        json.dumps(
            {
                "input": str(args.input),
                "output": str(args.output),
                "groups": len(grouped),
                "records": len(rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
