import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.agent import TravelAgent, budget_targets
from app.core.destinations import recommend_destinations
from app.core.parser import parse_llm_response
from app.models.domain import Activity, CostBreakdown, DayPlan, Itinerary, Preferences


VALID_JSON_RESPONSE = """
{
    "city": "London",
    "days": [
        {
            "day_number": 1,
            "activities": [
                {"name": "Big Ben", "description": "Iconic clock tower", "tags": ["Sightseeing"], "duration_hours": 1.0, "cost": 0.0, "image_url": "https://example.com/big-ben.jpg"}
            ]
        }
    ]
}
"""


@pytest.fixture
def planner():
    """Returns a TravelAgent instance with mocked OpenAI client."""
    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
        patch("app.core.agent.OpenAI") as mock_client,
    ):
        agent = TravelAgent()
        agent.client = mock_client.return_value
        return agent


def test_initial_plan_success(planner):
    """Verifies that plan_trip parses a valid JSON response correctly."""
    mock_response = MagicMock()
    mock_response.output_text = VALID_JSON_RESPONSE
    planner.client.responses.create.return_value = mock_response

    prefs = Preferences(city="London", budget=1000, days=1, interests=["History"])
    itinerary = planner.plan_trip(prefs)

    assert itinerary.city == "London"
    assert len(itinerary.days) == 1
    assert itinerary.days[0].activities[0].name == "Big Ben"
    request_kwargs = planner.client.responses.create.call_args.kwargs
    assert request_kwargs["tools"] == [{"type": "web_search"}]
    assert "text" not in request_kwargs


def test_json_parsing_resilience(planner):
    """Verifies parsing logic handles Markdown wrapping."""
    markdown_response = f"Here is your plan:\n```json\n{VALID_JSON_RESPONSE}\n```"

    itinerary = parse_llm_response(markdown_response, image_search=lambda _: None)
    assert itinerary.city == "London"
    assert len(itinerary.days) == 1


def test_openai_model_candidate_fallback(planner):
    """Verifies fallback logic when the first OpenAI model candidate fails."""
    mock_response = MagicMock()
    mock_response.output_text = VALID_JSON_RESPONSE
    planner.client.responses.create.side_effect = [
        Exception("Quota Exceeded"),
        mock_response,
    ]

    prefs = Preferences(city="London", budget=1000, days=1, interests=["History"])
    itinerary = planner.plan_trip(prefs)

    assert planner.client.responses.create.call_count == 2
    assert (
        planner.client.responses.create.call_args_list[0].kwargs["model"]
        == "gpt-5.4-mini"
    )
    assert (
        planner.client.responses.create.call_args_list[1].kwargs["model"]
        == "gpt-5.4-nano"
    )
    assert itinerary.city == "London"


def test_invalid_schema_response_is_repaired_with_json_mode(planner):
    invalid_response = MagicMock()
    invalid_response.output_text = '{"destination": "Rotterdam, Netherlands"}'
    repaired_response = MagicMock()
    repaired_response.output_text = VALID_JSON_RESPONSE
    planner.client.responses.create.side_effect = [invalid_response, repaired_response]

    prefs = Preferences(city="London", budget=1000, days=1, interests=["History"])
    itinerary = planner.generate_initial_plan(prefs)

    assert itinerary.city == "London"
    assert planner.client.responses.create.call_count == 2

    planning_kwargs = planner.client.responses.create.call_args_list[0].kwargs
    assert planning_kwargs["tools"] == [{"type": "web_search"}]
    assert "text" not in planning_kwargs

    repair_kwargs = planner.client.responses.create.call_args_list[1].kwargs
    assert "tools" not in repair_kwargs
    assert repair_kwargs["text"] == {"format": {"type": "json_object"}}
    assert "Convert the following travel itinerary response" in repair_kwargs["input"]


def test_missing_openai_api_key_leaves_client_unset():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("app.core.agent.OpenAI") as mock_openai,
    ):
        planner = TravelAgent()

    assert planner.client is None
    mock_openai.assert_not_called()

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        planner._call_model_with_fallback("Return JSON")


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


def test_budget_targets_allocate_full_hard_cap():
    prefs = Preferences(city="Lisbon", budget=500, days=2, interests=["Food"])

    targets = budget_targets(prefs)

    assert targets == {
        "transport": 125,
        "stay": 175,
        "food": 100,
        "activities": 100,
        "total": 500,
    }


