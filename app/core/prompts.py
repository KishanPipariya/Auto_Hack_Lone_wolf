import json
from datetime import datetime, timedelta
from typing import Mapping

from app.core.destinations import requested_route_city_terms
from app.models.domain import Activity, DestinationSuggestion, Itinerary, Preferences

MODEL_CANDIDATES = [
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.5",
]


def calendar_context(preferences: Preferences) -> str:
    if not preferences.start_date:
        return "No specific dates provided. Assume standard opening hours."

    start_dt = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            start_dt = datetime.strptime(preferences.start_date, fmt)
            break
        except ValueError:
            continue

    if not start_dt:
        return "Invalid date format. Assume standard opening hours."

    lines = ["SPECIFIC CALENDAR:"]
    for i in range(preferences.days):
        current_dt = start_dt + timedelta(days=i)
        lines.append(f"- Day {i + 1}: {current_dt.strftime('%A, %B %d, %Y')}")

    lines.extend(
        [
            "",
            "CRITICAL INSTRUCTION: Check opening hours for all venues for the specific DAY OF THE WEEK listed above.",
            "If a museum/location is CLOSED on that day (e.g. Louvre is closed Tuesdays), you MUST reschedule it to another day or choose a different activity.",
        ]
    )
    return "\n".join(lines)


def initial_plan_prompt(
    preferences: Preferences,
    activities: list[Activity],
    destination_suggestions: list[DestinationSuggestion] | None = None,
    category_targets: Mapping[str, float] | None = None,
) -> str:
    destination = (preferences.city or "").strip()
    requested_destinations = requested_route_city_terms(destination)
    multi_city_instruction = (
        "The requested destination is a multi-city route. Keep all requested cities "
        "in the plan, split days between them, and include travel time between cities."
        if len(requested_destinations) > 1
        else ""
    )
    destination_instruction = (
        f"Create the itinerary for {destination}. {multi_city_instruction}".strip()
        if destination
        else "Choose exactly one best-fit destination for this trip based on the vibe, budget, duration, and interests. Do not return a list of destination options."
    )
    vibe_instruction = (
        preferences.vibe or "balanced, locally distinctive, budget-conscious"
    )
    work_instruction = (
        "Include work-friendly stay/environment notes with strong Wi-Fi, cafe or coworking access, and quiet planning windows."
        if preferences.work_friendly
        else "No special remote-work filtering is required."
    )
    activities_context = activities_context_for_destination(
        destination, activities, preferences
    )
    curated_context = destination_context(destination_suggestions or [], preferences)
    budget_context = budget_targets_context(preferences, category_targets)
    budget_cap = budget_cap_text(preferences)
    currency_mode = cost_currency_mode(preferences)

    return f"""
        You are an expert travel agent. {destination_instruction}
        Create a {preferences.days}-day itinerary with a hard all-inclusive budget cap of {budget_cap}.
        Vibe/aesthetic: {vibe_instruction}
        Work-friendly requirement: {work_instruction}
        User Interests: {", ".join(preferences.interests)}

        {curated_context}

        {budget_context}

        CRITICAL INSTRUCTIONS:
        1. Return one curated destination or one requested multi-city route and a compact, detailed day-wise itinerary only.
        2. MULTI-CITY LOGIC: If the user explicitly requests multiple destinations, split the days logically between them.
           - You MUST specify the 'city' field for EACH DayPlan object so we know where the user is.
           - Every requested city MUST appear in at least one DayPlan 'city' value.
           - Account for travel time between cities as an activity.
        3. REALISM: Account for opening hours and logical travel times between venues.
        4. IMAGES: For every activity, generate a specific, search-friendly image_url query or real image URL.
        5. COSTS: {currency_mode} Keep the total under budget.
        6. VALID JSON: Return pure JSON matching the Itinerary pydantic schema. No markdown, no preamble.

        TRIP DATES & OPENING HOURS:
        {calendar_context(preferences)}

        {activities_context}

        REQUIREMENTS:
        - Return one curated destination or one requested multi-city route and a compact day-wise itinerary only.
        - {currency_mode}
        - cost_breakdown.total MUST be less than or equal to {budget_cap}.
        - Activity costs must match cost_breakdown.activities.
        - transport + stay + food + activities MUST equal cost_breakdown.total.
        - Explain briefly why the destination matches the vibe.
        - Include budget_notes explaining the category allocation and remaining budget.
        - Include work_friendly_notes when the work-friendly requirement is active; otherwise use null.

        OUTPUT FORMAT:
        Return ONLY a JSON object matching this structure:
        {{
            "city": "Selected destination city or requested multi-city route",
            "recommended_destination": "Selected destination city or requested multi-city route",
            "vibe_rationale": "Why this destination matches the vibe and interests",
            "budget_notes": "How the budget is allocated and kept under cap",
            "work_friendly_notes": "Wi-Fi/coworking/stay notes or null",
            "destination_suggestions": [],
            "cost_breakdown": {{
                "transport": 100,
                "stay": 180,
                "food": 90,
                "activities": 80,
                "total": 450,
                "remaining_budget": 50
            }},
            "days": [
                {{
                    "day_number": 1,
                    "city": "City for this day",
                    "activities": [
                        {{
                            "name": "Activity Name",
                            "description": "Short description",
                            "cost": 20,
                            "duration_hours": 1.5,
                            "duration_str": "1-2 hours",
                            "image_url": "https://example.com/real-photo.jpg",
                            "tags": ["Tag1", "Tag2"]
                        }}
                    ]
                }}
            ]
        }}
        """


