import os
import json
import urllib.request
from typing import List
from google import genai
from google.genai import types
from ddgs import DDGS
from app.models.domain import Preferences, Itinerary, DestinationSuggestion
from app.core.data import MOCK_ACTIVITIES
from dotenv import load_dotenv
from datetime import datetime, timedelta

import logging

load_dotenv()

# Configure logger (inherits config when running in server)
logger = logging.getLogger("travel_agent_server.agent")


# Prioritized list of models to try
MODEL_CANDIDATES = [
    "gemini-2.0-flash",
    "gemini-flash-latest",
    "gemini-1.5-flash",
    "gemini-pro-latest",
]

OPENROUTER_CANDIDATES = [
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
]


class TravelAgent:
    def __init__(self):
        self.activities = MOCK_ACTIVITIES
        self.client = None

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            print("WARNING: GOOGLE_API_KEY not found in environment.")
        else:
            self.client = genai.Client(api_key=api_key)

    def _get_calendar_context(self, preferences: Preferences) -> str:
        """
        Generates a string describing the day of week for each day of the trip.
        Used to prompt the LLM to check for opening hours.
        """
        if not preferences.start_date:
            return "No specific dates provided. Assume standard opening hours."

        try:
            # support both YYYY-MM-DD (standard) and DD-MM-YYYY (user request)
            start_dt = None
            for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
                try:
                    start_dt = datetime.strptime(preferences.start_date, fmt)
                    break
                except ValueError:
                    continue

            if not start_dt:
                return "Invalid date format. Assume standard opening hours."

            context = "SPECIFIC CALENDAR:\n"
            for i in range(preferences.days):
                current_dt = start_dt + timedelta(days=i)
                day_str = current_dt.strftime("%A, %B %d, %Y")
                context += f"- Day {i + 1}: {day_str}\n"

            context += "\nCRITICAL INSTRUCTION: Check opening hours for all venues for the specific DAY OF THE WEEK listed above.\n"
            context += "If a museum/location is CLOSED on that day (e.g. Louvre is closed Tuesdays), you MUST reschedule it to another day or choose a different activity."
            return context
        except Exception as e:
            print(f"WARNING: Date parsing failed: {e}")
            return ""

    def _search_real_image(self, query: str) -> str | None:
        """
        Searches for a real image URL using DuckDuckGo.
        Returns None if no image found or error occurs.
        """
        try:
            with DDGS() as ddgs:
                # Search for 1 image
                results = list(
                    ddgs.images(
                        query,
                        max_results=1,
                        safesearch="on",
                    )
                )
                if results and "image" in results[0]:
                    print(
                        f"DEBUG: Found real image for '{query}': {results[0]['image']}"
                    )
                    return results[0]["image"]
        except Exception as e:
            print(f"WARNING: Image search failed for '{query}': {e}")

        return None

    def _call_openrouter(self, prompt: str) -> str:
        """
        Fallback to OpenRouter if Google API fails.
        Tries multiple OpenRouter models in sequence.
        """
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

        last_error = None
        for model in OPENROUTER_CANDIDATES:
            print(f"DEBUG: Attempting OpenRouter fallback with {model}...")
            data = {"model": model, "messages": [{"role": "user", "content": prompt}]}

            try:
                req = urllib.request.Request(url, json.dumps(data).encode(), headers)
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode())
                    if "choices" in result and result["choices"]:
                        print(f"DEBUG: Success with OpenRouter ({model})!")
                        return str(result["choices"][0]["message"]["content"])
            except Exception as e:
                print(f"WARNING: OpenRouter ({model}) failed: {e}")
                last_error = e
                continue

        raise ValueError(f"All OpenRouter candidates failed. Last error: {last_error}")

    def _call_model_with_fallback(self, prompt: str) -> str:
        """
        Tries to generate content using models in preference order.
        Returns the text response of the first successful call.
        """
        # Try Google Direct First
        if self.client:
            # Enable Grounding
            config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )

            last_error = None
            for model_name in MODEL_CANDIDATES:
                try:
                    logger.info(f"DEBUG: Attempting with model: {model_name}...")
                    # Add timeout to avoid hanging indefinitely
                    config.response_mime_type = "application/json"
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=config,
                    )
                    logger.info(f"DEBUG: Success with {model_name}!")
                    return str(response.text)
                except Exception as e:
                    print(f"WARNING: Failed with {model_name}: {e}")
                    last_error = e
                    continue

        # If all Google models fail, try OpenRouter
        try:
            return self._call_openrouter(prompt)
        except Exception as or_error:
            # If everything fails, raise the last Google error if it exists, else OpenRouter error
            final_error = (
                last_error if "last_error" in locals() and last_error else or_error
            )
            raise RuntimeError(
                f"All model candidates failed. Last error: {final_error}"
            )

    def _check_constraints(
        self, itinerary: Itinerary, preferences: Preferences
    ) -> bool:
        """
        Validates the itinerary against preferences constraints.
        Updates the itinerary.valid and itinerary.validation_error fields.
        """
        # 1. Check Budget
        total_cost = itinerary.calculate_total_cost()
        if total_cost > preferences.budget:
            itinerary.valid = False
            itinerary.validation_error = (
                f"Total cost ${total_cost} exceeds budget ${preferences.budget}."
            )
            return False

        # 2. Check Days
        if len(itinerary.days) != preferences.days:
            itinerary.valid = False
            itinerary.validation_error = f"Itinerary has {len(itinerary.days)} days, expected {preferences.days}."
            return False

        itinerary.valid = True
        itinerary.validation_error = None
        return True

    def _parse_llm_response(self, response_text: str) -> Itinerary:
        """
        Parses JSON from LLM response, handling markdown code blocks.
        """
        try:
            cleaned_text = (
                response_text.replace("```json", "").replace("```", "").strip()
            )
            # Sometimes models return text before the JSON, try to find the first { or [
            start_idx = cleaned_text.find("{")
            end_idx = cleaned_text.rfind("}")

            # If object not found, check for list
            if start_idx == -1:
                start_idx = cleaned_text.find("[")
                end_idx = cleaned_text.rfind("]")

            if start_idx != -1:
                # Use raw_decode to parse the JSON and ignore trailing text
                # clean from the start of the JSON-like structure
                candidate_json = cleaned_text[start_idx:]
                try:
                    data, _ = json.JSONDecoder().raw_decode(candidate_json)
                except Exception:
                    # Fallback to previous logic if raw_decode fails (e.g. if it's incomplete)
                    if end_idx != -1:
                        cleaned_text = cleaned_text[start_idx : end_idx + 1]
                        data = json.loads(cleaned_text)
                    else:
                        raise
            else:
                data = json.loads(cleaned_text)

            # --- Fuzzy Normalization Start ---

            # 1. unwrapping: Find the "days" list
            if "city" not in data and "days" not in data:
                # Recursively search for a dictionary containing "days"
                def find_days_dict(obj):
                    if isinstance(obj, dict):
                        if "days" in obj and isinstance(obj["days"], list):
                            return obj
                        for v in obj.values():
                            res = find_days_dict(v)
                            if res:
                                return res
                    return None

                found_data = find_days_dict(data)
                if found_data:
                    data = found_data

            # 2. Fix City if missing
            if "city" not in data:
                data["city"] = "Unknown"

            # 3. Normalize Days and Activities
            if "days" in data and isinstance(data["days"], list):
                for day in data["days"]:
                    # Handle Day structure quirks
                    if "day" in day and "day_number" not in day:
                        day["day_number"] = day.pop("day")

                    if "activities" in day and isinstance(day["activities"], list):
                        for activity in day["activities"]:
                            # Normalize Cost (LLM often returns strings like "$10" or "Free")
                            cost_val = activity.get("cost", 0)
                            if isinstance(cost_val, str):
                                import re

                                # Extract first number found
                                nums = re.findall(r"[-+]?\d*\.\d+|\d+", cost_val)
                                if nums:
                                    activity["cost"] = float(nums[0])
                                else:
                                    activity["cost"] = 0.0

                            # Normalize Duration
                            # Capture the raw string first for display
                            if "duration" in activity and isinstance(
                                activity["duration"], str
                            ):
                                activity["duration_str"] = activity["duration"]
                            elif "duration_hours" in activity and isinstance(
                                activity["duration_hours"], str
                            ):
                                activity["duration_str"] = activity["duration_hours"]

                            dur_val = activity.get(
                                "duration", activity.get("duration_hours", 0)
                            )

                            # Remove 'duration' to prevent Pydantic alias collision
                            if "duration" in activity:
                                activity.pop("duration")

                            if isinstance(dur_val, str):
                                import re

                                nums = re.findall(r"[-+]?\d*\.\d+|\d+", dur_val)
                                if nums:
                                    activity["duration_hours"] = float(nums[0])
                                else:
                                    activity["duration_hours"] = 1.0  # Default
                            elif isinstance(dur_val, (int, float)):
                                activity["duration_hours"] = float(dur_val)

                            # Ensure required fields exist
                            if "duration_hours" not in activity:
                                activity["duration_hours"] = 1.0
                            if "duration_str" not in activity:
                                # Fallback if no string provided
                                activity["duration_str"] = (
                                    f"{activity['duration_hours']} hours"
                                )

                            if "tags" not in activity:
                                activity["tags"] = ["General"]
                            if "description" not in activity:
                                activity["description"] = activity.get(
                                    "name", "Activity"
                                )
                            if (
                                "image_url" not in activity
                                or not activity["image_url"]
                                or True
                            ):  # Force refresh
                                # 1. Try Real Search (DDG)
                                # We prioritize this over LLM hallucinations
                                real_image = self._search_real_image(
                                    f"{activity['name']} {data.get('city', '')}"
                                )
                                if real_image:
                                    activity["image_url"] = real_image
                                else:
                                    # 2. Dynamic fallback (Pollinations)
                                    import urllib.parse

                                    safe_query = urllib.parse.quote(
                                        f"{activity['name']} {data.get('city', '')} aesthetic"
                                    )
                                    activity["image_url"] = (
                                        f"https://image.pollinations.ai/prompt/{safe_query}?width=800&height=600&nologo=true"
                                    )

            # --- Fuzzy Normalization End ---

            # Lowercase keys if needed (some models return capitalized keys)
            # (Skipping global lowercase as it breaks mixedCase keys if we rely on normalized ones)
            # data = {k.lower(): v for k, v in data.items()}

            return Itinerary(**data)
        except Exception as e:
            logger.error(f"ERROR parsing LLM response: {e}")
            logger.error(
                f"RAW Response: {response_text}"
            )  # Log raw response for debugging
            # If everything fails, return empty structure to avoid 500 error,
            # but logged error will help debug.
            return Itinerary(city="Unknown", days=[])

    def generate_initial_plan(self, preferences: Preferences) -> Itinerary:
        """
        Uses Google Gen AI to generate the initial plan based on available activities.
        """
        if preferences.city.lower() == "paris":
            activities_context = f"""
             AVAILABLE ACTIVITIES (You must ONLY use these, do not invent new ones):
             {json.dumps([a.model_dump() for a in self.activities], indent=2)}
             """
        else:
            activities_context = """
             AVAILABLE ACTIVITIES:
             You are free to find real activities using Google Search.
             
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

        prompt = f"""
        You are an expert travel agent. Create a detailed, day-by-day itinerary for {preferences.city}.
        User Budget: ${preferences.budget}
        Trip Duration: {preferences.days} days
        Interests: {", ".join(preferences.interests)}

        CRITICAL INSTRUCTIONS:
        1. You are a expert travel agent. Create a detailed, day-by-day itinerary.
        2. MULTI-CITY LOGIC: If the user requests multiple destinations (e.g. 'Paris and London'), split the days logically between them. 
           - You MUST specify the 'city' field for EACH DayPlan object so we know where the user is.
           - Account for travel time between cities as an activity (e.g. 'Train to London').
        3. REALISM: Account for opening hours (closed on Mondays?) and logical travel times between venues.
        4. IMAGES: For every activity, generate a specific, search-friendly 'image_url' query (e.g. 'Eiffel Tower sunset').
        5. COSTS: Estimate costs realistically. '0' for free activities. Ensure total stays under budget.
        6. VALID VALID JSON: You must return PURE JSON matching the 'Itinerary' pydantic schema. No markdown, no pre-amble.

        TRIP DATES & OPENING HOURS:
        {self._get_calendar_context(preferences)}

        {activities_context}

        OUTPUT FORMAT:
        Return ONLY a JSON object matching this structure:
        {{
            "city": "{preferences.city}",
            "days": [
                {{
                    "day_number": 1,
                    "activities": [ 
                        {{
                            "name": "Activity Name",
                            "description": "Short description",
                            "cost": 20,
                            "duration": "1-2 hours", 
                            "image_url": "https://example.com/real-photo.jpg",
                            "tags": ["Tag1", "Tag2"]
                        }}
                    ]
                }}
            ]
        }}
        """

        print("DEBUG: Google ADK Agent generating initial plan...")
        response_text = self._call_model_with_fallback(prompt)
        return self._parse_llm_response(response_text)

    def refine_plan(
        self, previous_plan: Itinerary, error: str, preferences: Preferences
    ) -> Itinerary:
        """
        Asks Google Gen AI to check the error and generate a new plan.
        """
        if preferences.city.lower() == "paris":
            activities_context = f"""
             AVAILABLE ACTIVITIES:
             {json.dumps([a.model_dump() for a in self.activities], indent=2)}
             """
        else:
            activities_context = """
             AVAILABLE ACTIVITIES:
             You are free to find real activities using Google Search.
             **REMINDER**: Estimate costs in LOCAL currency, then convert to USD. Be realistic (e.g. Mumbai street food is <$5).
             """

        extra_instruction = ""
        if "0 days" in error or "valid JSON" in error:
            extra_instruction = """
            CRITICAL: The previous output was NOT valid JSON or was empty.
            You MUST return a pure JSON object. 
            Do NOT support markdown. 
            Do NOT add explanations.
            """

        prompt = f"""
        The previous itinerary for {preferences.city} was INVALID.
        Error: {error}
        
        Previous Plan Total Cost: ${previous_plan.total_cost}
        Budget: ${preferences.budget}
        
        DATES:
        {self._get_calendar_context(preferences)}

        Please fix the plan by removing or swapping activities to meet the constraints.
        
        {extra_instruction}
        
        {activities_context}

        OUTPUT FORMAT:
        Return a valid JSON object matching the Itinerary structure.
        """

        print(f"DEBUG: Calling Google Gen AI to fix error: {error}")
        response_text = self._call_model_with_fallback(prompt)
        return self._parse_llm_response(response_text)

    def plan_trip_stream(self, preferences: Preferences):
        """
        Generates the itinerary following the Google ADK 4-Step Agentic Process.
        1. Break down plan & allocate activities.
        2. Check constraints.
        3. Re-plan if needed.
        4. Finalize.
        """
        # Step 1: Breakdown & Allocation
        yield "Google ADK Agent: Step 1 - Breaking plan into days & allocating activities..."
        itinerary = self.generate_initial_plan(preferences)
        cost = itinerary.calculate_total_cost()
        yield f"Initial allocation complete. Estimated Cost: ${cost}"

        # Step 2: Constraints
        yield "Google ADK Agent: Step 2 - Verifying budget & time constraints..."
        is_valid = self._check_constraints(itinerary, preferences)

        # Step 3: Re-planning (Feedback Loop)
        max_retries = 3
        attempts = 0
        if not is_valid:
            yield "Google ADK Agent: Step 3 - Budget exceeded. Initiating Re-planning Loop..."

        while not is_valid and attempts < max_retries:
            attempts += 1
            yield f"Constraint Violation: {itinerary.validation_error}"
            yield f"Re-planning attempt {attempts}/{max_retries}..."

            itinerary = self.refine_plan(
                itinerary, itinerary.validation_error or "Unknown Validation Error", preferences
            )
            itinerary.calculate_total_cost()

            is_valid = self._check_constraints(itinerary, preferences)

        if not is_valid:
            yield "Warning: Constraints not fully met after re-planning. Returning best effort."

        # Step 4: Finalize
        yield "Google ADK Agent: Step 4 - Finalizing itinerary & generating artifacts..."
        yield itinerary

    def plan_trip(self, preferences: Preferences) -> Itinerary:
        """
        Wrapper for non-streaming callers.
        """
        result = None
        for item in self.plan_trip_stream(preferences):
            if isinstance(item, Itinerary):
                result = item
            elif isinstance(item, str):
                print(f"DEBUG: {item}")
        if result is None:
             # Should practically never happen given the stream logic always yields status then result
             raise RuntimeError("Planning failed to produce an itinerary result.")
        return result
