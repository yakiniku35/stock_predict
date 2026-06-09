from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from rnn_sentiment import build_text as build_rnn_text
from rnn_sentiment import load_artifacts, predict_many
from sentiment_baseline import LexiconSentimentAnalyzer


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


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run baseline sentiment tagging on news JSONL.")
    parser.add_argument("--input", type=Path, default=Path("data/raw/news_latest.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/normalized/news_with_sentiment.jsonl"))
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("data/normalized/news_with_sentiment_summary.json"),
    )
    parser.add_argument("--positive-threshold", type=float, default=20.0)
    parser.add_argument("--negative-threshold", type=float, default=-20.0)
    parser.add_argument("--workers", type=int, default=0, help="0 means auto use single-thread batch mode")
    parser.add_argument("--model-type", choices=["lexicon", "rnn"], default="lexicon")
    parser.add_argument("--rnn-model-dir", type=Path, default=Path("models/rnn_registry"))
    parser.add_argument("--rnn-batch-size", type=int, default=128)
    parser.add_argument("--ab-enabled", action="store_true")
    parser.add_argument("--ab-rnn-ratio", type=float, default=None)
    parser.add_argument("--ab-key-field", type=str, default="id")
    parser.add_argument("--ab-salt", type=str, default="stock_predict_ab_v1")
    parser.add_argument("--ab-report-output", type=Path, default=None)
    parser.add_argument("--ab-ratio-config", type=Path, default=Path("models/rnn_registry/traffic_policy.json"))
    return parser.parse_args()


def _build_text(row: dict) -> str:
    headline = str(row.get("headline") or "")
    content = str(row.get("content") or "")
    return f"{headline} {content}".strip()


def _hash_ratio(key: str, salt: str) -> float:
    digest = hashlib.md5(f"{salt}:{key}".encode("utf-8")).hexdigest()
    value = int(digest[:8], 16)
    return value / 0xFFFFFFFF


def _choose_ab_indices(rows: list[dict], rnn_ratio: float, key_field: str, salt: str) -> tuple[list[int], list[int]]:
    ratio = min(1.0, max(0.0, rnn_ratio))
    rnn_indices: list[int] = []
    lex_indices: list[int] = []

    for idx, row in enumerate(rows):
        key = str(row.get(key_field) or row.get("url") or row.get("headline") or idx)
        if _hash_ratio(key, salt) < ratio:
            rnn_indices.append(idx)
        else:
            lex_indices.append(idx)
    return rnn_indices, lex_indices


def _zero_distribution() -> dict[str, int]:
    return {"positive": 0, "neutral": 0, "negative": 0}


def _predict_parallel(rows: list[dict], analyzer: LexiconSentimentAnalyzer, workers: int) -> tuple[int, dict[str, int]]:
    errors = 0
    distribution = _zero_distribution()

    texts = [_build_text(row) for row in rows]

    def one(text: str):
        return analyzer.predict(text)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(one, texts))

    for row, result in zip(rows, results):
        try:
            row["sentiment_score"] = result.score
            row["sentiment_label"] = result.label
            distribution[result.label] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            distribution["neutral"] += 1

    return errors, distribution


def _predict_single(rows: list[dict], analyzer: LexiconSentimentAnalyzer) -> tuple[int, dict[str, int]]:
    errors = 0
    distribution = _zero_distribution()

    texts = [_build_text(row) for row in rows]
    results = analyzer.predict_many(texts)

    for row, result in zip(rows, results):
        try:
            row["sentiment_score"] = result.score
            row["sentiment_label"] = result.label
            distribution[result.label] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            distribution["neutral"] += 1

    return errors, distribution