def refinement_prompt(
    previous_plan: Itinerary,
    error: str,
    preferences: Preferences,
    activities: list[Activity],
    destination_suggestions: list[DestinationSuggestion] | None = None,
    category_targets: Mapping[str, float] | None = None,
) -> str:
    destination = (preferences.city or previous_plan.city or "").strip()
    activities_context = activities_context_for_destination(
        destination, activities, preferences, refinement=True
    )
    curated_context = destination_context(destination_suggestions or [], preferences)
    budget_context = budget_targets_context(preferences, category_targets)
    budget_cap = budget_cap_text(preferences)
    currency_mode = cost_currency_mode(preferences)
    extra_instruction = ""
    if "0 days" in error or "valid JSON" in error:
        extra_instruction = """
            CRITICAL: The previous output was NOT valid JSON or was empty.
            You MUST return a pure JSON object.
            Do NOT support markdown.
            Do NOT add explanations.
            """

    return f"""
        The previous itinerary for {destination or "the selected destination"} was INVALID.
        Error: {error}

        Previous Plan Total Cost: {budget_amount_text(previous_plan.total_cost, preferences)}
        Budget: {budget_cap}

        {budget_context}

        DATES:
        {calendar_context(preferences)}

        Please fix the plan by reducing category estimates and swapping activities to meet the constraints.
        Keep the requested destination or multi-city route, exactly {preferences.days} days, and total cost <= {budget_cap}.
        {currency_mode}
        If multiple cities were requested, every requested city must appear in at least one DayPlan city value.
        Include a full cost_breakdown with transport, stay, food, activities, total, and remaining_budget.
        Ensure activity costs add up to cost_breakdown.activities and all cost categories add up to cost_breakdown.total.
        Preserve destination_suggestions from the previous plan.

        {extra_instruction}

        {curated_context}

        {activities_context}

        OUTPUT FORMAT:
        Return a valid JSON object matching the Itinerary structure.
        """


def json_repair_prompt(raw_response: str, preferences: Preferences) -> str:
    currency_mode = cost_currency_mode(preferences)
    cost_aliases = (
        "- cost_local/estimated_cost_local/local_cost -> cost"
        if preferences.uses_local_budget
        else "- cost_usd/estimated_cost_usd -> cost"
    )
    return f"""
        Convert the following travel itinerary response into valid JSON matching
        the Itinerary schema exactly. Preserve the same trip content, dates,
        costs, activities, destination suggestions, and notes where possible.
        Do not add markdown, citations, source IDs, or explanatory text.
        {currency_mode}

        Required top-level fields:
        - city: string
        - recommended_destination: string or null
        - vibe_rationale: string or null
        - budget_notes: string or null
        - work_friendly_notes: string or null
        - destination_suggestions: array of objects with city, country,
          rationale, estimated_total_cost, tags
        - cost_breakdown: object with transport, stay, food, activities, total,
          remaining_budget
        - days: array of objects with day_number and activities

        Required activity fields:
        - name: string
        - description: string
        - cost: number
        - duration_hours: number
        - duration_str: string or null
        - image_url: string or null
        - tags: array of strings

        If the source uses aliases, map them as follows:
        - destination/name -> city
        - day -> day_number
        - plan -> activities
        - activity/title -> activity name
        {cost_aliases}

        Return ONLY the corrected JSON object.

        Source response:
        {raw_response}
        """


