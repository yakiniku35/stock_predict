from __future__ import annotations

import math
import re
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
        positive_term_weights: dict[str, float] | None = None,
        negative_term_weights: dict[str, float] | None = None,
        negation_terms: list[str] | None = None,
        intensifiers: list[str] | None = None,
    ) -> None:
        self.positive_terms = [t.lower() for t in (positive_terms or POSITIVE_TERMS)]
        self.negative_terms = [t.lower() for t in (negative_terms or NEGATIVE_TERMS)]
        self.negation_terms = [t.lower() for t in (negation_terms or NEGATION_TERMS)]
        self.intensifiers = [t.lower() for t in (intensifiers or INTENSIFIERS)]
        self.positive_threshold = positive_threshold
        self.negative_threshold = negative_threshold

        self.positive_term_weights = {
            "漲停": 1.5,
            "創新高": 1.3,
            "超預期": 1.3,
            "上修": 1.2,
            "強勁": 1.2,
            "guidance raised": 1.4,
            "record high": 1.3,
        }
        self.negative_term_weights = {
            "跌停": 1.6,
            "破產": 1.8,
            "違約": 1.8,
            "下修": 1.3,
            "重挫": 1.4,
            "guidance cut": 1.4,
            "warning": 1.3,
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

    def _score(self, normalized: str) -> float:
        pos_hits = self._weighted_hits(normalized, self.positive_terms, self.positive_term_weights)
        neg_hits = self._weighted_hits(normalized, self.negative_terms, self.negative_term_weights)

        pos_to_neg, neg_to_pos = self._negation_flip(normalized)
        pos_hits = max(0.0, pos_hits - pos_to_neg + neg_to_pos)
        neg_hits = max(0.0, neg_hits - neg_to_pos + pos_to_neg)

        intensity = self._intensity_boost(normalized)
        pos_hits *= intensity
        neg_hits *= intensity

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