def _predict_rnn(rows: list[dict], model_dir: Path, batch_size: int) -> tuple[int, dict[str, int], str]:
    errors = 0
    distribution = _zero_distribution()

    model, tokenizer, meta = load_artifacts(model_dir)
    max_len = int(meta.get("max_len", 256))
    texts = [build_rnn_text(row) for row in rows]
    preds = predict_many(model, tokenizer, texts, max_len=max_len, batch_size=max(1, batch_size))

    for row, pred in zip(rows, preds):
        try:
            row["sentiment_score"] = pred["sentiment_score"]
            row["sentiment_label"] = pred["sentiment_label"]
            row["sentiment_model"] = "rnn"
            distribution[pred["sentiment_label"]] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            row["sentiment_model"] = "rnn"
            distribution["neutral"] += 1

    model_name = str(meta.get("model_name", "bilstm_sentiment_v1"))
    return errors, distribution, model_name


def _predict_rnn_subset(
    rows: list[dict],
    indices: list[int],
    model,
    tokenizer,
    max_len: int,
    batch_size: int,
) -> tuple[int, dict[str, int], float]:
    start = time.perf_counter()
    errors = 0
    distribution = _zero_distribution()

    subset = [rows[i] for i in indices]
    texts = [build_rnn_text(row) for row in subset]
    preds = predict_many(model, tokenizer, texts, max_len=max_len, batch_size=max(1, batch_size))

    for idx, pred in zip(indices, preds):
        row = rows[idx]
        try:
            row["sentiment_score"] = pred["sentiment_score"]
            row["sentiment_label"] = pred["sentiment_label"]
            row["sentiment_model"] = "rnn"
            distribution[pred["sentiment_label"]] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            row["sentiment_model"] = "rnn"
            distribution["neutral"] += 1

    elapsed = max(1e-9, time.perf_counter() - start)
    return errors, distribution, elapsed


def _predict_lexicon_subset(
    rows: list[dict],
    indices: list[int],
    analyzer: LexiconSentimentAnalyzer,
    workers: int,
) -> tuple[int, dict[str, int], float]:
    start = time.perf_counter()
    errors = 0
    distribution = _zero_distribution()

    subset = [rows[i] for i in indices]
    texts = [_build_text(row) for row in subset]
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(analyzer.predict, texts))
    else:
        results = analyzer.predict_many(texts)

    for idx, result in zip(indices, results):
        row = rows[idx]
        try:
            row["sentiment_score"] = result.score
            row["sentiment_label"] = result.label
            row["sentiment_model"] = "lexicon"
            distribution[result.label] += 1
        except Exception:
            errors += 1
            row["sentiment_score"] = 0.0
            row["sentiment_label"] = "neutral"
            row["sentiment_model"] = "lexicon"
            distribution["neutral"] += 1

    elapsed = max(1e-9, time.perf_counter() - start)
    return errors, distribution, elapsed


