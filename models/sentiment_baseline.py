from __future__ import annotations

import math
from dataclasses import dataclass

POSITIVE_TERMS = [
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
    "樂觀",
    "飆升",
    "bullish",
    "beat",
    "surge",
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
    "bearish",
    "miss",
    "plunge",
]


@dataclass
class SentimentResult:
    score: float
    label: str


class LexiconSentimentAnalyzer:
    def __init__(
        self,
        positive_terms: list[str] | None = None,
        negative_terms: list[str] | None = None,
        positive_threshold: float = 0.2,
        negative_threshold: float = -0.2,
    ) -> None:
        self.positive_terms = [t.lower() for t in (positive_terms or POSITIVE_TERMS)]
        self.negative_terms = [t.lower() for t in (negative_terms or NEGATIVE_TERMS)]
        self.positive_threshold = positive_threshold
        self.negative_threshold = negative_threshold

    def predict(self, text: str) -> SentimentResult:
        normalized = " ".join((text or "").split()).lower()
        if not normalized:
            return SentimentResult(score=0.0, label="neutral")

        pos_hits = sum(normalized.count(term) for term in self.positive_terms)
        neg_hits = sum(normalized.count(term) for term in self.negative_terms)
        total_hits = pos_hits + neg_hits

        if total_hits == 0:
            score = 0.0
        else:
            score = (pos_hits - neg_hits) / math.sqrt(total_hits)
            score = max(-1.0, min(1.0, score))

        if score >= self.positive_threshold:
            label = "positive"
        elif score <= self.negative_threshold:
            label = "negative"
        else:
            label = "neutral"

        return SentimentResult(score=round(score, 4), label=label)
