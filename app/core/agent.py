import json
import logging
import os
import urllib.request
from collections.abc import Iterator
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.core.data import MOCK_ACTIVITIES
from app.core.destinations import recommend_destinations
from app.core.images import search_real_image
from app.core.parser import parse_llm_response
from app.core.prompts import (
    MODEL_CANDIDATES,
    OPENROUTER_CANDIDATES,
    initial_plan_prompt,
    refinement_prompt,
)
from app.models.domain import DestinationSuggestion, Itinerary, Preferences

load_dotenv()

logger = logging.getLogger("travel_agent_server.agent")


def budget_targets(preferences: Preferences) -> dict[str, float]:
    """Allocate the hard budget into deterministic planning targets."""
    if preferences.work_friendly:
        ratios = {
            "transport": 0.20,
            "stay": 0.40,
            "food": 0.20,
            "activities": 0.20,
        }
    else:
        ratios = {
            "transport": 0.25,
            "stay": 0.35,
            "food": 0.20,
            "activities": 0.20,
        }

    targets = {
        category: round(preferences.budget * ratio, 2)
        for category, ratio in ratios.items()
    }
    target_total = sum(targets.values())
    targets["activities"] = round(
        targets["activities"] + preferences.budget - target_total, 2
    )
    targets["total"] = round(preferences.budget, 2)
    return targets


