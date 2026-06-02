import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import TravelAgent
from models import Activity, CostBreakdown, DayPlan, Itinerary, Preferences


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
    """Returns a TravelAgent instance with mocked Google Client."""
    with patch("agent.genai.Client") as mock_client:
        agent = TravelAgent()
        agent.client = mock_client
        return agent


def test_initial_plan_success(planner):
    """Verifies that plan_trip parses a valid JSON response correctly."""
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
    planner.client.models.generate_content.side_effect = Exception("Quota Exceeded")

    with patch.object(
        planner, "_call_openrouter", return_value=VALID_JSON_RESPONSE
    ) as mock_or:
        prefs = Preferences(city="London", budget=1000, days=1, interests=["History"])
        itinerary = planner.plan_trip(prefs)

        mock_or.assert_called_once()
        assert itinerary.city == "London"


def test_constraint_checking(planner):
    """Verifies that validation logic catches budget issues."""
    itinerary = Itinerary(
        city="London",
        days=[
            DayPlan(
                day_number=1,
                activities=[
                    Activity(
                        name="Luxury Dinner",
                        description="Expensive meal",
                        tags=["Food"],
                        duration_hours=2.0,
                        cost=2000.0,
                    )
                ],
            )
        ],
    )

    prefs = Preferences(city="London", budget=500, days=1, interests=["Food"])

    is_valid = planner._check_constraints(itinerary, prefs)

    assert is_valid is False
    assert (
        itinerary.validation_error is not None
        and "exceeds budget" in itinerary.validation_error
    )


def test_preferences_support_vibe_discovery_without_city():
    prefs = Preferences(
        budget=700,
        days=3,
        interests=["Food"],
        vibe="quiet coastal cafes",
        work_friendly=True,
    )

    assert prefs.city is None
    assert prefs.vibe == "quiet coastal cafes"
    assert prefs.work_friendly is True


def test_cost_breakdown_model_calculates_remaining_budget():
    breakdown = CostBreakdown(transport=100, stay=200, food=90, activities=60)

    assert breakdown.calculate_total(budget=500) == 450
    assert breakdown.remaining_budget == 50


def test_parser_normalizes_destination_and_budget_breakdown(planner):
    raw_response = """
    {
        "recommended_destination": "Lisbon",
        "vibe_rationale": "Sunny tiles, cafes, and coastal viewpoints.",
        "budget_breakdown": {
            "transportation": "$120",
            "accommodation": "$240",
            "meals": "$90",
            "activities": "$50",
            "total": "$500",
            "remaining_budget": "$100"
        },
        "days": [
            {
                "day": 1,
                "activities": [
                    {"name": "Miradouro walk", "description": "Viewpoint route", "cost": "$50", "duration": "2 hours"}
                ]
            }
        ]
    }
    """

    with patch.object(planner, "_search_real_image", return_value=None):
        itinerary = planner._parse_llm_response(raw_response)

    assert itinerary.city == "Lisbon"
    assert itinerary.recommended_destination == "Lisbon"
    assert itinerary.cost_breakdown.transport == 120
    assert itinerary.cost_breakdown.stay == 240
    assert itinerary.cost_breakdown.food == 90
    assert itinerary.cost_breakdown.activities == 50
    assert itinerary.cost_breakdown.total == 500


def test_constraint_checking_uses_category_total(planner):
    itinerary = Itinerary(
        city="Lisbon",
        cost_breakdown=CostBreakdown(transport=200, stay=250, food=150, activities=50),
        days=[
            DayPlan(
                day_number=1,
                activities=[
                    Activity(
                        name="Viewpoint",
                        description="Walk",
                        tags=["Views"],
                        duration_hours=2.0,
                        cost=50.0,
                    )
                ],
            )
        ],
    )
    prefs = Preferences(budget=600, days=1, interests=["Views"])

    is_valid = planner._check_constraints(itinerary, prefs)

    assert is_valid is False
    assert itinerary.validation_error is not None
    assert "exceeds budget" in itinerary.validation_error
