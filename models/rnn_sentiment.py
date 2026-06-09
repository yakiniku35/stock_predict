from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

LABEL_TO_ID = {
    "negative": 0,
    "neutral": 1,
    "positive": 2,
}

ID_TO_LABEL = {v: k for k, v in LABEL_TO_ID.items()}
ACTIVE_MODEL_FILE = "active_model.json"


@dataclass
class RNNSentimentConfig:
    vocab_size: int = 20000
    max_len: int = 256
    embedding_dim: int = 96
    lstm_units: int = 64


def build_text(record: dict) -> str:
    headline = str(record.get("headline") or "")
    content = str(record.get("content") or "")
    return f"{headline} {content}".strip()


def labels_to_ids(labels: Iterable[str]) -> np.ndarray:
    encoded = [LABEL_TO_ID.get(str(label).lower(), LABEL_TO_ID["neutral"]) for label in labels]
    return np.asarray(encoded, dtype=np.int32)


def ids_to_labels(ids: Iterable[int]) -> list[str]:
    return [ID_TO_LABEL.get(int(i), "neutral") for i in ids]


def load_jsonl(path: Path) -> tuple[list[dict], int]:
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


def _has_artifacts(model_dir: Path) -> bool:
    return all((model_dir / filename).exists() for filename in ["model.keras", "tokenizer.json", "meta.json"])


def _resolve_pointer_candidate(registry_dir: Path, active_dir: str) -> Path | None:
    candidate = Path(active_dir)
    if candidate.is_absolute():
        return candidate if _has_artifacts(candidate) else None

    for anchor in [registry_dir, *registry_dir.parents]:
        resolved = (anchor / candidate).resolve()
        if _has_artifacts(resolved):
            return resolved
    return None


def resolve_model_dir(model_dir: Path) -> Path:
    model_dir = model_dir.resolve()
    if _has_artifacts(model_dir):
        return model_dir

    pointer_path = model_dir / ACTIVE_MODEL_FILE
    if pointer_path.exists():
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
        active_dir = payload.get("active_model_dir")
        if not active_dir:
            raise FileNotFoundError(f"Invalid {ACTIVE_MODEL_FILE}: missing active_model_dir")
        candidate = _resolve_pointer_candidate(model_dir, str(active_dir))
        if candidate is not None:
            return candidate
        raise FileNotFoundError(f"Active model path has no artifacts: {active_dir}")

    raise FileNotFoundError(
        f"No RNN artifacts found in {model_dir}. Provide artifact folder or registry with {ACTIVE_MODEL_FILE}."
    )


def get_active_model(registry_dir: Path) -> Path:
    return resolve_model_dir(registry_dir)


def set_active_model(registry_dir: Path, model_dir: Path) -> Path:
    registry_dir = registry_dir.resolve()
    model_dir = resolve_model_dir(model_dir)
    registry_dir.mkdir(parents=True, exist_ok=True)

    try:
        relative = model_dir.relative_to(registry_dir)
        stored_path = str(relative)
    except ValueError:
        stored_path = str(model_dir)

    payload = {
        "active_model_dir": stored_path,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "is_rnn": True,
    }
    (registry_dir / ACTIVE_MODEL_FILE).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return model_dir


def _import_tf():
    import tensorflow as tf
    from tensorflow import keras

    return tf, keras


def create_tokenizer(texts: list[str], vocab_size: int):
    _, keras = _import_tf()
    tokenizer = keras.preprocessing.text.Tokenizer(num_words=vocab_size, oov_token="[OOV]")
    tokenizer.fit_on_texts(texts)
    return tokenizer


def texts_to_padded(tokenizer, texts: list[str], max_len: int) -> np.ndarray:
    _, keras = _import_tf()
    sequences = tokenizer.texts_to_sequences(texts)
    return keras.preprocessing.sequence.pad_sequences(
        sequences,
        maxlen=max_len,
        padding="post",
        truncating="post",
        value=0,
    )


def build_lstm_model(config: RNNSentimentConfig):
    _, keras = _import_tf()
    inputs = keras.Input(shape=(config.max_len,), dtype="int32")
    x = keras.layers.Embedding(
        input_dim=config.vocab_size,
        output_dim=config.embedding_dim,
        mask_zero=True,
    )(inputs)
    x = keras.layers.Bidirectional(keras.layers.LSTM(config.lstm_units))(x)
    x = keras.layers.Dropout(0.25)(x)
    x = keras.layers.Dense(64, activation="relu")(x)
    outputs = keras.layers.Dense(3, activation="softmax")(x)

    model = keras.Model(inputs=inputs, outputs=outputs, name="bilstm_sentiment")
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-3),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


def score_from_probs(probs: np.ndarray) -> np.ndarray:
    # Map probability distribution to [-100, 100] by positive - negative confidence.
    positive = probs[:, LABEL_TO_ID["positive"]]
    negative = probs[:, LABEL_TO_ID["negative"]]
    scores = (positive - negative) * 100.0
    return np.clip(scores, -100.0, 100.0)


def save_artifacts(model, tokenizer, config: RNNSentimentConfig, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    model_path = output_dir / "model.keras"
    tokenizer_path = output_dir / "tokenizer.json"
    meta_path = output_dir / "meta.json"

    model.save(model_path)
    tokenizer_path.write_text(tokenizer.to_json(), encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "is_rnn": True,
                "model_name": "bilstm_sentiment_v1",
                "vocab_size": config.vocab_size,
                "max_len": config.max_len,
                "embedding_dim": config.embedding_dim,
                "lstm_units": config.lstm_units,
                "labels": ID_TO_LABEL,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return output_dir


def load_artifacts(model_dir: Path):
    _, keras = _import_tf()

    model_dir = resolve_model_dir(model_dir)

    model_path = model_dir / "model.keras"
    tokenizer_path = model_dir / "tokenizer.json"
    meta_path = model_dir / "meta.json"

    if not model_path.exists() or not tokenizer_path.exists() or not meta_path.exists():
        raise FileNotFoundError(
            f"Missing RNN artifacts in {model_dir}. Required: model.keras, tokenizer.json, meta.json"
        )

    model = keras.models.load_model(model_path)
    tokenizer = keras.preprocessing.text.tokenizer_from_json(tokenizer_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return model, tokenizer, meta


def predict_many(model, tokenizer, texts: list[str], max_len: int, batch_size: int = 128) -> list[dict]:
    if not texts:
        return []

    x = texts_to_padded(tokenizer, texts, max_len=max_len)
    probs = model.predict(x, batch_size=max(1, batch_size), verbose=0)

    probs = np.asarray(probs)
    label_ids = np.argmax(probs, axis=1)
    labels = ids_to_labels(label_ids.tolist())
    scores = score_from_probs(probs)

    results: list[dict] = []
    for label, score in zip(labels, scores.tolist()):
        results.append({
            "sentiment_label": label,
            "sentiment_score": round(float(score), 2),
        })
    return results
