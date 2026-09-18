"""指標自動判讀引擎。

把技術指標、新聞情緒與模型預測，轉成「人看得懂的繁體中文說明」。

輸出結構（給前端的「市場判讀」面板）：
    score        -100 ~ +100 的綜合分數
    stance       bullish / slightly_bullish / neutral / slightly_bearish / bearish
    stance_label 偏多 / 偏空 …（中文）
    headline     一句話結論
    summary      一段完整敘述（引用實際數值）
    signals      每個指標的判讀：方向、強度、白話說明
    action_hint  操作提示；risk_note 風險提醒；disclaimer 免責聲明
"""

from __future__ import annotations

__all__ = ["analyze", "STANCE_LABELS"]


STANCE_LABELS: dict[str, str] = {
    "bullish": "偏多",
    "slightly_bullish": "偏多（力道溫和）",
    "neutral": "中性",
    "slightly_bearish": "偏空（力道溫和）",
    "bearish": "偏空",
}

_DIRECTION_LABELS = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}

# 每個指標在綜合分數中的比重
_WEIGHTS: dict[str, float] = {
    "trend": 1.6,
    "rsi": 1.0,
    "macd": 1.3,
    "kd": 0.9,
    "bollinger": 0.9,
    "bias": 0.7,
    "volume": 0.9,
    "position_52w": 0.7,
    "volatility": 0.5,
    "sentiment": 1.1,
    "forecast": 1.2,
}

DISCLAIMER = "以上為程式依公開資料自動計算的技術面判讀，僅供學習與參考，不構成任何投資建議；投資有風險，請自行評估。"


