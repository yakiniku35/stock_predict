from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

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
    model_name = "lexicon_baseline_v2"

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

    def _score(self, normalized: str) -> float:
        pos_hits = sum(normalized.count(term) for term in self.positive_terms)
        neg_hits = sum(normalized.count(term) for term in self.negative_terms)
        total_hits = pos_hits + neg_hits

        if total_hits == 0:
            return 0.0

        score = (pos_hits - neg_hits) / math.sqrt(total_hits)
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
        score = round(self._score(normalized), 4)
        return SentimentResult(score=score, label=self._label(score))

    def predict_many(self, texts: Iterable[str]) -> list[SentimentResult]:
        results: list[SentimentResult] = []
        for text in texts:
            results.append(self.predict(text))
        return results