class TravelAgent:
    def __init__(self):
        self.activities = MOCK_ACTIVITIES
        self.client: Any | None = None

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY not found in environment.")
        else:
            self.client = genai.Client(api_key=api_key)

    def _call_openrouter(self, prompt: str) -> str:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not found. Cannot use fallback.")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "User-Agent": "TravelPlannerAgent/1.0",
        }

        last_error: Exception | None = None
        for model in OPENROUTER_CANDIDATES:
            logger.debug("Attempting OpenRouter fallback with %s", model)
            data = {"model": model, "messages": [{"role": "user", "content": prompt}]}

            try:
                req = urllib.request.Request(url, json.dumps(data).encode(), headers)
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode())
                    if "choices" in result and result["choices"]:
                        logger.debug("Success with OpenRouter model %s", model)
                        return str(result["choices"][0]["message"]["content"])
            except Exception as exc:
                logger.warning("OpenRouter model %s failed", model, exc_info=True)
                last_error = exc

        raise ValueError(f"All OpenRouter candidates failed. Last error: {last_error}")

    def _call_model_with_fallback(self, prompt: str) -> str:
        last_error: Exception | None = None
        if self.client:
            config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                response_mime_type="application/json",
            )

            for model_name in MODEL_CANDIDATES:
                try:
                    logger.info("Attempting generation with model %s", model_name)
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )
                    logger.info("Generation succeeded with model %s", model_name)
                    return str(response.text)
                except Exception as exc:
                    logger.warning("Model %s failed", model_name, exc_info=True)
                    last_error = exc

        try:
            return self._call_openrouter(prompt)
        except Exception as openrouter_error:
            final_error = last_error or openrouter_error
            raise RuntimeError(
                f"All model candidates failed. Last error: {final_error}"
            ) from openrouter_error

    def _check_constraints(
        self, itinerary: Itinerary, preferences: Preferences
    ) -> bool:
        itinerary.calculate_total_cost()
        itinerary.cost_breakdown.remaining_budget = (
            preferences.budget - itinerary.cost_breakdown.total
        )
        itinerary.total_cost = itinerary.cost_breakdown.total

        if not itinerary.city or itinerary.city == "Unknown":
            itinerary.valid = False
            itinerary.validation_error = (
                "Itinerary must include a recommended destination."
            )
            return False

        if preferences.city and itinerary.city.lower() != preferences.city.lower():
            itinerary.city = preferences.city

        if len(itinerary.days) != preferences.days:
            itinerary.valid = False
            itinerary.validation_error = f"Itinerary has {len(itinerary.days)} days, expected {preferences.days}."
            return False

        if any(not day.activities for day in itinerary.days):
            itinerary.valid = False
            itinerary.validation_error = (
                "Each itinerary day must include at least one curated activity."
            )
            return False

        activity_total = sum(
            sum(activity.cost for activity in day.activities)
            for day in itinerary.days
        )
        if abs(activity_total - itinerary.cost_breakdown.activities) > 0.01:
            itinerary.valid = False
            itinerary.validation_error = (
                "Activity costs do not match cost_breakdown.activities."
            )
            return False

        total_cost = itinerary.cost_breakdown.total

        category_total = (
            itinerary.cost_breakdown.transport
            + itinerary.cost_breakdown.stay
            + itinerary.cost_breakdown.food
            + itinerary.cost_breakdown.activities
        )
        if abs(category_total - itinerary.cost_breakdown.total) > 0.01:
            itinerary.valid = False
            itinerary.validation_error = (
                "Cost breakdown categories do not add up to the total."
            )
            return False

        if total_cost > preferences.budget:
            itinerary.valid = False
            itinerary.validation_error = (
                f"Total cost ${total_cost} exceeds budget ${preferences.budget}."
            )
            return False

        itinerary.valid = True
        itinerary.validation_error = None
        return True

    def _prepare_destination_context(
        self, preferences: Preferences
    ) -> tuple[Preferences, list[DestinationSuggestion]]:
        suggestions = recommend_destinations(preferences)
        if preferences.city or not suggestions:
            return preferences, suggestions

        selected_city = suggestions[0].city
        return preferences.model_copy(update={"city": selected_city}), suggestions

    def _attach_destination_context(
        self,
        itinerary: Itinerary,
        suggestions: list[DestinationSuggestion],
        preferences: Preferences,
    ) -> Itinerary:
        itinerary.destination_suggestions = suggestions

        if not itinerary.city and suggestions:
            itinerary.city = suggestions[0].city
        if not itinerary.recommended_destination:
            itinerary.recommended_destination = itinerary.city

        if not itinerary.vibe_rationale and suggestions:
            itinerary.vibe_rationale = suggestions[0].rationale

        if preferences.work_friendly and not itinerary.work_friendly_notes:
            itinerary.work_friendly_notes = (
                "Plan includes work-friendly pacing; choose lodging with reliable Wi-Fi "
                "and confirm coworking or quiet cafe access before booking."
            )

        itinerary.calculate_total_cost()
        itinerary.cost_breakdown.remaining_budget = (
            preferences.budget - itinerary.cost_breakdown.total
        )
        return itinerary

    def generate_initial_plan(
        self,
        preferences: Preferences,
        destination_suggestions: list[DestinationSuggestion] | None = None,
    ) -> Itinerary:
        logger.debug("Generating initial itinerary")
        targets = budget_targets(preferences)
        prompt = initial_plan_prompt(
            preferences, self.activities, destination_suggestions or [], targets
        )
        response_text = self._call_model_with_fallback(prompt)
        return parse_llm_response(response_text, image_search=search_real_image)

    def refine_plan(
        self,
        previous_plan: Itinerary,
        error: str,
        preferences: Preferences,
        destination_suggestions: list[DestinationSuggestion] | None = None,
    ) -> Itinerary:
        logger.debug("Refining itinerary after validation error: %s", error)
        targets = budget_targets(preferences)
        prompt = refinement_prompt(
            previous_plan,
            error,
            preferences,
            self.activities,
            destination_suggestions or [],
            targets,
        )
        response_text = self._call_model_with_fallback(prompt)
        return parse_llm_response(response_text, image_search=search_real_image)

    def plan_trip_stream(self, preferences: Preferences) -> Iterator[str | Itinerary]:
        planning_preferences, destination_suggestions = self._prepare_destination_context(
            preferences
        )
        if destination_suggestions:
            top = destination_suggestions[0]
            yield f"Curated destination match: {top.city}, {top.country or ''}".rstrip(
                ", "
            )

        yield "Google ADK Agent: Step 1 - Breaking plan into days & allocating activities..."
        itinerary = self.generate_initial_plan(
            planning_preferences, destination_suggestions
        )
        itinerary = self._attach_destination_context(
            itinerary, destination_suggestions, planning_preferences
        )
        cost = itinerary.calculate_total_cost()
        yield f"Initial allocation complete. Estimated Cost: ${cost}"

        yield "Google ADK Agent: Step 2 - Verifying budget & time constraints..."
        is_valid = self._check_constraints(itinerary, planning_preferences)

        max_retries = 3
        attempts = 0
        if not is_valid:
            yield "Google ADK Agent: Step 3 - Budget exceeded. Initiating Re-planning Loop..."

        while not is_valid and attempts < max_retries:
            attempts += 1
            yield f"Constraint Violation: {itinerary.validation_error}"
            yield f"Re-planning attempt {attempts}/{max_retries}..."

            itinerary = self.refine_plan(
                itinerary,
                itinerary.validation_error or "Unknown Validation Error",
                planning_preferences,
                destination_suggestions,
            )
            itinerary = self._attach_destination_context(
                itinerary, destination_suggestions, planning_preferences
            )
            itinerary.calculate_total_cost()
            is_valid = self._check_constraints(itinerary, planning_preferences)

        if not is_valid:
            yield "Warning: Constraints not fully met after re-planning. Returning validation error."

        yield "Google ADK Agent: Step 4 - Finalizing itinerary & generating artifacts..."
        yield itinerary

    def plan_trip(self, preferences: Preferences) -> Itinerary:
        result: Itinerary | None = None
        for item in self.plan_trip_stream(preferences):
            if isinstance(item, Itinerary):
                result = item
            else:
                logger.debug("Planning status: %s", item)
        if result is None:
            raise RuntimeError("Planning failed to produce an itinerary result.")
        return result
