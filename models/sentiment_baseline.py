from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

POSITIVE_TERMS = [
    "樂觀",
    "上漲",
    "利多",
    "創高",
    "成長",
    "看好",
    "回升",
    "擴產",
    "突破",
    "獲利",
    "增持",
    "買進",
    "強勁",
    "飆升",
    "彈升",
    "勁揚",
    "收紅",
    "翻紅",
    "續強",
    "站上",
    "攻上",
    "躍升",
    "新高",
    "bullish",
    "beat",
    "surge",
    "漲停",
    "走強",
    "大漲",
    "轉強",
    "優於預期",
    "超預期",
    "營收成長",
    "毛利提升",
    "淨利提升",
    "訂單回溫",
    "接單強勁",
    "需求回溫",
    "庫存去化",
    "調升",
    "上修",
    "加碼",
    "回購",
    "配息",
    "創新高",
    "利潤擴大",
    "outperform",
    "upgrade",
    "strong buy",
    "guidance raised",
    "record high",
    "growth",
]

NEGATIVE_TERMS = [
    "下跌",
    "利空",
    "重挫",
    "衰退",
    "看壞",
    "虧損",
    "破底",
    "減持",
    "賣出",
    "風險",
    "疲弱",
    "悲觀",
    "裁員",
    "下修",
    "跌破",
    "翻黑",
    "跳水",
    "下挫",
    "殺低",
    "摜破",
    "失守",
    "爆量下跌",
    "震盪下跌",
    "bearish",
    "miss",
    "plunge",
    "跌停",
    "走弱",
    "大跌",
    "重跌",
    "轉弱",
    "低於預期",
    "不如預期",
    "下修財測",
    "財測下修",
    "營收衰退",
    "毛利下滑",
    "淨利下滑",
    "需求疲軟",
    "庫存壓力",
    "砍單",
    "調降",
    "降評",
    "減碼",
    "破產",
    "違約",
    "虧損擴大",
    "創新低",
    "downgrade",
    "underperform",
    "guidance cut",
    "warning",
    "decline",
]

NEGATION_TERMS = [
    "不",
    "未",
    "沒有",
    "無",
    "並非",
    "non",
    "not",
    "never",
]

INTENSIFIERS = [
    "非常",
    "明顯",
    "大幅",
    "強烈",
    "顯著",
    "greatly",
    "strongly",
    "significantly",
]

UNCERTAINTY_TERMS = [
    "但",
    "然而",
    "不過",
    "仍",
    "觀望",
    "中性",
    "持平",
    "尚待",
    "可能",
    "potentially",
    "however",
    "but",
    "uncertain",
]


@dataclass
class SentimentResult:
    score: float
    label: str