def test_work_friendly_budget_targets_prioritize_stay():
    prefs = Preferences(
        city="Lisbon",
        budget=500,
        days=2,
        interests=["Food"],
        work_friendly=True,
    )

    targets = budget_targets(prefs)

    assert targets["stay"] == 200
    assert sum(targets[key] for key in ("transport", "stay", "food", "activities")) == 500


def test_parser_normalizes_current_schema(planner):
    raw_response = """
    {
        "city": "Lisbon",
        "vibe_rationale": "Sunny tiles, cafes, and coastal viewpoints.",
        "cost_breakdown": {
            "transport": "$120",
            "stay": "$240",
            "food": "$90",
            "activities": "$50",
            "total": "$500",
            "remaining_budget": "$100"
        },
        "days": [
            {
                "day_number": 1,
                "activities": [
                    {"name": "Miradouro walk", "description": "Viewpoint route", "cost": "$50", "duration_hours": "2 hours"}
                ]
            }
        ]
    }
    """

    itinerary = parse_llm_response(raw_response, image_search=lambda _: None)

    assert itinerary.city == "Lisbon"
    assert itinerary.cost_breakdown.transport == 120
    assert itinerary.cost_breakdown.stay == 240
    assert itinerary.cost_breakdown.food == 90
    assert itinerary.cost_breakdown.activities == 50
    assert itinerary.cost_breakdown.total == 500


def test_parser_handles_wrapped_current_payload_and_generated_image(planner):
    raw_response = """
    ```json
    {
        "city": "Amsterdam",
        "budget_notes": "Lean on transit and free walking routes.",
        "cost_breakdown": {
            "transport": "$40",
            "stay": "$220",
            "food": "$90",
            "activities": "$20",
            "total": "$370"
        },
        "days": [
            {
                "day_number": 1,
                "activities": [
                    {
                        "name": "Canal walk",
                        "cost": "Free",
                        "duration_hours": "2.5 hours"
                    }
                ]
            }
        ]
    }
    ```
    """

    itinerary = parse_llm_response(raw_response, image_search=lambda _: None)

    activity = itinerary.days[0].activities[0]
    assert itinerary.city == "Amsterdam"
    assert itinerary.budget_notes == "Lean on transit and free walking routes."
    assert activity.cost == 0
    assert activity.duration_hours == 2.5
    assert activity.tags == ["General"]
    assert activity.description == "Canal walk"
    assert activity.image_url is not None
    assert "pollinations.ai" in activity.image_url


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


def test_constraint_checking_requires_activity_category_match(planner):
    itinerary = Itinerary(
        city="Lisbon",
        cost_breakdown=CostBreakdown(
            transport=100,
            stay=200,
            food=80,
            activities=10,
        ),
        days=[
            DayPlan(
                day_number=1,
                activities=[
                    Activity(
                        name="Food walk",
                        description="Market route",
                        tags=["Food"],
                        duration_hours=2.0,
                        cost=25.0,
                    )
                ],
            )
        ],
    )
    prefs = Preferences(city="Lisbon", budget=500, days=1, interests=["Food"])

    is_valid = planner._check_constraints(itinerary, prefs)

    assert is_valid is False
    assert itinerary.validation_error is not None
    assert "Activity costs" in itinerary.validation_error


def test_constraint_checking_rejects_unrequested_country_for_multi_city(planner):
    itinerary = Itinerary(
        city="Bangkok, Thailand",
        recommended_destination="Bangkok, Thailand",
        cost_breakdown=CostBreakdown(
            transport=50,
            stay=100,
            food=40,
            activities=20,
        ),
        days=[
            DayPlan(
                day_number=1,
                city="Bangkok",
                activities=[
                    Activity(
                        name="Temple walk",
                        description="Bangkok old town route",
                        tags=["History"],
                        duration_hours=2.0,
                        cost=20.0,
                    )
                ],
            )
        ],
    )
    prefs = Preferences(
        city="Rotterdam, Amsterdam",
        budget=500,
        days=1,
        interests=["History"],
    )

    is_valid = planner._check_constraints(itinerary, prefs)

    assert is_valid is False
    assert itinerary.validation_error is not None
    assert "does not match requested destination" in itinerary.validation_error


