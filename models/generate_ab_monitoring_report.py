from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
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
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("data/monitoring/ab_report_daily.md"),
    )
    parser.add_argument(
        "--eval-summary",
        type=Path,
        default=Path("models/rnn_registry/last_retrain_summary.json"),
    )
    parser.add_argument("--current-ratio", type=float, default=-1.0)
    parser.add_argument(
        "--ratio-config",
        type=Path,
        default=Path("models/rnn_registry/traffic_policy.json"),
    )
    parser.add_argument("--weight-accuracy", type=float, default=0.75)
    parser.add_argument("--weight-throughput", type=float, default=0.25)
    parser.add_argument("--min-rnn-ratio", type=float, default=0.1)
    parser.add_argument("--max-rnn-ratio", type=float, default=0.9)
    parser.add_argument("--max-ratio-step", type=float, default=0.08)
    parser.add_argument("--write-ratio-config", action="store_true")
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


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parse_report_time(path: Path, payload: dict) -> datetime:
    generated = payload.get("generated_at")
    if isinstance(generated, str) and generated.strip():
        text = generated.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass

    match = re.search(r"(\d{8})_(\d{6})", path.name)
    if match:
        date_part = match.group(1)
        time_part = match.group(2)
        try:
            dt = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _daily_bucket_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