class LexiconSentimentAnalyzer: 
    model_name = "lexicon_baseline_v2"

    def __init__(
        self,
        positive_terms: list[str] | None = None,
        negative_terms: list[str] | None = None,
        positive_threshold: float = 20.0,
        negative_threshold: float = -20.0,
        positive_term_weights: dict[str, float] | None = None,
        negative_term_weights: dict[str, float] | None = None,
        negation_terms: list[str] | None = None,
        intensifiers: list[str] | None = None,
        uncertainty_terms: list[str] | None = None,
    ) -> None:
        self.positive_terms = [t.lower() for t in (positive_terms or POSITIVE_TERMS)]
        self.negative_terms = [t.lower() for t in (negative_terms or NEGATIVE_TERMS)]
        self.negation_terms = [t.lower() for t in (negation_terms or NEGATION_TERMS)]
        self.intensifiers = [t.lower() for t in (intensifiers or INTENSIFIERS)]
        self.uncertainty_terms = [t.lower() for t in (uncertainty_terms or UNCERTAINTY_TERMS)]
        self.positive_threshold = positive_threshold
        self.negative_threshold = negative_threshold

        self.positive_term_weights = {
            # ── 極度正面（突破性事件）──
            "漲停": 1.9,
            "暴漲": 1.8,
            "飆漲": 1.85,
            "大漲": 1.7,
            "historic high": 1.8,
            "all-time high": 1.85,
            "record breaking": 1.75,

            # ── 高度正面（基本面 / 預期大幅上修）──
            "創新高": 1.6,
            "創高": 1.55,
            "超預期": 1.5,
            "大幅超越": 1.55,
            "上修": 1.45,
            "獲利創高": 1.6,
            "guidance raised": 1.5,
            "beat estimates": 1.5,
            "earnings beat": 1.55,
            "raised outlook": 1.5,
            "upgrade": 1.45,

            # ── 中度正面（技術面 / 盤勢訊號）──
            "新高": 1.35,
            "record high": 1.35,
            "勁揚": 1.3,
            "飆升": 1.35,
            "站上": 1.25,
            "突破": 1.3,
            "強彈": 1.3,
            "回升": 1.2,
            "bullish": 1.25,
            "breakout": 1.3,
            "outperform": 1.3,

            # ── 輕度正面（氣氛偏多）──
            "買超": 1.15,
            "強勁": 1.2,
            "樂觀": 1.1,
            "看好": 1.1,
            "買進": 1.1,
            "accumulate": 1.1,
            "positive": 1.05,
            "optimistic": 1.1,
            "momentum": 1.1,
        }
        self.negative_term_weights = {
            # ── 極度危險（公司存亡層級）──
            "破產": 2.0,
            "倒閉": 2.0,
            "下市": 1.9,
            "違約": 1.9,
            "debt default": 1.9,
            "bankruptcy": 2.0,
            "insolvency": 1.9,
            "liquidation": 1.9,

            # ── 高度負面（財務/評等惡化）──
            "跌停": 1.7,
            "重挫": 1.6,
            "暴跌": 1.6,
            "崩跌": 1.65,
            "大幅下修": 1.6,
            "下修": 1.4,
            "虧損擴大": 1.5,
            "獲利預警": 1.55,
            "guidance cut": 1.5,
            "profit warning": 1.55,
            "downgrade": 1.5,
            "earnings miss": 1.45,

            # ── 中度負面（技術面 / 盤勢訊號）──
            "跌破": 1.35,
            "跳水": 1.35,
            "下挫": 1.3,
            "回落": 1.2,
            "失守": 1.25,
            "翻黑": 1.25,
            "warning": 1.3,
            "sell-off": 1.35,
            "bearish": 1.2,

            # ── 輕度負面（氣氛偏空）──
            "觀望": 1.1,
            "不確定": 1.1,
            "審慎": 1.05,
            "疲軟": 1.15,
            "承壓": 1.15,
            "cautious": 1.1,
            "uncertainty": 1.1,
            "headwinds": 1.15,
        }
        if positive_term_weights:
            self.positive_term_weights.update({k.lower(): float(v) for k, v in positive_term_weights.items()})
        if negative_term_weights:
            self.negative_term_weights.update({k.lower(): float(v) for k, v in negative_term_weights.items()})

    def _weighted_hits(self, normalized: str, terms: list[str], weights: dict[str, float]) -> float:
        total = 0.0
        for term in terms:
            cnt = normalized.count(term)
            if cnt <= 0:
                continue
            total += cnt * float(weights.get(term, 1.0))
        return total

    def _negation_flip(self, normalized: str) -> tuple[float, float]:
        pos_to_neg = 0.0
        neg_to_pos = 0.0
        for neg in self.negation_terms:
            for term in self.positive_terms:
                pattern = re.escape(neg) + r"\s*" + re.escape(term)
                hits = len(re.findall(pattern, normalized))
                if hits:
                    pos_to_neg += float(hits)
            for term in self.negative_terms:
                pattern = re.escape(neg) + r"\s*" + re.escape(term)
                hits = len(re.findall(pattern, normalized))
                if hits:
                    neg_to_pos += float(hits)
        return pos_to_neg, neg_to_pos

    def _intensity_boost(self, normalized: str) -> float:
        boost_hits = 0
        for term in self.intensifiers:
            boost_hits += normalized.count(term)
        # Cap boost to avoid score explosion in long repetitive text.
        return min(1.25, 1.0 + (0.05 * boost_hits))

    def _uncertainty_penalty(self, normalized: str) -> float:
        hits = 0
        for term in self.uncertainty_terms:
            hits += normalized.count(term)
        # More uncertainty terms -> shrink confidence toward neutral.
        return max(0.75, 1.0 - (0.04 * hits))

    def _conflict_penalty(self, pos_hits: float, neg_hits: float) -> float:
        if pos_hits <= 0.0 or neg_hits <= 0.0:
            return 1.0
        low = min(pos_hits, neg_hits)
        high = max(pos_hits, neg_hits)
        ratio = low / max(1e-9, high)
        # If both sides are strong (ratio close to 1), damp score toward neutral.
        return max(0.7, 1.0 - (0.3 * ratio))

    def _presence_hits(self, normalized: str, terms: list[str]) -> int:
        hits = 0
        for term in terms:
            if term in normalized:
                hits += 1
        return hits

    def _score(self, normalized: str) -> float:
        pos_hits = self._weighted_hits(normalized, self.positive_terms, self.positive_term_weights)
        neg_hits = self._weighted_hits(normalized, self.negative_terms, self.negative_term_weights)

        pos_to_neg, neg_to_pos = self._negation_flip(normalized)
        pos_hits = max(0.0, pos_hits - pos_to_neg + neg_to_pos)
        neg_hits = max(0.0, neg_hits - neg_to_pos + pos_to_neg)

        intensity = self._intensity_boost(normalized)
        pos_hits *= intensity
        neg_hits *= intensity

        uncertainty_penalty = self._uncertainty_penalty(normalized)
        conflict_penalty = self._conflict_penalty(pos_hits, neg_hits)

        total_hits = pos_hits + neg_hits

        if total_hits == 0:
            return 0.0

        score = (pos_hits - neg_hits) / math.sqrt(total_hits)
        score *= uncertainty_penalty
        score *= conflict_penalty
        return max(-1.0, min(1.0, score))

    def _label(self, score: float) -> str:
        if score >= self.positive_threshold:
            return "positive"
        if score <= self.negative_threshold:
            return "negative"
        return "neutral"

    def predict(self, text: str) -> SentimentResult:
        normalized = " ".join((text or "").split()).lower()
        if not normalized:
            return SentimentResult(score=0.0, label="neutral")
        raw_score = float(self._score(normalized))

        # Final guardrail: mixed polarity + uncertainty should prefer neutral.
        pos_presence = self._presence_hits(normalized, self.positive_terms)
        neg_presence = self._presence_hits(normalized, self.negative_terms)
        uncertainty_hits = self._presence_hits(normalized, self.uncertainty_terms)
        if pos_presence > 0 and neg_presence > 0:
            if uncertainty_hits > 0:
                raw_score = raw_score * 0.35
            elif abs(raw_score) < 0.55:
                raw_score = raw_score * 0.65
        elif uncertainty_hits >= 2 and abs(raw_score) < 0.7:
            raw_score = raw_score * 0.6

        scaled_score = max(-100.0, min(100.0, raw_score * 100.0))
        scaled_score = round(scaled_score, 2)

        return SentimentResult(score=scaled_score, label=self._label(scaled_score))

    def predict_many(self, texts: Iterable[str]) -> list[SentimentResult]:
        results: list[SentimentResult] = []
        for text in texts:
            results.append(self.predict(text))
        return results
