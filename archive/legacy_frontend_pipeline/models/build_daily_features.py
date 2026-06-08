from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def floor_to_bucket(dt: datetime, timeframe: str) -> datetime:
    if timeframe == "day":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if timeframe == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    if timeframe == "30min":
        minute = 30 if dt.minute >= 30 else 0
        return dt.replace(minute=minute, second=0, microsecond=0)
    if timeframe == "15min":
        minute = (dt.minute // 15) * 15
        return dt.replace(minute=minute, second=0, microsecond=0)
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def bucket_seconds(timeframe: str) -> int:
    if timeframe == "day":
        return 86400
    if timeframe == "hour":
        return 3600
    if timeframe == "30min":
        return 1800
    if timeframe == "15min":
        return 900
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def read_jsonl(path: Path) -> tuple[list[dict], int]:
    if not path.exists():
        return [], 0
    rows: list[dict] = []
    bad_lines = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                bad_lines += 1
    return rows, bad_lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build time-bucket sentiment features by ticker.")
    parser.add_argument("--input", type=Path, default=Path("data/normalized/news_with_sentiment.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/features/sentiment_features_hour.csv"))
    parser.add_argument(
        "--timeframe",
        type=str,
        default="hour",
        choices=["day", "hour", "30min", "15min"],
        help="Time bucket granularity",
    )
    parser.add_argument(
        "--timezone",
        type=str,
        default="Asia/Taipei",
        help="IANA timezone used for bucketing",
    )
    return parser.parse_args()


def resolve_timezone(name: str):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Taipei":
            return timezone(timedelta(hours=8), name)
        raise


def stddev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(var)


def main() -> int:
    args = parse_args()
    rows, bad_lines = read_jsonl(args.input)

    tz = resolve_timezone(args.timezone)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for row in rows:
        ticker = str(row.get("ticker") or "UNKNOWN")
        dt = parse_datetime(row.get("published_at") or row.get("fetched_at"))
        if dt is None:
            continue
        local_dt = dt.astimezone(tz)
        bucket_start = floor_to_bucket(local_dt, args.timeframe)
        bucket_key = bucket_start.isoformat()
        grouped[(ticker, bucket_key)].append(row)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "timeframe",
                "timezone",
                "bucket_start",
                "bucket_end",
                "news_count",
                "score_mean",
                "score_std",
                "score_min",
                "score_max",
                "positive_ratio",
                "neutral_ratio",
                "negative_ratio",
            ],
        )
        writer.writeheader()

        span_seconds = bucket_seconds(args.timeframe)
        for (ticker, bucket_start_text), items in sorted(grouped.items()):
            bucket_start = datetime.fromisoformat(bucket_start_text)
            bucket_end = bucket_start + timedelta(seconds=span_seconds)

            scores = [float(item.get("sentiment_score") or 0.0) for item in items]
            labels = [str(item.get("sentiment_label") or "neutral") for item in items]
            count = len(items)
            positive = sum(1 for label in labels if label == "positive")
            neutral = sum(1 for label in labels if label == "neutral")
            negative = sum(1 for label in labels if label == "negative")

            writer.writerow(
                {
                    "ticker": ticker,
                    "timeframe": args.timeframe,
                    "timezone": args.timezone,
                    "bucket_start": bucket_start.isoformat(),
                    "bucket_end": bucket_end.isoformat(),
                    "news_count": count,
                    "score_mean": round(sum(scores) / count, 6) if count else 0.0,
                    "score_std": round(stddev(scores), 6) if count else 0.0,
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
                "timeframe": args.timeframe,
                "timezone": args.timezone,
                "groups": len(grouped),
                "records": len(rows),
                "bad_lines_skipped": bad_lines,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
