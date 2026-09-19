"""價格預測模組（純 numpy / pandas 實作，無需 TensorFlow）。

設計重點
--------
舊版的「LSTM / GRU / CNN-LSTM」其實只是把動量乘上係數，權重也是寫死的，
既不會學習也無法驗證。這一版改成六個真正可計算、學術上有依據的時間序列模型，
並且用 **walk-forward（滾動起點）回測** 來決定每個模型的權重：

1. `holt_damped`   - 阻尼趨勢指數平滑（Holt's linear + damping），參數用格點搜尋擬合
2. `theta`         - Theta method，M3 競賽的經典強基準
3. `ridge_ar`      - 以落後報酬率 / 動量 / 波動 / RSI 為特徵的 Ridge 自迴歸（閉式解）
4. `knn_analog`    - 歷史相似型態比對（k 近鄰），捕捉非線性的型態重演
5. `drift`         - 隨機漫步 + 漂移（= ARIMA(0,1,0) with drift）
6. `ema_momentum`  - 指數均線動量外推（保留原本的短線視角，但加上阻尼）

每個模型都輸出「未來 h 期的完整路徑」，回測會算出：
    mape                絕對百分誤差平均（越小越好）
    directional_accuracy 方向猜對的比例（越高越好）
    weight              由誤差決定的權重（softmax(-誤差)），會自動偏向近期表現好的模型

最後的 ensemble 是加權平均路徑，並用回測殘差推估 80% 信賴區間。
所有預測都會限制在合理範圍內（依波動度動態調整上下限），避免離譜的外推。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = ["compute_forecast", "MODEL_LABELS"]


MODEL_LABELS: dict[str, str] = {
    "holt_damped": "Holt 阻尼趨勢",
    "theta": "Theta 法",
    "ridge_ar": "Ridge 自迴歸",
    "knn_analog": "歷史型態比對",
    "drift": "漂移隨機漫步",
    "ema_momentum": "EMA 動量",
}

MIN_HISTORY = 30
_EPS = 1e-9


# --------------------------------------------------------------------------- #
# 各別模型：輸入收盤價 numpy 陣列，輸出長度 h 的價格路徑
# --------------------------------------------------------------------------- #
# 指數平滑的權重隨時間指數衰減，超過數百期之前的資料對最終狀態的影響小於 1e-5，
# 但格點搜尋要跑 48 組參數 × 整條序列，資料一長就明顯變慢（2500 點約 0.08 秒／次，
# 加上滾動回測會呼叫 9 次）。因此只用最近 HOLT_FIT_WINDOW 期來擬合與遞推。
HOLT_FIT_WINDOW = 750


def _holt_damped(y: np.ndarray, h: int) -> np.ndarray:
    """阻尼趨勢指數平滑；用小型格點搜尋找出 SSE 最小的 (alpha, beta, phi)。"""
    if len(y) > HOLT_FIT_WINDOW:
        y = y[-HOLT_FIT_WINDOW:]
    best_params = (0.5, 0.1, 0.95)
    best_sse = math.inf
    for alpha in (0.2, 0.4, 0.6, 0.8):
        for beta in (0.05, 0.1, 0.2, 0.3):
            for phi in (0.85, 0.92, 0.98):
                level, trend = float(y[0]), float(y[1] - y[0]) if len(y) > 1 else 0.0
                sse = 0.0
                for value in y[1:]:
                    forecast = level + phi * trend
                    error = value - forecast
                    sse += error * error
                    new_level = alpha * value + (1 - alpha) * forecast
                    trend = beta * (new_level - level) + (1 - beta) * phi * trend
                    level = new_level
                if sse < best_sse:
                    best_sse = sse
                    best_params = (alpha, beta, phi)

    alpha, beta, phi = best_params
    level, trend = float(y[0]), float(y[1] - y[0]) if len(y) > 1 else 0.0
    for value in y[1:]:
        forecast = level + phi * trend
        new_level = alpha * value + (1 - alpha) * forecast
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level

    path = []
    damp_sum = 0.0
    for step in range(1, h + 1):
        damp_sum += phi ** step
        path.append(level + damp_sum * trend)
    return np.asarray(path, dtype=float)


def _theta(y: np.ndarray, h: int) -> np.ndarray:
    """Theta method：線性趨勢的一半 + SES 外推的一半。"""
    n = len(y)
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)

    alpha = 0.3
    level = float(y[0])
    for value in y[1:]:
        level = alpha * value + (1 - alpha) * level

    steps = np.arange(1, h + 1, dtype=float)
    linear = intercept + slope * (n - 1 + steps)
    ses = np.full(h, level, dtype=float)
    # theta=0 的線性成分與 theta=2 的 SES 成分平均（含趨勢補償）
    return 0.5 * linear + 0.5 * (ses + slope * steps * 0.5)


def _fit_ridge(features: np.ndarray, target: np.ndarray, lam: float = 1.0) -> np.ndarray:
    """Ridge 回歸閉式解，含截距項。"""
    design = np.hstack([np.ones((features.shape[0], 1)), features])
    penalty = lam * np.eye(design.shape[1])
    penalty[0, 0] = 0.0  # 不懲罰截距
    gram = design.T @ design + penalty
    try:
        return np.linalg.solve(gram, design.T @ target)
    except np.linalg.LinAlgError:  # pragma: no cover - 極端退化情況
        return np.linalg.lstsq(design, target, rcond=None)[0]


def _ar_features(log_returns: np.ndarray, index: int, lags: int = 5) -> np.ndarray:
    """由落後報酬率組出特徵：lag1..lag5、短中期動量、波動度。"""
    window = log_returns[index - lags: index]
    momentum_5 = float(log_returns[max(0, index - 5): index].sum())
    momentum_10 = float(log_returns[max(0, index - 10): index].sum())
    momentum_20 = float(log_returns[max(0, index - 20): index].sum())
    volatility = float(np.std(log_returns[max(0, index - 20): index]) or 0.0)
    return np.concatenate([window, [momentum_5, momentum_10, momentum_20, volatility]])


def _ridge_ar(y: np.ndarray, h: int, lags: int = 5) -> np.ndarray:
    """對 log 報酬率做 Ridge 自迴歸，再逐步遞推出未來價格。"""
    log_prices = np.log(np.maximum(y, _EPS))
    log_returns = np.diff(log_prices)
    if len(log_returns) < lags + 25:
        return _drift(y, h)

    rows, targets = [], []
    for index in range(lags + 20, len(log_returns)):
        rows.append(_ar_features(log_returns, index, lags))
        targets.append(log_returns[index])

    features = np.asarray(rows, dtype=float)
    target = np.asarray(targets, dtype=float)
    coefficients = _fit_ridge(features, target, lam=1.0)

    working = log_returns.copy()
    current_log_price = float(log_prices[-1])
    path = []
    for _ in range(h):
        feature_row = _ar_features(working, len(working), lags)
        predicted_return = float(np.dot(np.concatenate([[1.0], feature_row]), coefficients))
        # 限制單期報酬率，避免遞推發散
        predicted_return = float(np.clip(predicted_return, -0.1, 0.1))
        current_log_price += predicted_return
        path.append(math.exp(current_log_price))
        working = np.append(working, predicted_return)
    return np.asarray(path, dtype=float)


def _knn_analog(y: np.ndarray, h: int, window: int = 20, neighbours: int = 5) -> np.ndarray:
    """歷史型態比對：找出與「最近 window 期」最相似的歷史片段，取其後續走勢平均。"""
    if len(y) < window + h + 30:
        return _drift(y, h)

    def normalize(segment: np.ndarray) -> np.ndarray:
        base = segment[0] if abs(segment[0]) > _EPS else _EPS
        return segment / base - 1.0

    query = normalize(y[-window:])
    distances: list[tuple[float, np.ndarray]] = []
    for start in range(0, len(y) - window - h):
        candidate = normalize(y[start: start + window])
        distance = float(np.linalg.norm(candidate - query))
        future = y[start + window - 1: start + window - 1 + h + 1]
        if len(future) < h + 1:
            continue
        base = future[0] if abs(future[0]) > _EPS else _EPS
        distances.append((distance, future[1:] / base))

    if not distances:
        return _drift(y, h)

    distances.sort(key=lambda item: item[0])
    top = distances[: min(neighbours, len(distances))]
    weights = np.asarray([1.0 / (distance + 1e-4) for distance, _ in top], dtype=float)
    weights /= weights.sum()
    ratios = np.average(np.vstack([ratio for _, ratio in top]), axis=0, weights=weights)
    return float(y[-1]) * ratios


def _drift(y: np.ndarray, h: int) -> np.ndarray:
    """隨機漫步 + 漂移（以 log 報酬率平均當漂移項）。"""
    log_prices = np.log(np.maximum(y, _EPS))
    log_returns = np.diff(log_prices)
    drift = float(np.mean(log_returns[-60:])) if len(log_returns) else 0.0
    steps = np.arange(1, h + 1, dtype=float)
    return np.exp(log_prices[-1] + drift * steps)


def _ema_momentum(y: np.ndarray, h: int) -> np.ndarray:
    """EMA 快慢線差距當動量，並隨時間阻尼衰減。"""
    series = pd.Series(y)
    ema_fast = series.ewm(span=12, adjust=False).mean().to_numpy()
    ema_slow = series.ewm(span=26, adjust=False).mean().to_numpy()
    momentum = float(ema_fast[-1] - ema_slow[-1])
    base = float(ema_fast[-1])
    path = []
    for step in range(1, h + 1):
        path.append(base + momentum * (1 - 0.85 ** step) / 0.15 * 0.12)
    return np.asarray(path, dtype=float)


MODELS = {
    "holt_damped": _holt_damped,
    "theta": _theta,
    "ridge_ar": _ridge_ar,
    "knn_analog": _knn_analog,
    "drift": _drift,
    "ema_momentum": _ema_momentum,
}


# --------------------------------------------------------------------------- #
# 回測與整合
# --------------------------------------------------------------------------- #
def _bounded_path(path: np.ndarray, latest: float, volatility: float, horizon: int) -> np.ndarray:
    """依波動度限制預測範圍：波動越大容忍度越高，但最多 ±35%。"""
    cap = min(0.35, max(0.06, volatility * math.sqrt(max(horizon, 1)) * 2.2))
    low, high = latest * (1 - cap), latest * (1 + cap)
    return np.clip(np.nan_to_num(path, nan=latest, posinf=high, neginf=low), low, high)


def _safe_predict(name: str, y: np.ndarray, h: int) -> np.ndarray | None:
    try:
        path = np.asarray(MODELS[name](y, h), dtype=float)
    except Exception:  # pragma: no cover - 單一模型失敗不影響其他模型
        return None
    if path.shape != (h,) or not np.all(np.isfinite(path)):
        return None
    return path


def _walk_forward(y: np.ndarray, horizon: int, origins: int = 8) -> tuple[dict[str, dict], list[dict]]:
    """滾動起點回測：每個起點只用該時點以前的資料訓練，再比對真實結果。

    回傳 (各模型的成績, 每個起點的原始預測)；後者用來回測 ensemble 本身。
    """
    scores: dict[str, dict] = {
        name: {"errors": [], "hits": [], "residuals": []} for name in MODELS
    }
    per_origin: list[dict] = []
    step = max(1, horizon // 2)
    usable = len(y) - MIN_HISTORY - horizon
    if usable <= 0:
        return scores, per_origin

    origin_points = []
    cursor = len(y) - horizon
    for _ in range(origins):
        if cursor - MIN_HISTORY < 0:
            break
        origin_points.append(cursor)
        cursor -= step
    origin_points.reverse()

    for origin in origin_points:
        train = y[:origin]
        actual = y[origin: origin + horizon]
        if len(actual) < horizon or len(train) < MIN_HISTORY:
            continue
        last = float(train[-1])
        truth = float(actual[-1])
        origin_record = {"last": last, "truth": truth, "predictions": {}}
        for name in MODELS:
            path = _safe_predict(name, train, horizon)
            if path is None:
                continue
            predicted = float(path[-1])
            origin_record["predictions"][name] = predicted
            scores[name]["errors"].append(abs(predicted - truth) / max(abs(truth), _EPS) * 100.0)
            scores[name]["hits"].append(
                1.0 if np.sign(predicted - last) == np.sign(truth - last) else 0.0
            )
            scores[name]["residuals"].append((predicted - truth) / max(abs(truth), _EPS))
        if origin_record["predictions"]:
            per_origin.append(origin_record)
    return scores, per_origin


def _backtest_ensemble(per_origin: list[dict], weights: dict[str, float]) -> dict:
    """用同一組權重，回測「加權整合」本身的誤差與方向準確率。"""
    errors: list[float] = []
    hits: list[float] = []
    residuals: list[float] = []
    for record in per_origin:
        available = {name: value for name, value in record["predictions"].items() if name in weights}
        total = sum(weights[name] for name in available)
        if not available or total <= 0:
            continue
        blended = sum(value * weights[name] for name, value in available.items()) / total
        truth, last = record["truth"], record["last"]
        errors.append(abs(blended - truth) / max(abs(truth), _EPS) * 100.0)
        hits.append(1.0 if np.sign(blended - last) == np.sign(truth - last) else 0.0)
        residuals.append((blended - truth) / max(abs(truth), _EPS))
    return {"errors": errors, "hits": hits, "residuals": residuals}


def _weights_from_scores(scores: dict[str, dict], available: list[str]) -> dict[str, float]:
    """以回測 MAPE 與方向準確率計算權重（softmax(-成本)）。"""
    costs: dict[str, float] = {}
    for name in available:
        errors = scores.get(name, {}).get("errors", [])
        hits = scores.get(name, {}).get("hits", [])
        if not errors:
            costs[name] = 1.0  # 無回測資料 -> 中性成本
            continue
        mape = float(np.mean(errors))
        hit_rate = float(np.mean(hits)) if hits else 0.5
        # 誤差越小、方向準確率越高，成本越低
        costs[name] = mape * (1.35 - 0.7 * hit_rate)

    if not costs:
        return {}

    values = np.asarray(list(costs.values()), dtype=float)
    scale = float(np.median(values)) or 1.0
    logits = -values / max(scale * 0.55, _EPS)
    logits -= logits.max()
    exp = np.exp(logits)
    weights = exp / exp.sum()
    # 設下限避免單一模型獨大，並重新正規化
    weights = np.maximum(weights, 0.03)
    weights = weights / weights.sum()
    return {name: float(weight) for name, weight in zip(costs.keys(), weights)}


def _confidence(scores: dict[str, dict], weights: dict[str, float]) -> tuple[float, float]:
    """回傳 (相對殘差標準差, 加權方向準確率)。"""
    residuals: list[float] = []
    hit_rates: list[tuple[float, float]] = []
    for name, weight in weights.items():
        entry = scores.get(name, {})
        residuals.extend(entry.get("residuals", []))
        hits = entry.get("hits", [])
        if hits:
            hit_rates.append((float(np.mean(hits)), weight))
    sigma = float(np.std(residuals)) if len(residuals) >= 3 else 0.05
    if hit_rates:
        total_weight = sum(weight for _, weight in hit_rates) or 1.0
        accuracy = sum(rate * weight for rate, weight in hit_rates) / total_weight
    else:
        accuracy = 0.5
    return max(sigma, 0.005), accuracy


def _format_entry(
    key: str,
    latest: float,
    path: np.ndarray,
    scores: dict,
    weight: float,
) -> dict:
    predicted = float(path[-1])
    errors = scores.get("errors", [])
    hits = scores.get("hits", [])
    return {
        "key": key,
        "model": MODEL_LABELS.get(key, key),
        "status": "ready",
        "predicted_price": round(predicted, 2),
        "change_pct": round(((predicted - latest) / latest * 100.0) if latest else 0.0, 2),
        "path": [round(float(value), 2) for value in path],
        "backtest_mape": round(float(np.mean(errors)), 2) if errors else None,
        "directional_accuracy": round(float(np.mean(hits)) * 100.0, 1) if hits else None,
        "weight": round(weight * 100.0, 1),
        "backtest_runs": len(errors),
    }


def compute_forecast(prices: list[dict], horizon: int = 7) -> dict:
    """主入口：輸入價格列表與預測天數，輸出各模型與整合後的預測結果。"""
    horizon = int(max(1, min(60, horizon)))
    if not prices:
        return {"status": "no_data", "horizon_days": horizon, "predictions": {}}

    close = pd.to_numeric(pd.DataFrame(prices)["close"], errors="coerce").dropna()
    y = close.to_numpy(dtype=float)
    if len(y) < MIN_HISTORY:
        return {
            "status": "insufficient_history",
            "horizon_days": horizon,
            "message": f"歷史資料僅 {len(y)} 筆，至少需要 {MIN_HISTORY} 筆才能建模",
            "predictions": {},
        }

    latest = float(y[-1])
    log_returns = np.diff(np.log(np.maximum(y, _EPS)))
    volatility = float(np.std(log_returns[-60:])) if len(log_returns) else 0.02

    scores, per_origin = _walk_forward(y, horizon)
    paths: dict[str, np.ndarray] = {}
    for name in MODELS:
        path = _safe_predict(name, y, horizon)
        if path is None:
            continue
        paths[name] = _bounded_path(path, latest, volatility, horizon)

    if not paths:
        return {"status": "model_failed", "horizon_days": horizon, "predictions": {}}

    weights = _weights_from_scores(scores, list(paths.keys()))
    ensemble_path = np.zeros(horizon, dtype=float)
    for name, path in paths.items():
        ensemble_path += path * weights.get(name, 0.0)
    ensemble_path = _bounded_path(ensemble_path, latest, volatility, horizon)

    ensemble_scores = _backtest_ensemble(per_origin, weights)
    ensemble_mape = round(float(np.mean(ensemble_scores["errors"])), 2) if ensemble_scores["errors"] else None
    if ensemble_scores["residuals"]:
        sigma = max(float(np.std(ensemble_scores["residuals"])), 0.005)
        accuracy = float(np.mean(ensemble_scores["hits"]))
    else:
        sigma, accuracy = _confidence(scores, weights)
    steps = np.arange(1, horizon + 1, dtype=float)
    band = sigma * np.sqrt(steps / max(horizon, 1)) * 1.2816  # 80% 區間
    upper = ensemble_path * (1 + band)
    lower = ensemble_path * (1 - band)

    predictions = {
        name: _format_entry(name, latest, path, scores.get(name, {}), weights.get(name, 0.0))
        for name, path in paths.items()
    }
    predictions = dict(
        sorted(predictions.items(), key=lambda item: -(item[1]["weight"] or 0.0))
    )

    ensemble_price = float(ensemble_path[-1])
    ensemble = {
        "key": "ensemble",
        "model": "加權整合 Ensemble",
        "status": "ready",
        "predicted_price": round(ensemble_price, 2),
        "change_pct": round(((ensemble_price - latest) / latest * 100.0) if latest else 0.0, 2),
        "path": [round(float(value), 2) for value in ensemble_path],
        "upper_band": [round(float(value), 2) for value in upper],
        "lower_band": [round(float(value), 2) for value in lower],
        "directional_accuracy": round(accuracy * 100.0, 1),
        "backtest_mape": ensemble_mape,
        "backtest_runs": len(ensemble_scores["errors"]),
        "confidence_level": 80,
    }

    backtest_runs = max((len(item.get("errors", [])) for item in scores.values()), default=0)
    best_model = min(
        (item for item in predictions.values() if item["backtest_mape"] is not None),
        key=lambda item: item["backtest_mape"],
        default=None,
    )

    return {
        "status": "ready",
        "horizon_days": horizon,
        "latest_price": round(latest, 2),
        "sample_size": int(len(y)),
        "volatility_daily_pct": round(volatility * 100.0, 2),
        "validation": {
            "method": "walk_forward",
            "runs": backtest_runs,
            "best_model": best_model["model"] if best_model else None,
            "best_model_mape": best_model["backtest_mape"] if best_model else None,
            "ensemble_mape": ensemble_mape,
            "weighted_directional_accuracy": round(accuracy * 100.0, 1),
        },
        "ensemble": ensemble,
        "predictions": predictions,
    }