def _fmt(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "--"
    return f"{value:.{digits}f}{suffix}"


def _signal(key: str, name: str, stance: str, strength: float, text: str,
            value_text: str = "") -> dict:
    return {
        "key": key,
        "name": name,
        "stance": stance,
        "stance_label": _DIRECTION_LABELS.get(stance, "中性"),
        "strength": int(max(0, min(100, round(strength)))),
        "value_text": value_text,
        "text": text,
    }


# --------------------------------------------------------------------------- #
# 各指標判讀
# --------------------------------------------------------------------------- #
def _trend_signal(snap: dict) -> dict | None:
    close = snap.get("close")
    sma5, sma20, sma60 = snap.get("sma5"), snap.get("sma20"), snap.get("sma60")
    if close is None or sma20 is None:
        return None

    above20 = close > sma20
    value_text = f"收盤 {_fmt(close)}／20MA {_fmt(sma20)}"

    if sma5 is not None and sma60 is not None:
        if sma5 > sma20 > sma60 and above20:
            return _signal("trend", "均線結構", "bullish", 88,
                           "5日、20日、60日均線呈現多頭排列，股價站上所有均線，中短期趨勢向上。", value_text)
        if sma5 < sma20 < sma60 and not above20:
            return _signal("trend", "均線結構", "bearish", 88,
                           "5日、20日、60日均線呈現空頭排列，股價位於均線之下，中短期趨勢向下。", value_text)

    rising20 = (snap.get("sma20_prev") is not None and sma20 > snap["sma20_prev"])
    if above20 and rising20:
        return _signal("trend", "均線結構", "bullish", 65,
                       "股價站在 20 日均線之上且均線仍在上彎，短期趨勢偏多但尚未形成完整多頭排列。", value_text)
    if not above20 and not rising20:
        return _signal("trend", "均線結構", "bearish", 65,
                       "股價跌破 20 日均線且均線下彎，短期趨勢轉弱。", value_text)
    return _signal("trend", "均線結構", "neutral", 40,
                   "股價在 20 日均線附近震盪，多空方向還不明確。", value_text)


def _rsi_signal(snap: dict) -> dict | None:
    rsi = snap.get("rsi")
    if rsi is None:
        return None
    value_text = f"RSI(14) {_fmt(rsi, 1)}"
    if rsi >= 80:
        return _signal("rsi", "RSI 相對強弱", "bearish", 75,
                       f"RSI 來到 {rsi:.1f}，進入嚴重超買區，短線追高風險升高，容易出現回檔。", value_text)
    if rsi >= 70:
        return _signal("rsi", "RSI 相對強弱", "bearish", 55,
                       f"RSI 為 {rsi:.1f}，已在超買區；動能雖強，但短線過熱需留意。", value_text)
    if rsi <= 20:
        return _signal("rsi", "RSI 相對強弱", "bullish", 75,
                       f"RSI 僅 {rsi:.1f}，屬於嚴重超賣，有機會出現技術性反彈。", value_text)
    if rsi <= 30:
        return _signal("rsi", "RSI 相對強弱", "bullish", 55,
                       f"RSI 為 {rsi:.1f}，落在超賣區，賣壓可能接近尾聲。", value_text)
    if rsi >= 55:
        return _signal("rsi", "RSI 相對強弱", "bullish", 45,
                       f"RSI 為 {rsi:.1f}，位於中性偏強區間，買方力道略佔上風。", value_text)
    if rsi <= 45:
        return _signal("rsi", "RSI 相對強弱", "bearish", 45,
                       f"RSI 為 {rsi:.1f}，位於中性偏弱區間，賣方力道略大。", value_text)
    return _signal("rsi", "RSI 相對強弱", "neutral", 30,
                   f"RSI 為 {rsi:.1f}，多空力道大致均衡。", value_text)


def _macd_signal(snap: dict) -> dict | None:
    macd, signal_line = snap.get("macd"), snap.get("macd_signal")
    hist, hist_prev = snap.get("macd_hist"), snap.get("macd_hist_prev")
    if macd is None or signal_line is None or hist is None:
        return None

    value_text = f"MACD {_fmt(macd)}／訊號線 {_fmt(signal_line)}"
    crossed_up = hist_prev is not None and hist_prev <= 0 < hist
    crossed_down = hist_prev is not None and hist_prev >= 0 > hist

    if crossed_up:
        return _signal("macd", "MACD 動能", "bullish", 85,
                       "MACD 剛完成黃金交叉（柱狀體由負轉正），動能由空翻多，是偏多的轉折訊號。", value_text)
    if crossed_down:
        return _signal("macd", "MACD 動能", "bearish", 85,
                       "MACD 剛出現死亡交叉（柱狀體由正轉負），動能轉弱，需提防續跌。", value_text)
    if hist > 0:
        expanding = hist_prev is not None and hist > hist_prev
        return _signal("macd", "MACD 動能", "bullish", 70 if expanding else 50,
                       "MACD 柱狀體為正" + ("且持續放大，上漲動能仍在增強。" if expanding else "但已開始收斂，上攻力道略為減弱。"),
                       value_text)
    expanding = hist_prev is not None and hist < hist_prev
    return _signal("macd", "MACD 動能", "bearish", 70 if expanding else 50,
                   "MACD 柱狀體為負" + ("且負值持續擴大，下跌動能增強。" if expanding else "但負值開始收斂，下跌力道有趨緩跡象。"),
                   value_text)


def _kd_signal(snap: dict) -> dict | None:
    k, d = snap.get("k"), snap.get("d")
    if k is None or d is None:
        return None
    k_prev, d_prev = snap.get("k_prev"), snap.get("d_prev")
    value_text = f"K {_fmt(k, 1)}／D {_fmt(d, 1)}"

    golden = k_prev is not None and d_prev is not None and k_prev <= d_prev and k > d
    dead = k_prev is not None and d_prev is not None and k_prev >= d_prev and k < d

    if golden and k < 50:
        return _signal("kd", "KD 隨機指標", "bullish", 80,
                       f"KD 在低檔（K={k:.1f}）出現黃金交叉，是短線轉強的訊號。", value_text)
    if dead and k > 50:
        return _signal("kd", "KD 隨機指標", "bearish", 80,
                       f"KD 在高檔（K={k:.1f}）出現死亡交叉，短線容易轉弱。", value_text)
    if k >= 80 and d >= 80:
        return _signal("kd", "KD 隨機指標", "bearish", 60,
                       f"K、D 值皆在 80 以上（K={k:.1f}），進入高檔鈍化區，追價風險提高。", value_text)
    if k <= 20 and d <= 20:
        return _signal("kd", "KD 隨機指標", "bullish", 60,
                       f"K、D 值皆在 20 以下（K={k:.1f}），落入低檔區，反彈機會增加。", value_text)
    if k > d:
        return _signal("kd", "KD 隨機指標", "bullish", 45,
                       f"K 值（{k:.1f}）位於 D 值（{d:.1f}）之上，短線仍由買方主導。", value_text)
    return _signal("kd", "KD 隨機指標", "bearish", 45,
                   f"K 值（{k:.1f}）低於 D 值（{d:.1f}），短線仍由賣方主導。", value_text)


def _bollinger_signal(snap: dict) -> dict | None:
    close = snap.get("close")
    upper, middle, lower = snap.get("bb_upper"), snap.get("bb_middle"), snap.get("bb_lower")
    if None in (close, upper, middle, lower) or upper <= lower:
        return None

    percent_b = (close - lower) / (upper - lower) * 100.0
    bandwidth = snap.get("bb_bandwidth")
    value_text = f"%B {percent_b:.0f}%／帶寬 {_fmt(bandwidth, 1, '%')}"

    if percent_b >= 100:
        return _signal("bollinger", "布林通道", "bearish", 65,
                       "股價突破布林上軌，短線明顯超漲，過去多半會先回到通道內整理。", value_text)
    if percent_b <= 0:
        return _signal("bollinger", "布林通道", "bullish", 65,
                       "股價跌破布林下軌，屬於短線超跌，常見技術性反彈。", value_text)
    if bandwidth is not None and bandwidth < 8:
        return _signal("bollinger", "布林通道", "neutral", 55,
                       f"布林帶寬僅 {bandwidth:.1f}%，通道明顯收窄，通常代表波動壓縮、即將選擇方向。", value_text)
    if percent_b >= 70:
        return _signal("bollinger", "布林通道", "bullish", 50,
                       f"股價位於通道上半部（%B={percent_b:.0f}%），走勢相對強勢。", value_text)
    if percent_b <= 30:
        return _signal("bollinger", "布林通道", "bearish", 50,
                       f"股價位於通道下半部（%B={percent_b:.0f}%），走勢相對弱勢。", value_text)
    return _signal("bollinger", "布林通道", "neutral", 30,
                   f"股價在布林通道中軌附近（%B={percent_b:.0f}%），區間整理。", value_text)


def _bias_signal(snap: dict) -> dict | None:
    bias = snap.get("bias")
    if bias is None:
        return None
    value_text = f"20日乖離 {bias:+.2f}%"
    if bias >= 12:
        return _signal("bias", "乖離率 BIAS", "bearish", 70,
                       f"股價正乖離達 {bias:.1f}%，短線偏離均線過遠，有均值回歸的壓力。", value_text)
    if bias <= -12:
        return _signal("bias", "乖離率 BIAS", "bullish", 70,
                       f"股價負乖離達 {bias:.1f}%，短線跌深，反彈需求增加。", value_text)
    if bias >= 3:
        return _signal("bias", "乖離率 BIAS", "bullish", 40,
                       f"正乖離 {bias:.1f}%，股價穩定位於均線之上，但尚未過熱。", value_text)
    if bias <= -3:
        return _signal("bias", "乖離率 BIAS", "bearish", 40,
                       f"負乖離 {bias:.1f}%，股價受均線壓制。", value_text)
    return _signal("bias", "乖離率 BIAS", "neutral", 25,
                   f"乖離率僅 {bias:.1f}%，股價貼著均線走，籌碼相對穩定。", value_text)


def _volume_signal(snap: dict) -> dict | None:
    volume, volume_ma = snap.get("volume"), snap.get("volume_ma20")
    if not volume or not volume_ma:
        return None

    ratio = volume / volume_ma
    change_pct = snap.get("change_pct", 0.0) or 0.0
    obv, obv_prev = snap.get("obv"), snap.get("obv_prev")
    obv_rising = obv is not None and obv_prev is not None and obv > obv_prev
    value_text = f"量能 {ratio:.2f} 倍月均量"

    if ratio >= 1.8 and change_pct > 0:
        return _signal("volume", "量能與籌碼", "bullish", 80,
                       f"成交量放大到月均量的 {ratio:.1f} 倍且股價上漲，屬於價漲量增的健康型態。", value_text)
    if ratio >= 1.8 and change_pct < 0:
        return _signal("volume", "量能與籌碼", "bearish", 75,
                       f"成交量放大到月均量的 {ratio:.1f} 倍但股價下跌，出現賣壓宣洩，需留意籌碼鬆動。", value_text)
    if ratio <= 0.6:
        return _signal("volume", "量能與籌碼", "neutral", 45,
                       f"成交量萎縮到月均量的 {ratio:.1f} 倍，市場觀望氣氛濃，行情不易延續。", value_text)
    if obv_rising:
        return _signal("volume", "量能與籌碼", "bullish", 45,
                       "量能正常，OBV 能量潮持續墊高，代表資金仍在流入。", value_text)
    return _signal("volume", "量能與籌碼", "neutral", 30,
                   "量能與 OBV 都沒有明顯變化，籌碼面中性。", value_text)


def _position_signal(snap: dict) -> dict | None:
    position = snap.get("position_52w")
    if position is None:
        return None
    high, low = snap.get("high_52w"), snap.get("low_52w")
    value_text = f"位階 {position:.0f}%（區間 {_fmt(low)} ~ {_fmt(high)}）"
    if position >= 90:
        return _signal("position_52w", "波段位階", "bullish", 65,
                       f"股價位於近一年區間的 {position:.0f}% 位置，接近波段高點，趨勢強勢但屬於高位階。", value_text)
    if position <= 10:
        return _signal("position_52w", "波段位階", "bearish", 65,
                       f"股價位於近一年區間的 {position:.0f}% 位置，接近波段低點，屬於弱勢低位階。", value_text)
    if position >= 65:
        return _signal("position_52w", "波段位階", "bullish", 45,
                       f"股價位於近一年區間的 {position:.0f}%，位階偏高。", value_text)
    if position <= 35:
        return _signal("position_52w", "波段位階", "bearish", 45,
                       f"股價位於近一年區間的 {position:.0f}%，位階偏低。", value_text)
    return _signal("position_52w", "波段位階", "neutral", 25,
                   f"股價位於近一年區間的 {position:.0f}%，處於中間位階。", value_text)


def _volatility_signal(snap: dict) -> dict | None:
    volatility = snap.get("volatility_annualized")
    if volatility is None:
        return None
    atr, close = snap.get("atr"), snap.get("close")
    atr_pct = (atr / close * 100.0) if atr and close else None
    value_text = f"年化波動 {volatility:.1f}%" + (f"／ATR {atr_pct:.1f}%" if atr_pct else "")
    if volatility >= 45:
        return _signal("volatility", "波動風險", "bearish", 60,
                       f"年化波動度達 {volatility:.0f}%，價格劇烈震盪，部位控管要更保守。", value_text)
    if volatility <= 15:
        return _signal("volatility", "波動風險", "neutral", 35,
                       f"年化波動度僅 {volatility:.0f}%，走勢相對平穩。", value_text)
    return _signal("volatility", "波動風險", "neutral", 25,
                   f"年化波動度 {volatility:.0f}%，屬於一般水準。", value_text)


def _sentiment_signal(summary: dict | None) -> dict | None:
    if not summary or not summary.get("records"):
        return None
    score = float(summary.get("score_mean") or 0.0)
    positive = float(summary.get("positive_ratio") or 0.0) * 100
    negative = float(summary.get("negative_ratio") or 0.0) * 100
    label = summary.get("dominant_label", "neutral")
    records = int(summary.get("records") or 0)
    value_text = f"{records} 則新聞／正 {positive:.0f}%、負 {negative:.0f}%"

    if label == "positive":
        strength = 50 + min(35, abs(score))
        return _signal("sentiment", "新聞情緒", "bullish", strength,
                       f"近期 {records} 則新聞中正面佔 {positive:.0f}%，平均情緒分數 {score:.1f}，消息面偏向樂觀。", value_text)
    if label == "negative":
        strength = 50 + min(35, abs(score))
        return _signal("sentiment", "新聞情緒", "bearish", strength,
                       f"近期 {records} 則新聞中負面佔 {negative:.0f}%，平均情緒分數 {score:.1f}，消息面偏向保守。", value_text)
    return _signal("sentiment", "新聞情緒", "neutral", 30,
                   f"近期 {records} 則新聞正負面比例接近（正 {positive:.0f}%、負 {negative:.0f}%），消息面中性。", value_text)


def _forecast_signal(forecast_result: dict | None) -> dict | None:
    if not forecast_result or forecast_result.get("status") != "ready":
        return None
    ensemble = forecast_result.get("ensemble") or {}
    change = float(ensemble.get("change_pct") or 0.0)
    horizon = forecast_result.get("horizon_days", 7)
    accuracy = ensemble.get("directional_accuracy")
    value_text = f"{horizon} 日預估 {change:+.2f}%" + (f"／回測方向準確率 {accuracy:.0f}%" if accuracy else "")

    # 回測方向準確率越低，這個訊號的份量就越小
    reliability = 0.5 if accuracy is None else max(0.2, min(1.0, float(accuracy) / 100.0))
    strength = min(90, abs(change) * 12 + 30) * reliability + 15

    if change >= 1.0:
        return _signal("forecast", "模型預測", "bullish", strength,
                       f"整合模型推估未來 {horizon} 個交易日約為 {change:+.2f}%，方向偏多。", value_text)
    if change <= -1.0:
        return _signal("forecast", "模型預測", "bearish", strength,
                       f"整合模型推估未來 {horizon} 個交易日約為 {change:+.2f}%，方向偏空。", value_text)
    return _signal("forecast", "模型預測", "neutral", 30,
                   f"整合模型推估未來 {horizon} 個交易日僅 {change:+.2f}%，接近持平，缺乏明確方向。", value_text)


# --------------------------------------------------------------------------- #
# 綜合判讀
# --------------------------------------------------------------------------- #
def _stance_from_score(score: float) -> str:
    if score >= 35:
        return "bullish"
    if score >= 12:
        return "slightly_bullish"
    if score <= -35:
        return "bearish"
    if score <= -12:
        return "slightly_bearish"
    return "neutral"


def _build_summary(stance: str, score: float, signals: list[dict], snap: dict,
                   instrument_label: str) -> tuple[str, str, list[str]]:
    bullish = [s for s in signals if s["stance"] == "bullish"]
    bearish = [s for s in signals if s["stance"] == "bearish"]
    bullish.sort(key=lambda s: -s["strength"])
    bearish.sort(key=lambda s: -s["strength"])

    change_pct = snap.get("change_pct", 0.0) or 0.0
    close = snap.get("close")

    headline_map = {
        "bullish": "技術面明顯偏多，多方主導盤勢",
        "slightly_bullish": "技術面偏多，但力道仍待確認",
        "neutral": "多空拉鋸，方向尚未明朗",
        "slightly_bearish": "技術面偏弱，反彈力道有限",
        "bearish": "技術面明顯偏空，賣壓仍重",
    }
    headline = headline_map[stance]

    parts: list[str] = []
    parts.append(
        f"目前{instrument_label}收在 {_fmt(close)}（最近一個交易日 {change_pct:+.2f}%），"
        f"綜合 {len(signals)} 項指標後的多空分數為 {score:+.0f} 分（-100 至 +100），判定為「{STANCE_LABELS[stance]}」。"
    )

    if bullish:
        names = "、".join(s["name"] for s in bullish[:3])
        parts.append(f"支持偏多的訊號有 {len(bullish)} 項，其中最明確的是{names}：{bullish[0]['text']}")
    if bearish:
        names = "、".join(s["name"] for s in bearish[:3])
        parts.append(f"偏空或需要留意的訊號有 {len(bearish)} 項，主要是{names}：{bearish[0]['text']}")
    if not bullish and not bearish:
        parts.append("目前沒有任何指標出現明確的方向訊號，屬於典型的盤整格局。")

    action_map = {
        "bullish": "多項指標同向偏多，順勢操作的勝算較高；但仍建議設好停利與停損，避免追高。",
        "slightly_bullish": "偏多訊號略多於偏空，可留意回檔不破均線時的進場機會，資金分批投入較安全。",
        "neutral": "多空訊號互相抵銷，建議等待方向明確（例如站穩或跌破 20 日均線）再行動，此時觀望往往優於硬做。",
        "slightly_bearish": "偏空訊號略多，若已有部位可考慮降低比重，新進場則宜等待止跌訊號。",
        "bearish": "技術面明顯轉弱，優先控制風險；不建議在下跌趨勢中攤平，等待打底完成較穩健。",
    }
    bullets = [signal["text"] for signal in (bullish[:2] + bearish[:2])]
    return headline, " ".join(parts) + " " + action_map[stance], bullets


def _risk_note(snap: dict, signals: list[dict]) -> str:
    notes: list[str] = []
    volatility = snap.get("volatility_annualized")
    if volatility and volatility >= 40:
        notes.append(f"年化波動度高達 {volatility:.0f}%，單日跳動幅度大")
    rsi = snap.get("rsi")
    if rsi is not None and rsi >= 75:
        notes.append("RSI 已進入超買區，追價風險偏高")
    if rsi is not None and rsi <= 25:
        notes.append("RSI 已進入超賣區，不宜貿然摸底")
    sample = snap.get("sample_size") or 0
    if sample < 60:
        notes.append(f"歷史資料僅 {sample} 筆，指標與預測的穩定度較低")
    conflicting = len({s["stance"] for s in signals if s["stance"] != "neutral"}) > 1
    if conflicting:
        notes.append("指標之間存在分歧，代表盤勢處於轉折或整理階段")
    if not notes:
        notes.append("目前沒有偵測到特別突出的風險項目，但市場仍可能受突發消息影響")
    return "；".join(notes) + "。"


def analyze(
    snapshot: dict,
    sentiment_summary: dict | None = None,
    forecast_result: dict | None = None,
    instrument_kind: str | None = None,
) -> dict:
    """把指標快照 + 新聞情緒 + 模型預測整合成中文判讀結果。"""
    if not snapshot:
        return {
            "status": "no_data",
            "score": 0,
            "stance": "neutral",
            "stance_label": STANCE_LABELS["neutral"],
            "headline": "資料不足，無法判讀",
            "summary": "目前沒有足夠的歷史價格資料可以計算技術指標，請改用較長的時間區間再試一次。",
            "signals": [],
            "counts": {"bullish": 0, "bearish": 0, "neutral": 0},
            "disclaimer": DISCLAIMER,
        }

    builders = [
        _trend_signal(snapshot),
        _rsi_signal(snapshot),
        _macd_signal(snapshot),
        _kd_signal(snapshot),
        _bollinger_signal(snapshot),
        _bias_signal(snapshot),
        _volume_signal(snapshot),
        _position_signal(snapshot),
        _volatility_signal(snapshot),
        _sentiment_signal(sentiment_summary),
        _forecast_signal(forecast_result),
    ]
    signals = [item for item in builders if item]

    total_weight = 0.0
    weighted = 0.0
    for signal in signals:
        weight = _WEIGHTS.get(signal["key"], 1.0)
        direction = 1 if signal["stance"] == "bullish" else -1 if signal["stance"] == "bearish" else 0
        weighted += direction * (signal["strength"] / 100.0) * weight
        total_weight += weight

    score = (weighted / total_weight * 100.0) if total_weight else 0.0
    score = max(-100.0, min(100.0, score))
    stance = _stance_from_score(score)

    counts = {
        "bullish": sum(1 for s in signals if s["stance"] == "bullish"),
        "bearish": sum(1 for s in signals if s["stance"] == "bearish"),
        "neutral": sum(1 for s in signals if s["stance"] == "neutral"),
    }

    instrument_label = {
        "etf": "這檔指數型基金（ETF）",
        "stock": "這檔股票",
        "index": "這個指數",
    }.get(instrument_kind or "", "這檔標的")

    headline, summary, bullets = _build_summary(stance, score, signals, snapshot, instrument_label)

    # 綜合信心：訊號一致性越高、樣本越多，信心越高
    decisive = counts["bullish"] + counts["bearish"]
    consistency = (abs(counts["bullish"] - counts["bearish"]) / decisive) if decisive else 0.0
    confidence = round(min(90.0, 30.0 + consistency * 45.0 + min(len(signals), 10) * 1.2))

    return {
        "status": "ready",
        "score": round(score, 1),
        "stance": stance,
        "stance_label": STANCE_LABELS[stance],
        "confidence": confidence,
        "headline": headline,
        "summary": summary,
        "bullets": bullets,
        "signals": signals,
        "counts": counts,
        "risk_note": _risk_note(snapshot, signals),
        "disclaimer": DISCLAIMER,
    }