def test_plan_trip_stream_yields_status_events_then_itinerary(planner):
    itinerary = Itinerary(
        city="Porto",
        cost_breakdown=CostBreakdown(
            transport=50,
            stay=100,
            food=40,
            activities=20,
            total=210,
            remaining_budget=90,
        ),
        days=[
            DayPlan(
                day_number=1,
                activities=[
                    Activity(
                        name="Riverside walk",
                        description="Douro viewpoint route",
                        tags=["Views"],
                        duration_hours=2.0,
                        cost=20.0,
                    )
                ],
            )
        ],
    )

    with patch.object(planner, "generate_initial_plan", return_value=itinerary):
        events = list(
            planner.plan_trip_stream(
                Preferences(city="Porto", budget=300, days=1, interests=["Views"])
            )
        )

    assert all(isinstance(event, str) for event in events[:-1])
    assert isinstance(events[-1], Itinerary)
    assert events[-1].city == "Porto"


def test_no_city_vibe_request_receives_destination_suggestions(planner):
    prefs = Preferences(
        budget=1500,
        days=1,
        interests=["Food"],
        vibe="ancient town cafes beach",
    )
    expected_city = recommend_destinations(prefs)[0].city
    captured = {}

    def fake_initial(preferences, destination_suggestions):
        captured["preferences"] = preferences
        captured["suggestions"] = destination_suggestions
        return Itinerary(
            city=preferences.city,
            cost_breakdown=CostBreakdown(
                transport=100,
                stay=200,
                food=80,
                activities=20,
            ),
            days=[
                DayPlan(
                    day_number=1,
                    activities=[
                        Activity(
                            name="Old town cafe walk",
                            description="Compact food route",
                            cost=20,
                        )
                    ],
                )
            ],
        )

    with patch.object(planner, "generate_initial_plan", side_effect=fake_initial):
        events = list(planner.plan_trip_stream(prefs))

    result = events[-1]
    assert isinstance(result, Itinerary)
    assert captured["preferences"].city == expected_city
    assert result.city == expected_city
    assert result.recommended_destination == expected_city
    assert len(result.destination_suggestions) == 3


def test_over_budget_final_plan_remains_invalid(planner):
    itinerary = Itinerary(
        city="Lisbon",
        cost_breakdown=CostBreakdown(
            transport=300,
            stay=300,
            food=100,
            activities=50,
        ),
        days=[
            DayPlan(
                day_number=1,
                activities=[Activity(name="Dinner", description="Meal", cost=50)],
            )
        ],
    )

    prefs = Preferences(city="Lisbon", budget=500, days=1, interests=["Food"])

    with (
        patch.object(planner, "generate_initial_plan", return_value=itinerary),
        patch.object(planner, "refine_plan", return_value=itinerary),
    ):
        events = list(planner.plan_trip_stream(prefs))

    result = events[-1]
    assert isinstance(result, Itinerary)
    assert result.valid is False
    assert result.validation_error is not None
    assert "exceeds budget" in result.validation_error


def test_over_budget_plan_is_refined_to_valid_itinerary(planner):
    initial = Itinerary(
        city="Lisbon",
        cost_breakdown=CostBreakdown(
            transport=300,
            stay=300,
            food=100,
            activities=50,
        ),
        days=[
            DayPlan(
                day_number=1,
                activities=[Activity(name="Dinner", description="Meal", cost=50)],
            )
        ],
    )
    refined = Itinerary(
        city="Lisbon",
        cost_breakdown=CostBreakdown(
            transport=100,
            stay=180,
            food=70,
            activities=50,
        ),
        days=[
            DayPlan(
                day_number=1,
                activities=[Activity(name="Market walk", description="Food", cost=50)],
            )
        ],
    )

    prefs = Preferences(city="Lisbon", budget=500, days=1, interests=["Food"])

    with (
        patch.object(planner, "generate_initial_plan", return_value=initial),
        patch.object(planner, "refine_plan", return_value=refined) as mock_refine,
    ):
        events = list(planner.plan_trip_stream(prefs))

    result = events[-1]
    assert isinstance(result, Itinerary)
    assert mock_refine.call_count == 1
    assert result.valid is True
    assert result.cost_breakdown.total == 400
