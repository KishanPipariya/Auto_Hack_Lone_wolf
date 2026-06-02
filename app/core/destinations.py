import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models.domain import DestinationSuggestion, Preferences

DESTINATIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "destinations.json"

INTEREST_KEYWORDS = {
    "adventure": {"adventure", "hiking", "trek", "surf", "diving", "rafting"},
    "art": {"art", "gallery", "museum", "architecture", "creative"},
    "food": {"food", "cuisine", "street food", "cafe", "cafes", "dining"},
    "history": {"history", "historic", "ancient", "heritage", "monastery"},
    "nature": {"nature", "beach", "mountain", "forest", "lake", "wildlife"},
    "nightlife": {"nightlife", "bars", "music", "lively"},
    "romantic": {"romantic", "relaxed", "sunset", "charm"},
    "shopping": {"market", "shopping", "shops", "boutique"},
}


@lru_cache
def load_destinations() -> list[dict[str, Any]]:
    with DESTINATIONS_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)


def recommend_destinations(
    preferences: Preferences,
    limit: int = 3,
) -> list[DestinationSuggestion]:
    candidates = sorted(
        load_destinations(),
        key=lambda item: _score_destination(item, preferences),
        reverse=True,
    )
    return [_to_suggestion(item) for item in candidates[:limit]]


def destination_context(suggestions: list[DestinationSuggestion]) -> str:
    if not suggestions:
        return "No curated destination context is available."

    lines = ["CURATED DESTINATION CONTEXT:"]
    for index, suggestion in enumerate(suggestions, start=1):
        country = f", {suggestion.country}" if suggestion.country else ""
        tags = ", ".join(suggestion.tags) if suggestion.tags else "general"
        lines.append(
            f"{index}. {suggestion.city}{country} - estimated total ${suggestion.estimated_total_cost:g}; "
            f"tags: {tags}; rationale: {suggestion.rationale}"
        )
    lines.append(
        "Use the #1 curated destination when the user did not provide a city. "
        "Keep destination_suggestions in the final JSON if provided."
    )
    return "\n".join(lines)


def _to_suggestion(item: dict[str, Any]) -> DestinationSuggestion:
    text = _destination_text(item)
    return DestinationSuggestion(
        city=str(item.get("city", "")),
        country=item.get("country"),
        rationale=item.get("rationale") or item.get("description"),
        estimated_total_cost=float(item.get("estimated_cost") or 0),
        tags=sorted(_matched_tags(text)),
    )


def _score_destination(item: dict[str, Any], preferences: Preferences) -> float:
    text = _destination_text(item)
    score = 0.0

    if preferences.city:
        city = str(item.get("city", "")).lower()
        country = str(item.get("country", "")).lower()
        requested = preferences.city.lower()
        if requested == city:
            score += 200
        elif requested in city or requested in country:
            score += 80

    score += _text_score(preferences.vibe or "", text, weight=8)
    for interest in preferences.interests:
        normalized_interest = _clean_interest(interest)
        score += _text_score(normalized_interest, text, weight=7)
        score += _keyword_score(normalized_interest, text)

    estimated_cost = float(item.get("estimated_cost") or 0)
    if estimated_cost and preferences.budget:
        if estimated_cost <= preferences.budget:
            score += 35
            score += max(0, 20 * (1 - (preferences.budget - estimated_cost) / preferences.budget))
        else:
            over_ratio = (estimated_cost - preferences.budget) / preferences.budget
            score -= 60 + (over_ratio * 70)

    return score


def _destination_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key, ""))
        for key in ("city", "country", "description", "rationale", "image_key")
    ).lower()


def _clean_interest(value: str) -> str:
    return re.sub(r"^[^\w]+", "", value).strip().lower()


def _text_score(query: str, text: str, weight: float) -> float:
    words = [word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2]
    return sum(weight for word in words if word in text)


def _keyword_score(interest: str, text: str) -> float:
    keywords = INTEREST_KEYWORDS.get(interest, set())
    return sum(6 for keyword in keywords if keyword in text)


def _matched_tags(text: str) -> set[str]:
    tags = set()
    for tag, keywords in INTEREST_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            tags.add(tag.title())
    return tags
