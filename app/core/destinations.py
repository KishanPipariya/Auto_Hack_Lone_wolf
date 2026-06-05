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
    "cafes": {"cafe", "cafes", "coffee", "street food", "food"},
    "food": {"food", "cuisine", "street food", "cafe", "cafes", "dining"},
    "history": {"history", "historic", "ancient", "heritage", "monastery"},
    "nature": {"nature", "beach", "mountain", "forest", "lake", "wildlife"},
    "nightlife": {"nightlife", "bars", "music", "lively"},
    "romantic": {"romantic", "relaxed", "sunset", "charm"},
    "shopping": {"market", "shopping", "shops", "boutique"},
}

VIBE_KEYWORDS = {
    "ancient": {"ancient", "historic", "heritage", "temple", "medieval", "old town"},
    "beach": {"beach", "coastal", "ocean", "island", "reef", "turquoise"},
    "budget": {"budget", "affordable", "cheap", "shoestring", "reasonable"},
    "cafes": {"cafe", "cafes", "coffee", "street food", "food"},
    "chill": {"relaxed", "laid-back", "tranquil", "serene", "quiet"},
    "city": {"city", "urban", "markets", "streets", "nightlife", "culture"},
    "creative": {"art", "gallery", "murals", "architecture", "creative"},
    "digital": {"cafe", "cafes", "city", "markets", "affordable", "culture"},
    "foodie": {"food", "cuisine", "street food", "dining", "flavors"},
    "luxury": {"luxury", "glamour", "high-end", "opulent", "designer"},
    "mountain": {"mountain", "hike", "hiking", "trek", "alps", "andes"},
    "quiet": {"tranquil", "serene", "laid-back", "relaxed", "hidden"},
    "romantic": {"romantic", "sunset", "charm", "palaces", "canals"},
}

WORK_FRIENDLY_CITIES = {
    "Bali",
    "Bangkok",
    "Budapest",
    "Chiang Mai",
    "Goa",
    "Hanoi",
    "Hoi An",
    "Krakow",
    "Lisbon",
    "Medellin",
    "Mexico City",
    "Penang",
    "Tbilisi",
}

REMOTE_WORK_RISK_TERMS = {
    "safari",
    "rainforest",
    "national park",
    "wilderness",
    "gorillas",
    "delta",
    "outback",
}


@lru_cache
def load_destinations() -> list[dict[str, Any]]:
    with DESTINATIONS_PATH.open(encoding="utf-8") as fp:
        return json.load(fp)


def recommend_destinations(
    preferences: Preferences,
    limit: int = 3,
) -> list[DestinationSuggestion]:
    requested_terms = requested_destination_terms(preferences.city)
    destinations = load_destinations()
    if requested_terms:
        matches = [
            item
            for item in destinations
            if _matches_requested_destination(item, requested_terms)
        ]
        return [_to_suggestion(item) for item in matches[:limit]]

    candidates = sorted(
        destinations,
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


def requested_destination_terms(value: str | None) -> list[str]:
    if not value:
        return []
    terms = re.split(r"\s*(?:,|\band\b|&|\+)\s*", value, flags=re.IGNORECASE)
    return [term.strip() for term in terms if term.strip()]


def _matches_requested_destination(
    item: dict[str, Any],
    requested_terms: list[str],
) -> bool:
    city = str(item.get("city", "")).lower()
    country = str(item.get("country", "")).lower()

    for term in requested_terms:
        requested = term.lower()
        if requested == city or requested == country:
            return True
        if requested in city or requested in country:
            return True
    return False


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

    score += _text_score(preferences.vibe or "", text, weight=9)
    score += _semantic_score(preferences.vibe or "", text, VIBE_KEYWORDS, weight=6)
    for interest in preferences.interests:
        normalized_interest = _clean_interest(interest)
        score += _text_score(normalized_interest, text, weight=8)
        score += _keyword_score(normalized_interest, text, INTEREST_KEYWORDS, weight=7)
        score += _semantic_score(
            normalized_interest, text, VIBE_KEYWORDS, weight=4
        )

    estimated_cost = float(item.get("estimated_cost") or 0)
    if estimated_cost and preferences.budget:
        if estimated_cost <= preferences.budget:
            score += 45
            budget_room = max(preferences.budget - estimated_cost, 0)
            score += max(0, 25 * (1 - budget_room / preferences.budget))
            if estimated_cost <= preferences.budget * 0.75:
                score += 8
        else:
            over_ratio = (estimated_cost - preferences.budget) / preferences.budget
            score -= 85 + (over_ratio * 90)

    if preferences.work_friendly:
        score += _work_friendly_score(item, text, preferences)

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


def _keyword_score(
    interest: str,
    text: str,
    keyword_map: dict[str, set[str]],
    weight: float,
) -> float:
    keywords = keyword_map.get(interest, set())
    return sum(weight for keyword in keywords if keyword in text)


def _semantic_score(
    query: str,
    text: str,
    keyword_map: dict[str, set[str]],
    weight: float,
) -> float:
    query_words = {
        word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2
    }
    score = 0.0
    for word in query_words:
        keywords = keyword_map.get(word, set())
        score += sum(weight for keyword in keywords if keyword in text)
    return score


def _work_friendly_score(
    item: dict[str, Any],
    text: str,
    preferences: Preferences,
) -> float:
    score = 0.0
    if item.get("city") in WORK_FRIENDLY_CITIES:
        score += 28
    score += _semantic_score(
        "digital quiet cafes budget city",
        text,
        VIBE_KEYWORDS,
        weight=3,
    )
    if any(term in text for term in REMOTE_WORK_RISK_TERMS):
        score -= 35
    estimated_cost = float(item.get("estimated_cost") or 0)
    if estimated_cost and estimated_cost <= preferences.budget:
        score += 10
    return score


def _matched_tags(text: str) -> set[str]:
    tags = set()
    for tag, keywords in INTEREST_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            tags.add(tag.title())
    return tags
