from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate AB run reports into a daily monitoring summary.")
    parser.add_argument(
        "--input-glob",
        type=str,
        default="data/monitoring/ab_runs/*.json",
        help="Glob pattern of AB report JSON files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/monitoring/ab_report_daily.json"),
    )
    return parser.parse_args()


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _zero_dist() -> dict[str, int]:
    return {"positive": 0, "neutral": 0, "negative": 0}


def _merge_dist(dst: dict[str, int], src: dict[str, int]) -> None:
    for key in ["positive", "neutral", "negative"]:
        dst[key] += _safe_int(src.get(key, 0))


def main() -> int:
    args = parse_args()
    base = Path(".")
    files = sorted(base.glob(args.input_glob))

    total_runs = 0
    total_records = 0
    total_errors = 0

    rnn_records = 0
    rnn_errors = 0
    rnn_seconds = 0.0
    rnn_dist = _zero_dist()

    lex_records = 0
    lex_errors = 0
    lex_seconds = 0.0
    lex_dist = _zero_dist()

    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        arms = payload.get("arms", {})

        total_runs += 1
        total_records += _safe_int(payload.get("records", 0))
        total_errors += _safe_int(payload.get("errors", 0))

        rnn = arms.get("rnn", {})
        lex = arms.get("lexicon", {})

        rnn_records += _safe_int(rnn.get("records", 0))
        rnn_errors += _safe_int(rnn.get("errors", 0))
        rnn_seconds += _safe_float(rnn.get("seconds", 0.0))
        _merge_dist(rnn_dist, rnn.get("distribution", {}))

        lex_records += _safe_int(lex.get("records", 0))
        lex_errors += _safe_int(lex.get("errors", 0))
        lex_seconds += _safe_float(lex.get("seconds", 0.0))
        _merge_dist(lex_dist, lex.get("distribution", {}))

    def _rps(records: int, seconds: float) -> float:
        if seconds <= 0:
            return 0.0
        return round(records / seconds, 2)

    summary = {
        "input_glob": args.input_glob,
        "runs": total_runs,
        "records": total_records,
        "errors": total_errors,
        "arms": {
            "rnn": {
                "records": rnn_records,
                "errors": rnn_errors,
                "seconds": round(rnn_seconds, 4),
                "records_per_second": _rps(rnn_records, rnn_seconds),
                "distribution": rnn_dist,
            },
            "lexicon": {
                "records": lex_records,
                "errors": lex_errors,
                "seconds": round(lex_seconds, 4),
                "records_per_second": _rps(lex_records, lex_seconds),
                "distribution": lex_dist,
            },
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
