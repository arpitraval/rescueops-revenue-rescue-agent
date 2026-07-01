from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "risk_taxonomy.json"


@lru_cache(maxsize=1)
def load_risk_taxonomy() -> dict[str, Any]:
    with TAXONOMY_PATH.open(encoding="utf-8") as taxonomy_file:
        return json.load(taxonomy_file)


def infer_tags(text: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    tags = []

    for signal in load_risk_taxonomy()["signals"]:
        patterns = signal.get("patterns", ())
        if any(phrase_present(normalized, pattern) for pattern in patterns):
            tags.append(signal["tag"])

    return tuple(tags)


def estimate_weight(text: str, tags: tuple[str, ...]) -> int:
    taxonomy = load_risk_taxonomy()
    scoring = taxonomy["scoring"]
    normalized = normalize_text(text)

    signal_weights = {
        signal["tag"]: int(signal.get("weight", 0))
        for signal in taxonomy["signals"]
    }

    weight = int(scoring["base_signal_weight"])
    weight += sum(signal_weights.get(tag, 0) for tag in tags)

    for boost in scoring.get("boosts", ()):
        patterns = boost.get("patterns", ())
        if any(phrase_present(normalized, pattern) for pattern in patterns):
            weight += int(boost["weight"])

    weight += revenue_amount_boost(normalized, scoring)
    return min(weight, int(scoring["max_signal_weight"]))


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def phrase_present(text: str, phrase: str) -> bool:
    normalized_phrase = normalize_text(phrase)
    if " " in normalized_phrase or "-" in normalized_phrase:
        return normalized_phrase in text
    return re.search(rf"\b{re.escape(normalized_phrase)}\b", text) is not None


def revenue_amount_boost(text: str, scoring: dict[str, Any]) -> int:
    if not re.search(r"(\$|usd)\s?\d", text):
        return 0
    return int(scoring.get("revenue_amount_weight", 0))