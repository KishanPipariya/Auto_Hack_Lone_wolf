import json
import logging
import re
from collections.abc import Callable
from typing import Any

from app.core.images import resolve_activity_image
from app.models.domain import Itinerary

logger = logging.getLogger("travel_agent_server.parser")


def parse_money(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", value.replace(",", ""))
        return float(nums[0]) if nums else 0.0
    return 0.0


def parse_duration(value: Any, default: float = 1.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", value)
        return float(nums[0]) if nums else default
    return default


def extract_json_payload(response_text: str) -> Any:
    cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
    start_idx = cleaned_text.find("{")
    end_idx = cleaned_text.rfind("}")

    if start_idx == -1:
        start_idx = cleaned_text.find("[")
        end_idx = cleaned_text.rfind("]")

    if start_idx == -1:
        return json.loads(cleaned_text)

    candidate_json = cleaned_text[start_idx:]
    try:
        data, _ = json.JSONDecoder().raw_decode(candidate_json)
        return data
    except json.JSONDecodeError:
        if end_idx == -1:
            raise
        return json.loads(cleaned_text[start_idx : end_idx + 1])


def normalize_itinerary_data(
    data: Any,
    image_search: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("LLM response JSON must be an object")

    data = dict(data)
    normalize_itinerary_aliases(data)

    activity_total = 0.0
    days = data.get("days", [])
    if isinstance(days, list):
        for day in days:
            if not isinstance(day, dict):
                continue
            day_city = str(day.get("city") or data.get("city") or "destination")
            normalize_day(day, day_city, image_search)
            day_activity_total = sum(
                parse_money(activity.get("cost", 0))
                for activity in day.get("activities", [])
                if isinstance(activity, dict)
            )
            day["total_cost"] = day.get("total_cost") or day_activity_total
            activity_total += day_activity_total

    normalize_cost_breakdown(data, activity_total)

    return data


def normalize_itinerary_aliases(data: dict[str, Any]) -> None:
    if not data.get("city"):
        data["city"] = data.get("destination") or data.get("name")

    if not data.get("recommended_destination"):
        data["recommended_destination"] = data.get("city")

    suggestions = data.get("destination_suggestions", [])
    if isinstance(suggestions, list):
        for suggestion in suggestions:
            normalize_destination_suggestion(suggestion)

    days = data.get("days", [])
    if isinstance(days, list):
        for day in days:
            normalize_day_aliases(day)


def normalize_destination_suggestion(suggestion: Any) -> None:
    if not isinstance(suggestion, dict):
        return

    if not suggestion.get("city"):
        suggestion["city"] = suggestion.get("destination") or suggestion.get("name")
    if not suggestion.get("estimated_total_cost"):
        suggestion["estimated_total_cost"] = (
            suggestion.get("estimated_total")
            or suggestion.get("estimated_total_usd")
            or suggestion.get("cost_estimate_usd")
            or 0
        )


def normalize_day_aliases(day: Any) -> None:
    if not isinstance(day, dict):
        return

    if not day.get("day_number"):
        day["day_number"] = day.get("day")
    if not day.get("city"):
        day["city"] = day.get("destination") or day.get("location")
    if not day.get("activities") and isinstance(day.get("plan"), list):
        day["activities"] = [
            normalize_plan_item_aliases(item) for item in day["plan"] if isinstance(item, dict)
        ]


def normalize_plan_item_aliases(item: dict[str, Any]) -> dict[str, Any]:
    activity = dict(item)
    if not activity.get("name"):
        activity["name"] = activity.get("activity") or activity.get("title") or "Activity"
    if not activity.get("description"):
        activity["description"] = activity.get("activity") or activity.get("name")
    if not activity.get("cost"):
        activity["cost"] = (
            activity.get("cost_usd")
            or activity.get("estimated_cost_usd")
            or activity.get("cost_estimate_usd")
            or 0
        )
    if activity.get("time") and not activity.get("tags"):
        activity["tags"] = [str(activity["time"])]
    return activity


def normalize_day(
    day: dict[str, Any],
    city: str,
    image_search: Callable[[str], str | None] | None,
) -> None:
    activities = day.get("activities", [])
    if not isinstance(activities, list):
        return

    for activity in activities:
        if not isinstance(activity, dict):
            continue
        normalize_activity(activity, city, image_search)


def normalize_activity(
    activity: dict[str, Any],
    city: str,
    image_search: Callable[[str], str | None] | None,
) -> None:
    activity["cost"] = parse_money(activity.get("cost", 0))

    raw_duration = activity.get("duration_hours", 1.0)
    if isinstance(raw_duration, str):
        activity["duration_str"] = raw_duration
    elif "duration_str" not in activity:
        activity["duration_str"] = f"{parse_duration(raw_duration):g} hours"

    duration_hours = parse_duration(raw_duration)
    activity["duration_hours"] = duration_hours

    if not activity.get("tags"):
        activity["tags"] = ["General"]
    if not activity.get("description"):
        activity["description"] = activity.get("name", "Activity")
    activity["image_url"] = resolve_activity_image(activity, city, image_search)


def normalize_cost_breakdown(data: dict[str, Any], activity_total: float) -> None:
    raw_breakdown = data.get("cost_breakdown") or {}
    if not isinstance(raw_breakdown, dict):
        raw_breakdown = {}

    normalized_breakdown = {
        "transport": parse_money(raw_breakdown.get("transport", 0)),
        "stay": parse_money(raw_breakdown.get("stay", 0)),
        "food": parse_money(raw_breakdown.get("food", 0)),
        "activities": activity_total,
        "total": parse_money(raw_breakdown.get("total", data.get("total_cost", 0))),
        "remaining_budget": parse_money(raw_breakdown.get("remaining_budget", 0)),
    }

    computed_total = (
        normalized_breakdown["transport"]
        + normalized_breakdown["stay"]
        + normalized_breakdown["food"]
        + normalized_breakdown["activities"]
    )
    normalized_breakdown["total"] = computed_total

    data["cost_breakdown"] = normalized_breakdown
    data["total_cost"] = normalized_breakdown["total"]


def parse_llm_response(
    response_text: str,
    image_search: Callable[[str], str | None] | None = None,
) -> Itinerary:
    try:
        data = normalize_itinerary_data(
            extract_json_payload(response_text), image_search
        )
        return Itinerary(**data)
    except Exception:
        logger.error("Error parsing LLM response", exc_info=True)
        logger.error("Raw response: %s", response_text)
        return Itinerary(city="Unknown", days=[])
