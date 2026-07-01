from __future__ import annotations

import re
from collections import defaultdict

from rescueops.models import DiscoveredSignal, Evidence

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "is",
    "it",
    "not",
    "of",
    "on",
    "or",
    "our",
    "that",
    "the",
    "their",
    "them",
    "this",
    "to",
    "until",
    "was",
    "we",
    "with",
}

MIN_PHRASE_SCORE = 10


def discover_emerging_signals(
    evidence: tuple[Evidence, ...],
    account_name: str = "",
    limit: int = 5,
) -> tuple[DiscoveredSignal, ...]:
    account_terms = set(tokenize(account_name))
    phrase_hits: dict[str, list[Evidence]] = defaultdict(list)

    for item in evidence:
        seen_in_item = set(candidate_phrases(item.text, account_terms))
        for phrase in seen_in_item:
            phrase_hits[phrase].append(item)

    discovered = [
        build_signal(phrase, hits)
        for phrase, hits in phrase_hits.items()
        if len(hits) >= 2 or max(item.weight for item in hits) >= 12
    ]

    ranked = sorted(discovered, key=lambda item: item.score, reverse=True)
    return tuple(item for item in ranked if item.score >= MIN_PHRASE_SCORE)[:limit]


def candidate_phrases(text: str, excluded_terms: set[str]) -> tuple[str, ...]:
    tokens = [
        token
        for token in tokenize(text)
        if token not in STOP_WORDS and token not in excluded_terms and len(token) > 2
    ]

    phrases: set[str] = set()
    for size in (2, 3):
        for index in range(0, max(len(tokens) - size + 1, 0)):
            phrase = " ".join(tokens[index : index + size])
            if meaningful_phrase(phrase):
                phrases.add(phrase)

    return tuple(phrases)


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9$]+", text.lower()))


def meaningful_phrase(phrase: str) -> bool:
    terms = phrase.split()
    if len(set(terms)) != len(terms):
        return False
    return any(not term.isdigit() for term in terms)


def build_signal(phrase: str, hits: list[Evidence]) -> DiscoveredSignal:
    channels = tuple(sorted({item.channel for item in hits}))
    sources = tuple(sorted({item.source for item in hits}))
    examples = tuple(item.title for item in sorted(hits, key=lambda item: item.weight, reverse=True)[:2])
    avg_weight = round(sum(item.weight for item in hits) / len(hits))
    score = avg_weight + len(hits) * 3 + len(channels) * 2 + len(sources) * 2

    return DiscoveredSignal(
        phrase=phrase,
        score=score,
        evidence_count=len(hits),
        channels=channels,
        sources=sources,
        examples=examples,
    )


def emerging_pattern_bonus(signals: tuple[DiscoveredSignal, ...]) -> int:
    if not signals:
        return 0
    return min(sum(signal.score for signal in signals[:3]) // 12, 12)