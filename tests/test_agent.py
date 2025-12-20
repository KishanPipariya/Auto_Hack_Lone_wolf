
import pytest
from unittest.mock import MagicMock, patch
from agent import TravelPlanner
from models import Preferences, Itinerary

# Mock data for valid plan
VALID_JSON_RESPONSE = """
{
    "city": "London",
    "days": [
        {
            "day_number": 1,
            "activities": [
                {"name": "Big Ben", "description": "Iconic clock tower", "tags": ["Sightseeing"], "duration_hours": 1.0, "cost": 0.0}
            ]
        }
    ]
}
"""

@pytest.fixture
def planner():
    """Returns a TravelPlanner instance with mocked Google Client."""
    with patch("agent.genai.Client") as mock_client:
        planner = TravelPlanner()
        planner.client = mock_client
        return planner

def test_initial_plan_success(planner):
    """Verifies that plan_trip parses a valid JSON response correctly."""
    
    # Mock the Gemini API response
    mock_response = MagicMock()
    mock_response.text = VALID_JSON_RESPONSE
    planner.client.models.generate_content.return_value = mock_response

    prefs = Preferences(city="London", budget=1000, days=1, interests=["History"])
    itinerary = planner.plan_trip(prefs)

    assert itinerary.city == "London"
    assert len(itinerary.days) == 1
    assert itinerary.days[0].activities[0].name == "Big Ben"

def test_json_parsing_resilience(planner):
    """Verifies parsing logic handles Markdown wrapping."""
    
    markdown_response = f"Here is your plan:\n```json\n{VALID_JSON_RESPONSE}\n```"
    
    itinerary = planner._parse_llm_response(markdown_response)
    assert itinerary.city == "London"
    assert len(itinerary.days) == 1

def test_openrouter_fallback(planner):
    """Verifies fallback logic when Google API fails."""
    
    # Mock Google API to raise Exception
    planner.client.models.generate_content.side_effect = Exception("Quota Exceeded")
    
    # Mock OpenRouter call
    with patch.object(planner, "_call_openrouter", return_value=VALID_JSON_RESPONSE) as mock_or:
        prefs = Preferences(city="London", budget=1000, days=1, interests=["History"])
        itinerary = planner.plan_trip(prefs)
        
        # Verify Fallback was called
        mock_or.assert_called_once()
        assert itinerary.city == "London"

def test_constraint_checking(planner):
    """Verifies that validation logic catches budget issues."""
    
    # Create an expensive itinerary
    itinerary = Itinerary(
        city="London",
        days=[
            {
                "day_number": 1,
                "activities": [
                    {"name": "Luxury Dinner", "description": "Expensive meal", "tags": ["Food"], "duration_hours": 2.0, "cost": 2000.0}
                ]
            }
        ]
    )
    
    prefs = Preferences(city="London", budget=500, days=1, interests=["Food"])
    
    is_valid = planner._check_constraints(itinerary, prefs)
    
    assert is_valid is False
    assert "exceeds budget" in itinerary.validation_error
