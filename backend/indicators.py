"""技術指標計算模組。

本模組只依賴 pandas / numpy，統一給 `api/index.py`、`backend/app.py` 與訊號引擎使用，
避免前後端各自重算而產生不一致的結果。

對外主要函式：
    compute_indicators(prices)  -> dict: 圖表用的完整序列
    latest_snapshot(prices, indicators) -> dict: 最新一根 K 棒的指標快照（訊號引擎用）
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "EMPTY_INDICATORS",
    "compute_indicators",
    "latest_snapshot",
    "to_float_or_none",
]


EMPTY_INDICATORS: dict = {
    "sma": {"sma5": [], "sma20": [], "sma60": [], "sma120": [], "sma240": []},
    "ema": {"ema12": [], "ema26": []},
    "bb": {"upper": [], "middle": [], "lower": [], "bandwidth": []},
    "macd": {"macd": [], "signal": [], "histogram": []},
    "kd": {"k": [], "d": []},
    "rsi": [],
    "bias": [],
    "ad": [],
    "atr": [],
    "obv": [],
    "volume_ma20": [],
}


def to_float_or_none(value) -> float | None:
    """把任何值安全轉成 float；NaN/inf/無法轉換皆回傳 None。"""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric


def _series_to_list(series: pd.Series, digits: int = 4) -> list[float | None]:
    output: list[float | None] = []
    for value in series.tolist():
        numeric = to_float_or_none(value)
        output.append(round(numeric, digits) if numeric is not None else None)
    return output


def _last_valid(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None


def _nth_last_valid(values: list[float | None], n: int) -> float | None:
    """取得倒數第 n 個有效值（n=0 為最後一個）。"""
    seen = 0
    for value in reversed(values):
        if value is None:
            continue
        if seen == n:
            return value
        seen += 1
    return None


def prices_to_frame(prices: list[dict]) -> pd.DataFrame:
    """把 API 的價格列表轉成數值化的 DataFrame。"""
    df = pd.DataFrame(prices)
    for column in ("open", "high", "low", "close", "volume"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            df[column] = np.nan
    df["volume"] = df["volume"].fillna(0.0)
    return df


def compute_indicators(prices: list[dict]) -> dict:
    """計算全部技術指標序列，長度與 prices 相同，不足期數的位置為 None。"""
    if not prices:
        return {key: (value.copy() if isinstance(value, dict) else list(value))
                for key, value in EMPTY_INDICATORS.items()}

    df = prices_to_frame(prices)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    sma5 = close.rolling(window=5, min_periods=5).mean()
    sma20 = close.rolling(window=20, min_periods=20).mean()
    sma60 = close.rolling(window=60, min_periods=60).mean()
    sma120 = close.rolling(window=120, min_periods=120).mean()
    sma240 = close.rolling(window=240, min_periods=240).mean()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal

    # RSI 使用 Wilder 平滑（與看盤軟體一致），比單純移動平均更標準
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = losses.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0).where(avg_gain.notna())

    low9 = low.rolling(window=9, min_periods=9).min()
    high9 = high.rolling(window=9, min_periods=9).max()
    rsv = ((close - low9) / (high9 - low9).replace(0.0, np.nan)) * 100.0
    k = rsv.ewm(alpha=1 / 3, adjust=False, min_periods=9).mean()
    d = k.ewm(alpha=1 / 3, adjust=False, min_periods=9).mean()

    bb_mid = sma20
    bb_std = close.rolling(window=20, min_periods=20).std()
    bb_upper = bb_mid + (bb_std * 2.0)
    bb_lower = bb_mid - (bb_std * 2.0)
    bb_bandwidth = ((bb_upper - bb_lower) / bb_mid.replace(0.0, np.nan)) * 100.0

    bias20 = ((close - sma20) / sma20.replace(0.0, np.nan)) * 100.0

    mfm = ((close - low) - (high - close)) / (high - low).replace(0.0, np.nan)
    mfm = mfm.fillna(0.0)
    ad = (mfm * volume).cumsum()

    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    direction = np.sign(close.diff().fillna(0.0))
    obv = (direction * volume).cumsum()
    volume_ma20 = volume.rolling(window=20, min_periods=5).mean()

    return {
        "sma": {
            "sma5": _series_to_list(sma5, digits=2),
            "sma20": _series_to_list(sma20, digits=2),
            "sma60": _series_to_list(sma60, digits=2),
            "sma120": _series_to_list(sma120, digits=2),
            "sma240": _series_to_list(sma240, digits=2),
        },
        "ema": {
            "ema12": _series_to_list(ema12, digits=2),
            "ema26": _series_to_list(ema26, digits=2),
        },
        "bb": {
            "upper": _series_to_list(bb_upper, digits=2),
            "middle": _series_to_list(bb_mid, digits=2),
            "lower": _series_to_list(bb_lower, digits=2),
            "bandwidth": _series_to_list(bb_bandwidth, digits=2),
        },
        "macd": {
            "macd": _series_to_list(macd_line),
            "signal": _series_to_list(macd_signal),
            "histogram": _series_to_list(macd_hist),
        },
        "kd": {
            "k": _series_to_list(k, digits=2),
            "d": _series_to_list(d, digits=2),
        },
        "rsi": _series_to_list(rsi, digits=2),
        "bias": _series_to_list(bias20, digits=2),
        "ad": _series_to_list(ad, digits=2),
        "atr": _series_to_list(atr, digits=2),
        "obv": _series_to_list(obv, digits=2),
        "volume_ma20": _series_to_list(volume_ma20, digits=2),
    }


def latest_snapshot(prices: list[dict], indicators: dict) -> dict:
    """整理訊號引擎需要的「最新值 + 前一值」快照。"""
    if not prices:
        return {}

    df = prices_to_frame(prices)
    close = df["close"].dropna()
    if close.empty:
        return {}

    latest_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else latest_close

    window52 = close.tail(250)
    high_52w = float(window52.max())
    low_52w = float(window52.min())

    returns = close.pct_change().dropna()
    volatility_20 = float(returns.tail(20).std() * np.sqrt(252) * 100) if len(returns) >= 5 else None

    volume = df["volume"].fillna(0.0)
    latest_volume = float(volume.iloc[-1])
    volume_ma = _last_valid(indicators.get("volume_ma20", [])) or 0.0

    macd = indicators.get("macd", {})
    kd = indicators.get("kd", {})
    sma = indicators.get("sma", {})
    bb = indicators.get("bb", {})

    return {
        "close": latest_close,
        "prev_close": prev_close,
        "change_pct": ((latest_close - prev_close) / prev_close * 100.0) if prev_close else 0.0,
        "rsi": _last_valid(indicators.get("rsi", [])),
        "rsi_prev": _nth_last_valid(indicators.get("rsi", []), 1),
        "macd": _last_valid(macd.get("macd", [])),
        "macd_signal": _last_valid(macd.get("signal", [])),
        "macd_hist": _last_valid(macd.get("histogram", [])),
        "macd_hist_prev": _nth_last_valid(macd.get("histogram", []), 1),
        "k": _last_valid(kd.get("k", [])),
        "d": _last_valid(kd.get("d", [])),
        "k_prev": _nth_last_valid(kd.get("k", []), 1),
        "d_prev": _nth_last_valid(kd.get("d", []), 1),
        "sma5": _last_valid(sma.get("sma5", [])),
        "sma20": _last_valid(sma.get("sma20", [])),
        "sma60": _last_valid(sma.get("sma60", [])),
        "sma120": _last_valid(sma.get("sma120", [])),
        "sma20_prev": _nth_last_valid(sma.get("sma20", []), 1),
        "bb_upper": _last_valid(bb.get("upper", [])),
        "bb_middle": _last_valid(bb.get("middle", [])),
        "bb_lower": _last_valid(bb.get("lower", [])),
        "bb_bandwidth": _last_valid(bb.get("bandwidth", [])),
        "bias": _last_valid(indicators.get("bias", [])),
        "atr": _last_valid(indicators.get("atr", [])),
        "obv": _last_valid(indicators.get("obv", [])),
        "obv_prev": _nth_last_valid(indicators.get("obv", []), 5),
        "ad": _last_valid(indicators.get("ad", [])),
        "ad_prev": _nth_last_valid(indicators.get("ad", []), 5),
        "volume": latest_volume,
        "volume_ma20": volume_ma,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "position_52w": ((latest_close - low_52w) / (high_52w - low_52w) * 100.0)
        if high_52w > low_52w
        else 50.0,
        "volatility_annualized": volatility_20,
        "sample_size": int(len(close)),
    }