def _merge_distribution(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {
        "positive": int(left.get("positive", 0)) + int(right.get("positive", 0)),
        "neutral": int(left.get("neutral", 0)) + int(right.get("neutral", 0)),
        "negative": int(left.get("negative", 0)) + int(right.get("negative", 0)),
    }


def _default_ab_report_path(summary_output: Path) -> Path:
    return summary_output.with_name(f"{summary_output.stem}_ab_report.json")


def _write_ab_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_ab_ratio(cli_ratio: float | None, config_path: Path) -> tuple[float, str]:
    if cli_ratio is not None:
        return min(1.0, max(0.0, cli_ratio)), "cli"

    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            configured = float(payload.get("rnn_ratio", 0.5))
            return min(1.0, max(0.0, configured)), "config"
        except (ValueError, TypeError, json.JSONDecodeError):
            return 0.5, "fallback"

    return 0.5, "default"


def main() -> int:
    args = parse_args()
    t0 = time.perf_counter()
    rows, bad_lines = read_jsonl(args.input)

    workers = max(0, args.workers)
    if args.ab_enabled:
        effective_ratio, ratio_source = _resolve_ab_ratio(args.ab_rnn_ratio, args.ab_ratio_config)
        analyzer = LexiconSentimentAnalyzer(
            positive_threshold=args.positive_threshold,
            negative_threshold=args.negative_threshold,
        )
        model, tokenizer, meta = load_artifacts(args.rnn_model_dir)
        model_name = str(meta.get("model_name", "bilstm_sentiment_v1"))
        max_len = int(meta.get("max_len", 256))

        rnn_indices, lex_indices = _choose_ab_indices(
            rows,
            rnn_ratio=effective_ratio,
            key_field=args.ab_key_field,
            salt=args.ab_salt,
        )

        rnn_errors, rnn_dist, rnn_seconds = _predict_rnn_subset(
            rows,
            rnn_indices,
            model=model,
            tokenizer=tokenizer,
            max_len=max_len,
            batch_size=args.rnn_batch_size,
        )
        lex_errors, lex_dist, lex_seconds = _predict_lexicon_subset(
            rows,
            lex_indices,
            analyzer=analyzer,
            workers=workers if workers > 1 else 1,
        )

        errors = rnn_errors + lex_errors
        distribution = _merge_distribution(rnn_dist, lex_dist)
        execution_mode = "ab_hybrid"
        is_rnn = "mixed"
        used_workers = workers
        used_thresholds = {
            "positive": args.positive_threshold,
            "negative": args.negative_threshold,
        }

        ab_report_output = args.ab_report_output or _default_ab_report_path(args.summary_output)
        ab_report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input": str(args.input),
            "records": len(rows),
            "errors": errors,
            "ab_config": {
                "enabled": True,
                "rnn_ratio": effective_ratio,
                "ratio_source": ratio_source,
                "ratio_config": str(args.ab_ratio_config),
                "key_field": args.ab_key_field,
                "salt": args.ab_salt,
            },
            "arms": {
                "rnn": {
                    "model": model_name,
                    "records": len(rnn_indices),
                    "errors": rnn_errors,
                    "seconds": round(rnn_seconds, 4),
                    "records_per_second": round(len(rnn_indices) / max(1e-9, rnn_seconds), 2),
                    "distribution": rnn_dist,
                },
                "lexicon": {
                    "model": "lexicon_baseline_v2",
                    "records": len(lex_indices),
                    "errors": lex_errors,
                    "seconds": round(lex_seconds, 4),
                    "records_per_second": round(len(lex_indices) / max(1e-9, lex_seconds), 2),
                    "distribution": lex_dist,
                },
            },
        }
        _write_ab_report(ab_report_output, ab_report)
    elif args.model_type == "rnn":
        errors, distribution, model_name = _predict_rnn(rows, args.rnn_model_dir, args.rnn_batch_size)
        execution_mode = "rnn_batch"
        is_rnn = True
        used_workers = 1
        used_thresholds = None
    else:
        analyzer = LexiconSentimentAnalyzer(
            positive_threshold=args.positive_threshold,
            negative_threshold=args.negative_threshold,
        )
        if workers <= 1:
            errors, distribution = _predict_single(rows, analyzer)
            execution_mode = "single_batch"
        else:
            errors, distribution = _predict_parallel(rows, analyzer, workers)
            execution_mode = "thread_pool"
        model_name = analyzer.model_name
        is_rnn = False
        used_workers = workers
        used_thresholds = {
            "positive": args.positive_threshold,
            "negative": args.negative_threshold,
        }
        for row in rows:
            row["sentiment_model"] = "lexicon"

    write_jsonl(args.output, rows)

    elapsed = max(1e-9, time.perf_counter() - t0)
    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "records": len(rows),
        "bad_lines_skipped": bad_lines,
        "errors": errors,
        "distribution": distribution,
        "thresholds": used_thresholds,
        "runtime": {
            "execution_mode": execution_mode,
            "workers": used_workers,
            "seconds": round(elapsed, 4),
            "records_per_second": round(len(rows) / elapsed, 2),
            "model": model_name,
            "is_rnn": is_rnn,
        },
        "model_type": "ab" if args.ab_enabled else args.model_type,
    }
    if args.ab_enabled:
        ab_report_output = args.ab_report_output or _default_ab_report_path(args.summary_output)
        summary["ab_test"] = {
            "enabled": True,
            "rnn_ratio": effective_ratio,
            "ratio_source": ratio_source,
            "ratio_config": str(args.ab_ratio_config),
            "report_output": str(ab_report_output),
        }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