def _sum_dist(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {
        "positive": _safe_int(left.get("positive", 0)) + _safe_int(right.get("positive", 0)),
        "neutral": _safe_int(left.get("neutral", 0)) + _safe_int(right.get("neutral", 0)),
        "negative": _safe_int(left.get("negative", 0)) + _safe_int(right.get("negative", 0)),
    }


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _build_window(days: dict[str, dict], day_count: int) -> list[dict]:
    if not days:
        return []
    max_day = max(datetime.fromisoformat(day) for day in days.keys())
    start_day = max_day - timedelta(days=max(0, day_count - 1))

    window: list[dict] = []
    cursor = start_day
    while cursor <= max_day:
        key = cursor.date().isoformat()
        entry = days.get(
            key,
            {
                "date": key,
                "runs": 0,
                "records": 0,
                "errors": 0,
                "rnn_records": 0,
                "rnn_seconds": 0.0,
                "rnn_rps": 0.0,
                "lex_records": 0,
                "lex_seconds": 0.0,
                "lex_rps": 0.0,
                "rnn_ratio_actual": 0.0,
            },
        )
        window.append(entry)
        cursor += timedelta(days=1)
    return window


def _to_mermaid(window: list[dict], title: str) -> str:
    if not window:
        return "No trend data"

    x_labels = [item["date"][5:] for item in window]
    rnn_values = [round(float(item.get("rnn_rps", 0.0)), 2) for item in window]
    lex_values = [round(float(item.get("lex_rps", 0.0)), 2) for item in window]

    return "\n".join(
        [
            "```mermaid",
            "xychart-beta",
            f'    title "{title}"',
            f"    x-axis [{', '.join(x_labels)}]",
            "    y-axis \"records/s\" 0 --> 20000",
            f"    line \"RNN\" [{', '.join(str(v) for v in rnn_values)}]",
            f"    line \"Lexicon\" [{', '.join(str(v) for v in lex_values)}]",
            "```",
        ]
    )


def _load_eval_metrics(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    evaluation = payload.get("evaluation", {})
    candidate = evaluation.get("candidate", {}).get("metrics", {})
    lexicon = evaluation.get("lexicon_baseline", {}).get("metrics", {})

    return {
        "rnn_accuracy": _safe_float(candidate.get("accuracy", 0.0)),
        "rnn_macro_f1": _safe_float(candidate.get("macro_f1", 0.0)),
        "lex_accuracy": _safe_float(lexicon.get("accuracy", 0.0)),
        "lex_macro_f1": _safe_float(lexicon.get("macro_f1", 0.0)),
    }


def _resolve_current_ratio(cli_ratio: float, ratio_config_path: Path, latest_report_ratio: float) -> float:
    if cli_ratio >= 0:
        return _clip(cli_ratio, 0.0, 1.0)

    if ratio_config_path.exists():
        try:
            payload = json.loads(ratio_config_path.read_text(encoding="utf-8"))
            return _clip(_safe_float(payload.get("rnn_ratio", latest_report_ratio)), 0.0, 1.0)
        except json.JSONDecodeError:
            return _clip(latest_report_ratio, 0.0, 1.0)

    return _clip(latest_report_ratio, 0.0, 1.0)


def _adaptive_ratio(
    current_ratio: float,
    metrics: dict,
    rnn_rps_7d: float,
    lex_rps_7d: float,
    weight_accuracy: float,
    weight_throughput: float,
    min_ratio: float,
    max_ratio: float,
    max_step: float,
) -> dict:
    acc_rnn = _safe_float(metrics.get("rnn_accuracy", 0.0))
    acc_lex = _safe_float(metrics.get("lex_accuracy", 0.0))

    # Keep the score in [-1, 1] so ratio updates are stable.
    acc_gap = _clip((acc_rnn - acc_lex) / 0.3, -1.0, 1.0)
    thr_denom = max(1.0, rnn_rps_7d, lex_rps_7d)
    thr_gap = _clip((rnn_rps_7d - lex_rps_7d) / thr_denom, -1.0, 1.0)

    w_acc = max(0.0, weight_accuracy)
    w_thr = max(0.0, weight_throughput)
    w_sum = w_acc + w_thr if (w_acc + w_thr) > 0 else 1.0
    w_acc /= w_sum
    w_thr /= w_sum

    combined = (w_acc * acc_gap) + (w_thr * thr_gap)
    target = _clip(current_ratio + (combined * 0.25), min_ratio, max_ratio)
    delta = _clip(target - current_ratio, -abs(max_step), abs(max_step))
    next_ratio = _clip(current_ratio + delta, min_ratio, max_ratio)

    return {
        "current_ratio": round(current_ratio, 6),
        "target_ratio": round(target, 6),
        "recommended_ratio": round(next_ratio, 6),
        "components": {
            "accuracy_gap_normalized": round(acc_gap, 6),
            "throughput_gap_normalized": round(thr_gap, 6),
            "weight_accuracy": round(w_acc, 4),
            "weight_throughput": round(w_thr, 4),
            "combined_score": round(combined, 6),
        },
    }


def _write_ratio_config(path: Path, ratio_payload: dict) -> None:
    payload = {
        "rnn_ratio": ratio_payload["recommended_ratio"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "generate_ab_monitoring_report.py",
        "adaptive": ratio_payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _markdown_report(summary: dict, trend_7d: list[dict], trend_30d: list[dict]) -> str:
    adaptive = summary.get("adaptive_ratio", {})
    lines = [
        "# AB Monitoring Report",
        "",
        f"- Runs: {summary.get('runs', 0)}",
        f"- Records: {summary.get('records', 0)}",
        f"- Errors: {summary.get('errors', 0)}",
        "",
        "## Adaptive RNN Ratio",
        f"- Current: {adaptive.get('current_ratio', 0.0)}",
        f"- Target: {adaptive.get('target_ratio', 0.0)}",
        f"- Recommended: {adaptive.get('recommended_ratio', 0.0)}",
        "",
        "## 7-day Throughput Trend",
        _to_mermaid(trend_7d, "7-day Throughput (RNN vs Lexicon)"),
        "",
        "## 30-day Throughput Trend",
        _to_mermaid(trend_30d, "30-day Throughput (RNN vs Lexicon)"),
    ]
    return "\n".join(lines)


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

    latest_ratio = 0.5
    daily: dict[str, dict] = {}

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

        config = payload.get("ab_config", {})
        latest_ratio = _safe_float(config.get("rnn_ratio", latest_ratio))

        day_key = _daily_bucket_key(_parse_report_time(path, payload))
        if day_key not in daily:
            daily[day_key] = {
                "date": day_key,
                "runs": 0,
                "records": 0,
                "errors": 0,
                "rnn_records": 0,
                "rnn_seconds": 0.0,
                "rnn_dist": _zero_dist(),
                "lex_records": 0,
                "lex_seconds": 0.0,
                "lex_dist": _zero_dist(),
            }
        day = daily[day_key]
        day["runs"] += 1
        day["records"] += _safe_int(payload.get("records", 0))
        day["errors"] += _safe_int(payload.get("errors", 0))
        day["rnn_records"] += _safe_int(rnn.get("records", 0))
        day["rnn_seconds"] += _safe_float(rnn.get("seconds", 0.0))
        day["rnn_dist"] = _sum_dist(day["rnn_dist"], rnn.get("distribution", {}))
        day["lex_records"] += _safe_int(lex.get("records", 0))
        day["lex_seconds"] += _safe_float(lex.get("seconds", 0.0))
        day["lex_dist"] = _sum_dist(day["lex_dist"], lex.get("distribution", {}))

    def _rps(records: int, seconds: float) -> float:
        if seconds <= 0:
            return 0.0
        return round(records / seconds, 2)

    for item in daily.values():
        item["rnn_rps"] = _rps(_safe_int(item["rnn_records"]), _safe_float(item["rnn_seconds"]))
        item["lex_rps"] = _rps(_safe_int(item["lex_records"]), _safe_float(item["lex_seconds"]))
        item["rnn_ratio_actual"] = round(
            _safe_int(item["rnn_records"]) / max(1, _safe_int(item["records"])),
            6,
        )

    trend_7d = _build_window(daily, day_count=7)
    trend_30d = _build_window(daily, day_count=30)
    eval_metrics = _load_eval_metrics(args.eval_summary)

    rnn_rps_7d = _avg([_safe_float(item.get("rnn_rps", 0.0)) for item in trend_7d])
    lex_rps_7d = _avg([_safe_float(item.get("lex_rps", 0.0)) for item in trend_7d])
    current_ratio = _resolve_current_ratio(args.current_ratio, args.ratio_config, latest_ratio)
    adaptive = _adaptive_ratio(
        current_ratio=current_ratio,
        metrics=eval_metrics,
        rnn_rps_7d=rnn_rps_7d,
        lex_rps_7d=lex_rps_7d,
        weight_accuracy=args.weight_accuracy,
        weight_throughput=args.weight_throughput,
        min_ratio=min(args.min_rnn_ratio, args.max_rnn_ratio),
        max_ratio=max(args.min_rnn_ratio, args.max_rnn_ratio),
        max_step=args.max_ratio_step,
    )

    summary = {
        "input_glob": args.input_glob,
        "runs": total_runs,
        "records": total_records,
        "errors": total_errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
        "trends": {
            "daily": [daily[key] for key in sorted(daily.keys())],
            "window_7d": trend_7d,
            "window_30d": trend_30d,
        },
        "evaluation_metrics": eval_metrics,
        "adaptive_ratio": adaptive,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(_markdown_report(summary, trend_7d, trend_30d), encoding="utf-8")

    if args.write_ratio_config:
        _write_ratio_config(args.ratio_config, adaptive)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
