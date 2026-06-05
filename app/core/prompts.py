import json
from datetime import datetime, timedelta
from typing import Mapping

from app.core.destinations import destination_context
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
    destination_instruction = (
        f"Create the itinerary for {destination}."
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
    activities_context = activities_context_for_destination(destination, activities)
    curated_context = destination_context(destination_suggestions or [])
    budget_context = budget_targets_context(preferences, category_targets)

    return f"""
        You are an expert travel agent. {destination_instruction}
        Create a {preferences.days}-day itinerary with a hard all-inclusive budget cap of ${preferences.budget}.
        Vibe/aesthetic: {vibe_instruction}
        Work-friendly requirement: {work_instruction}
        User Interests: {", ".join(preferences.interests)}

        {curated_context}

        {budget_context}

        CRITICAL INSTRUCTIONS:
        1. Return one curated destination and a compact, detailed day-wise itinerary only.
        2. MULTI-CITY LOGIC: If the user explicitly requests multiple destinations, split the days logically between them.
           - You MUST specify the 'city' field for EACH DayPlan object so we know where the user is.
           - Account for travel time between cities as an activity.
        3. REALISM: Account for opening hours and logical travel times between venues.
        4. IMAGES: For every activity, generate a specific, search-friendly image_url query or real image URL.
        5. COSTS: Include transport, stay, food, and activities estimates in USD and keep the total under budget.
        6. VALID JSON: Return pure JSON matching the Itinerary pydantic schema. No markdown, no preamble.

        TRIP DATES & OPENING HOURS:
        {calendar_context(preferences)}

        {activities_context}

        REQUIREMENTS:
        - Return one curated destination and a compact day-wise itinerary only.
        - Include transport, stay, food, and activities estimates in USD.
        - cost_breakdown.total MUST be less than or equal to ${preferences.budget}.
        - Activity costs must match cost_breakdown.activities.
        - transport + stay + food + activities MUST equal cost_breakdown.total.
        - Explain briefly why the destination matches the vibe.
        - Include budget_notes explaining the category allocation and remaining budget.
        - Include work_friendly_notes when the work-friendly requirement is active; otherwise use null.

        OUTPUT FORMAT:
        Return ONLY a JSON object matching this structure:
        {{
            "city": "Selected destination city",
            "recommended_destination": "Selected destination city",
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
        destination, activities, refinement=True
    )
    curated_context = destination_context(destination_suggestions or [])
    budget_context = budget_targets_context(preferences, category_targets)
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

        Previous Plan Total Cost: ${previous_plan.total_cost}
        Budget: ${preferences.budget}

        {budget_context}

        DATES:
        {calendar_context(preferences)}

        Please fix the plan by reducing category estimates and swapping activities to meet the constraints.
        Keep exactly one destination, exactly {preferences.days} days, and total cost <= ${preferences.budget}.
        Include a full cost_breakdown with transport, stay, food, activities, total, and remaining_budget.
        Ensure activity costs add up to cost_breakdown.activities and all cost categories add up to cost_breakdown.total.
        Preserve destination_suggestions from the previous plan.

        {extra_instruction}

        {curated_context}

        {activities_context}

        OUTPUT FORMAT:
        Return a valid JSON object matching the Itinerary structure.
        """


def json_repair_prompt(raw_response: str) -> str:
    return f"""
        Convert the following travel itinerary response into valid JSON matching
        the Itinerary schema exactly. Preserve the same trip content, dates,
        costs, activities, destination suggestions, and notes where possible.
        Do not add markdown, citations, source IDs, or explanatory text.

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
        - cost: number in USD
        - duration_hours: number
        - duration_str: string or null
        - image_url: string or null
        - tags: array of strings

        If the source uses aliases, map them as follows:
        - destination/name -> city
        - day -> day_number
        - plan -> activities
        - activity/title -> activity name
        - cost_usd/estimated_cost_usd -> cost

        Return ONLY the corrected JSON object.

        Source response:
        {raw_response}
        """


def budget_targets_context(
    preferences: Preferences,
    category_targets: Mapping[str, float] | None,
) -> str:
    if not category_targets:
        return (
            "BUDGET TARGETS:\n"
            f"- Hard cap: ${preferences.budget:g}. Keep every estimate all-inclusive and under this cap."
        )

    return "\n".join(
        [
            "BUDGET TARGETS:",
            f"- Hard cap: ${category_targets.get('total', preferences.budget):g}",
            f"- Transport target: ${category_targets.get('transport', 0):g}",
            f"- Stay target: ${category_targets.get('stay', 0):g}",
            f"- Food target: ${category_targets.get('food', 0):g}",
            f"- Activities target: ${category_targets.get('activities', 0):g}",
            "- You may move small amounts between categories, but the final total must remain under the hard cap.",
        ]
    )


def activities_context_for_destination(
    destination: str,
    activities: list[Activity],
    refinement: bool = False,
) -> str:
    if destination.lower() == "paris":
        instruction = "AVAILABLE ACTIVITIES:"
        if not refinement:
            instruction = "AVAILABLE ACTIVITIES (You must ONLY use these, do not invent new ones):"
        return f"""
             {instruction}
             {json.dumps([a.model_dump() for a in activities], indent=2)}
             """

    if refinement:
        return """
             AVAILABLE ACTIVITIES:
             You are free to find real activities using web search.
             **REMINDER**: Estimate costs in LOCAL currency, then convert to USD. Be realistic (e.g. Mumbai street food is <$5).
             """

    return """
             AVAILABLE ACTIVITIES:
             You are free to find real activities using web search.

             **CRITICAL INSTRUCTION: COST & CURRENCY**
             - Estimate costs in the destination's LOCAL currency first (e.g. Rupees, Yen, Euros).
             - CONVERT all costs to USD using current exchange rates.
             - **BE REALISTIC**: Street food in Asia is cheap (<$5 USD). Public transport is cheap. Fine dining is expensive.
             - Output ONLY the USD number in the `cost` field.

             **CRITICAL INSTRUCTION: IMAGE URLs**
             - You MUST SEARCH for a real, public, direct image URL for each activity.
             - Prefer URLs from trusted sources like **Wikimedia Commons**, **Wikipedia**, or **official tourism sites**.
             - The URL SHOULD end in an image extension (e.g., .jpg, .png, .webp) to ensure it renders.
             - Do NOT use placeholder text like "http/..." or "image_url_here".
             - If you cannot find a reliable URL, leave the field null (our system will auto-generate one).
             """