def budget_targets_context(
    preferences: Preferences,
    category_targets: Mapping[str, float] | None,
) -> str:
    daily_target = preferences.budget / max(preferences.days, 1)
    currency_note = budget_currency_note(preferences)

    if not category_targets:
        return (
            "BUDGET TARGETS:\n"
            f"- Hard cap: {budget_amount_text(preferences.budget, preferences)}. Keep every estimate all-inclusive and under this cap.\n"
            f"- Daily target: about {budget_amount_text(daily_target, preferences)} per day across {preferences.days} day(s)."
            f"{currency_note}"
        )

    return "\n".join(
        [
            "BUDGET TARGETS:",
            f"- Hard cap: {budget_amount_text(category_targets.get('total', preferences.budget), preferences)}",
            f"- Daily target: about {budget_amount_text(daily_target, preferences)} per day across {preferences.days} day(s).",
            f"- Transport target: {budget_amount_text(category_targets.get('transport', 0), preferences)}",
            f"- Stay target: {budget_amount_text(category_targets.get('stay', 0), preferences)}",
            f"- Food target: {budget_amount_text(category_targets.get('food', 0), preferences)}",
            f"- Activities target: {budget_amount_text(category_targets.get('activities', 0), preferences)}",
            "- You may move small amounts between categories, but the final total must remain under the hard cap.",
            currency_note.lstrip(),
        ]
    )


def destination_context(
    suggestions: list[DestinationSuggestion],
    preferences: Preferences,
) -> str:
    if not suggestions:
        return "No curated destination context is available."

    lines = ["CURATED DESTINATION CONTEXT:"]
    for index, suggestion in enumerate(suggestions, start=1):
        country = f", {suggestion.country}" if suggestion.country else ""
        tags = ", ".join(suggestion.tags) if suggestion.tags else "general"
        lines.append(
            f"{index}. {suggestion.city}{country} - estimated total "
            f"{budget_amount_text(suggestion.estimated_total_cost, preferences)}; "
            f"tags: {tags}; rationale: {suggestion.rationale}"
        )
    lines.append(
        "Use the #1 curated destination when the user did not provide a city. "
        "Keep destination_suggestions in the final JSON if provided."
    )
    return "\n".join(lines)


def format_budget_amount(value: float) -> str:
    if value and abs(value) < 1:
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{value:g}"


def budget_amount_text(value: float, preferences: Preferences) -> str:
    formatted = format_budget_amount(value)
    if preferences.uses_local_budget:
        return f"{formatted} in the destination's local currency"
    return f"${formatted}"


def budget_cap_text(preferences: Preferences) -> str:
    return budget_amount_text(preferences.budget, preferences)


def budget_currency_note(preferences: Preferences) -> str:
    if not preferences.uses_local_budget:
        return ""
    return (
        "\n- The user entered the budget in the destination's local currency. "
        "Do not convert this budget to USD. Keep transport, stay, food, activities, "
        "total, remaining_budget, destination_suggestions.estimated_total_cost, "
        "and every activity cost in the destination's local currency."
    )


def cost_currency_mode(preferences: Preferences) -> str:
    if preferences.uses_local_budget:
        return (
            "All cost fields must be numeric amounts in the destination's local "
            "currency only. Do not use USD, do not convert to USD, and do not include "
            "currency symbols or currency codes in JSON number fields."
        )
    return (
        "Include transport, stay, food, activities, destination suggestion estimates, "
        "and every activity cost as numeric USD amounts."
    )


def activities_context_for_destination(
    destination: str,
    activities: list[Activity],
    preferences: Preferences,
    refinement: bool = False,
) -> str:
    if destination.lower() == "paris":
        instruction = "AVAILABLE ACTIVITIES:"
        if not refinement:
            instruction = "AVAILABLE ACTIVITIES (You must ONLY use these, do not invent new ones):"
        currency_instruction = cost_currency_mode(preferences)
        return f"""
             {instruction}
             {json.dumps([a.model_dump() for a in activities], indent=2)}
             COST CURRENCY: {currency_instruction}
             """

    if refinement:
        return f"""
             AVAILABLE ACTIVITIES:
             You are free to find real activities using web search.
             **REMINDER**: {cost_currency_mode(preferences)} Be realistic for the destination's actual prices.
             """

    return f"""
             AVAILABLE ACTIVITIES:
             You are free to find real activities using web search.

             **CRITICAL INSTRUCTION: COST & CURRENCY**
             - {cost_currency_mode(preferences)}
             - **BE REALISTIC**: Use actual local price levels. Public transport and street food should reflect normal destination prices.

             **CRITICAL INSTRUCTION: IMAGE URLs**
             - You MUST SEARCH for a real, public, direct image URL for each activity.
             - Prefer URLs from trusted sources like **Wikimedia Commons**, **Wikipedia**, or **official tourism sites**.
             - The URL SHOULD end in an image extension (e.g., .jpg, .png, .webp) to ensure it renders.
             - Do NOT use placeholder text like "http/..." or "image_url_here".
             - If you cannot find a reliable URL, leave the field null (our system will auto-generate one).
             """
