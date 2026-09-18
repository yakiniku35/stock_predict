"""風險報酬指標、定期定額試算與多標的比較。

全部都是純函式（輸入價格列表、輸出數字），方便測試也方便重用：

    risk_metrics()      年化報酬、年化波動、最大回撤、夏普值、正報酬月份比例…
    beta_vs_benchmark() 與大盤（或任一標的）的 Beta 與相關係數
    simulate_dca()      定期定額試算（可含配息再投入）
    normalize_series()  多標的比較用的「以第一天為 100」報酬曲線
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

__all__ = [
    "risk_metrics",
    "beta_vs_benchmark",
    "simulate_dca",
    "normalize_series",
    "PERIODS_PER_YEAR",
    "DCA_UNIT_AMOUNT",
]

# 以交易日計算年化；intraday 的資料則用該 interval 的估計值
PERIODS_PER_YEAR = {
    "1d": 252, "5d": 50, "1wk": 52, "1mo": 12, "3mo": 4,
    "1h": 252 * 6, "60m": 252 * 6, "90m": 252 * 4,
    "30m": 252 * 13, "15m": 252 * 26, "5m": 252 * 78, "1m": 252 * 390,
}

# 定期定額用「單位金額」試算，前端只要乘上使用者輸入的金額即可（結果與金額成正比）
DCA_UNIT_AMOUNT = 1000.0
RISK_FREE_RATE = 0.015  # 約略的無風險利率，用於夏普值


def _close_series(prices: list[dict]) -> pd.Series:
    frame = pd.DataFrame(prices)
    closes = pd.to_numeric(frame["close"], errors="coerce")
    closes.index = frame["date"]
    return closes.dropna()


def _safe_round(value, digits: int = 2):
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def max_drawdown(closes: np.ndarray) -> dict:
    """最大回撤：從波段高點到之後最低點的最大跌幅。"""
    if len(closes) < 2:
        return {"pct": 0.0, "peak_index": 0, "trough_index": 0}

    running_peak = np.maximum.accumulate(closes)
    drawdowns = (closes - running_peak) / running_peak
    trough_index = int(np.argmin(drawdowns))
    peak_index = int(np.argmax(closes[: trough_index + 1])) if trough_index > 0 else 0
    return {
        "pct": float(drawdowns[trough_index] * 100.0),
        "peak_index": peak_index,
        "trough_index": trough_index,
    }


def risk_metrics(prices: list[dict], interval: str = "1d") -> dict:
    """計算一段期間的報酬與風險指標。"""
    if not prices or len(prices) < 5:
        return {"status": "insufficient_data"}

    closes = _close_series(prices)
    values = closes.to_numpy(dtype=float)
    if len(values) < 5:
        return {"status": "insufficient_data"}

    periods = PERIODS_PER_YEAR.get(interval, 252)
    returns = np.diff(values) / values[:-1]
    total_return = (values[-1] / values[0] - 1.0) * 100.0
    years = max(len(values) / periods, 1e-6)

    annualized_return = ((values[-1] / values[0]) ** (1 / years) - 1.0) * 100.0
    annualized_vol = float(np.std(returns, ddof=1) * math.sqrt(periods) * 100.0) if len(returns) > 1 else 0.0
    sharpe = ((annualized_return / 100.0 - RISK_FREE_RATE) / (annualized_vol / 100.0)) if annualized_vol > 0 else None

    downside = returns[returns < 0]
    downside_vol = float(np.std(downside, ddof=1) * math.sqrt(periods) * 100.0) if len(downside) > 1 else 0.0
    sortino = ((annualized_return / 100.0 - RISK_FREE_RATE) / (downside_vol / 100.0)) if downside_vol > 0 else None

    drawdown = max_drawdown(values)
    dates = list(closes.index)
    positive_ratio = float((returns > 0).mean() * 100.0) if len(returns) else 0.0

    # 以月為單位統計勝率（日線以上才有意義）
    monthly_win_rate = None
    try:
        monthly = closes.copy()
        monthly.index = pd.to_datetime(list(closes.index), errors="coerce")
        monthly = monthly.dropna()
        if len(monthly) > 40:
            monthly_returns = monthly.resample("ME").last().pct_change().dropna()
            if len(monthly_returns) >= 3:
                monthly_win_rate = float((monthly_returns > 0).mean() * 100.0)
    except Exception:
        monthly_win_rate = None

    return {
        "status": "ready",
        "sample_size": int(len(values)),
        "start_date": dates[0],
        "end_date": dates[-1],
        "start_price": _safe_round(values[0]),
        "end_price": _safe_round(values[-1]),
        "total_return_pct": _safe_round(total_return),
        "annualized_return_pct": _safe_round(annualized_return),
        "annualized_volatility_pct": _safe_round(annualized_vol),
        "sharpe_ratio": _safe_round(sharpe),
        "sortino_ratio": _safe_round(sortino),
        "max_drawdown_pct": _safe_round(drawdown["pct"]),
        "max_drawdown_peak_date": dates[drawdown["peak_index"]],
        "max_drawdown_trough_date": dates[drawdown["trough_index"]],
        "positive_period_ratio_pct": _safe_round(positive_ratio, 1),
        "monthly_win_rate_pct": _safe_round(monthly_win_rate, 1),
        "best_period_pct": _safe_round(float(np.max(returns) * 100.0)) if len(returns) else None,
        "worst_period_pct": _safe_round(float(np.min(returns) * 100.0)) if len(returns) else None,
        "risk_free_rate_pct": RISK_FREE_RATE * 100,
    }


def beta_vs_benchmark(prices: list[dict], benchmark_prices: list[dict]) -> dict | None:
    """以共同日期計算 Beta 與相關係數（衡量跟大盤的連動程度）。"""
    if not prices or not benchmark_prices:
        return None

    target = _close_series(prices)
    benchmark = _close_series(benchmark_prices)
    joined = pd.concat([target, benchmark], axis=1, join="inner").dropna()
    if len(joined) < 20:
        return None

    target_returns = joined.iloc[:, 0].pct_change().dropna().to_numpy(dtype=float)
    benchmark_returns = joined.iloc[:, 1].pct_change().dropna().to_numpy(dtype=float)
    if len(target_returns) < 20:
        return None

    variance = float(np.var(benchmark_returns, ddof=1))
    if variance <= 0:
        return None

    covariance = float(np.cov(target_returns, benchmark_returns, ddof=1)[0][1])
    correlation = float(np.corrcoef(target_returns, benchmark_returns)[0][1])
    return {
        "beta": _safe_round(covariance / variance),
        "correlation": _safe_round(correlation),
        "overlap_days": int(len(joined)),
    }


def simulate_dca(prices: list[dict], dividends: list[dict] | None = None,
                 amount: float = DCA_UNIT_AMOUNT, reinvest_dividends: bool = True) -> dict:
    """定期定額試算：每個月的第一個交易日固定投入,計算目前價值。

    * 以「零股 / 可買小數股」計算，實務上會有整股限制，屬於示意性質。
    * `dividends` 是 `[{"date": ..., "amount": ...}]`（每股現金股利）。
    """
    if not prices or len(prices) < 20:
        return {"status": "insufficient_data"}

    frame = pd.DataFrame(prices)
    frame["parsed_date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["parsed_date"]).sort_values("parsed_date")
    if frame.empty:
        return {"status": "insufficient_data"}

    # 每個月的第一個交易日
    frame["month"] = frame["parsed_date"].dt.to_period("M")
    buy_days = frame.groupby("month", as_index=False).first()
    if len(buy_days) < 2:
        return {"status": "insufficient_data"}

    dividend_events: list[tuple[pd.Timestamp, float]] = []
    for record in (dividends or []):
        try:
            timestamp = pd.Timestamp(record["date"])
            value = float(record["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        if value > 0:
            dividend_events.append((timestamp, value))
    dividend_events.sort(key=lambda item: item[0])

    shares = 0.0
    invested = 0.0
    dividend_cash = 0.0
    dividend_total = 0.0
    dividend_index = 0
    history: list[dict] = []

    for _, row in buy_days.iterrows():
        current_date = row["parsed_date"]
        price = float(row["close"])
        if price <= 0:
            continue

        # 先結算這個月之前發生的配息
        while dividend_index < len(dividend_events) and dividend_events[dividend_index][0] <= current_date:
            _, per_share = dividend_events[dividend_index]
            payout = shares * per_share
            dividend_total += payout
            if reinvest_dividends and payout > 0:
                shares += payout / price
            else:
                dividend_cash += payout
            dividend_index += 1

        shares += amount / price
        invested += amount
        history.append({
            "date": current_date.strftime("%Y-%m-%d"),
            "invested": round(invested, 2),
            "value": round(shares * price + dividend_cash, 2),
        })

    if invested <= 0:
        return {"status": "insufficient_data"}

    # 結算期末之前剩餘的配息
    final_price = float(frame.iloc[-1]["close"])
    while dividend_index < len(dividend_events):
        _, per_share = dividend_events[dividend_index]
        payout = shares * per_share
        dividend_total += payout
        if reinvest_dividends and payout > 0:
            shares += payout / final_price
        else:
            dividend_cash += payout
        dividend_index += 1

    final_value = shares * final_price + dividend_cash
    months = len(history)
    years = max(months / 12.0, 1e-6)
    total_return_pct = (final_value / invested - 1.0) * 100.0
    annualized_pct = ((final_value / invested) ** (1 / years) - 1.0) * 100.0

    # 一次全押（Lump sum）對照組
    first_price = float(buy_days.iloc[0]["close"])
    lump_sum_value = (invested / first_price) * final_price if first_price > 0 else None

    return {
        "status": "ready",
        "unit_amount": amount,
        "months": months,
        "years": round(years, 2),
        "start_date": history[0]["date"],
        "end_date": frame.iloc[-1]["parsed_date"].strftime("%Y-%m-%d"),
        "invested": _safe_round(invested),
        "final_value": _safe_round(final_value),
        "profit": _safe_round(final_value - invested),
        "total_return_pct": _safe_round(total_return_pct),
        "annualized_return_pct": _safe_round(annualized_pct),
        "shares": _safe_round(shares, 4),
        "dividend_total": _safe_round(dividend_total),
        "dividend_reinvested": reinvest_dividends,
        "average_cost": _safe_round(invested / shares) if shares > 0 else None,
        "final_price": _safe_round(final_price),
        "lump_sum_value": _safe_round(lump_sum_value),
        "history": history,
    }


def normalize_series(prices: list[dict], base: float = 100.0) -> dict:
    """把價格序列轉成「第一天 = 100」的相對走勢，供多標的比較。"""
    if not prices:
        return {"dates": [], "values": []}

    closes = _close_series(prices)
    values = closes.to_numpy(dtype=float)
    if len(values) == 0 or values[0] <= 0:
        return {"dates": [], "values": []}

    normalized = values / values[0] * base
    return {
        "dates": list(closes.index),
        "values": [round(float(value), 2) for value in normalized],
    }
