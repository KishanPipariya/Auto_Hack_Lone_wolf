import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.agent import TravelAgent, budget_targets
from app.core.destinations import recommend_destinations
from app.core.parser import parse_llm_response
from app.core.prompts import (
    budget_targets_context,
    initial_plan_prompt,
    json_repair_prompt,
    refinement_prompt,
)
from app.models.domain import (
    Activity,
    CostBreakdown,
    DayPlan,
    DestinationSuggestion,
    Itinerary,
    Preferences,
)


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


def test_local_budget_constraint_error_omits_dollar_symbol(planner):
    itinerary = Itinerary(
        city="Tokyo",
        days=[
            DayPlan(
                day_number=1,
                activities=[
                    Activity(name="Dinner", description="Meal", cost=60000.0)
                ],
            )
        ],
    )

    prefs = Preferences(city="Tokyo", local_budget=50000, days=1, interests=["Food"])

    is_valid = planner._check_constraints(itinerary, prefs)

    assert is_valid is False
    assert itinerary.validation_error is not None
    assert "exceeds budget" in itinerary.validation_error
    assert "$" not in itinerary.validation_error


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


def test_budget_targets_context_includes_nonzero_daily_target():
    prefs = Preferences(city="Lisbon", budget=1, days=3, interests=["Food"])

    context = budget_targets_context(prefs, budget_targets(prefs))

    assert "Daily target: about $0.33 per day across 3 day(s)." in context
    assert "Daily target: about $0 per day" not in context


def test_local_budget_prompts_keep_costs_in_local_currency():
    prefs = Preferences(
        city="Tokyo",
        local_budget=50000,
        days=2,
        interests=["Food"],
    )

    prompt = initial_plan_prompt(prefs, [], [], budget_targets(prefs))

    assert "Do not use USD" in prompt
    assert "do not convert to USD" in prompt
    assert "destination's local currency only" in prompt
    assert "CONVERT all costs to USD" not in prompt
    assert "USD equivalent" not in prompt
    assert "output only USD" not in prompt.lower()


def test_local_budget_prompt_suggestion_context_omits_dollar_symbol():
    prefs = Preferences(
        local_budget=50000,
        days=2,
        interests=["Food"],
        vibe="street food",
    )
    suggestions = [
        DestinationSuggestion(
            city="Tokyo",
            country="Japan",
            rationale="Dense local food scene.",
            estimated_total_cost=45000,
            tags=["Food"],
        )
    ]

    prompt = initial_plan_prompt(prefs, [], suggestions, budget_targets(prefs))

    assert "estimated total 45000 in the destination's local currency" in prompt
    assert "estimated total $" not in prompt


def test_local_budget_refinement_and_repair_do_not_reintroduce_usd():
    prefs = Preferences(
        city="Tokyo",
        local_budget=50000,
        days=1,
        interests=["Food"],
    )
    previous_plan = Itinerary(
        city="Tokyo",
        cost_breakdown=CostBreakdown(total=60000),
        total_cost=60000,
        days=[
            DayPlan(
                day_number=1,
                activities=[
                    Activity(name="Ramen", description="Lunch", cost=1200),
                ],
            )
        ],
    )

    refine = refinement_prompt(
        previous_plan,
        "Total cost exceeds budget",
        prefs,
        [],
        [],
        budget_targets(prefs),
    )
    repair = json_repair_prompt("{}", prefs)

    combined = f"{refine}\n{repair}"
    assert "Do not use USD" in combined
    assert "do not convert to USD" in combined
    assert "cost_usd/estimated_cost_usd" not in combined
    assert "number in USD" not in combined
    assert "USD equivalent" not in combined


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


def test_constraint_checking_requires_day_city_coverage_for_multi_city(planner):
    itinerary = Itinerary(
        city="Rotterdam, Amsterdam",
        recommended_destination="Rotterdam, Amsterdam",
        cost_breakdown=CostBreakdown(
            transport=50,
            stay=100,
            food=40,
            activities=20,
        ),
        days=[
            DayPlan(
                day_number=1,
                city="Amsterdam",
                activities=[
                    Activity(
                        name="Canal walk",
                        description="Amsterdam route",
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
    assert "each requested city" in itinerary.validation_error


def test_constraint_checking_accepts_multi_city_day_coverage(planner):
    itinerary = Itinerary(
        city="Rotterdam, Amsterdam",
        recommended_destination="Rotterdam, Amsterdam",
        cost_breakdown=CostBreakdown(
            transport=50,
            stay=100,
            food=40,
            activities=20,
        ),
        days=[
            DayPlan(
                day_number=1,
                city="Rotterdam",
                activities=[
                    Activity(
                        name="Markthal walk",
                        description="Rotterdam market route",
                        tags=["Food"],
                        duration_hours=2.0,
                        cost=10.0,
                    )
                ],
            ),
            DayPlan(
                day_number=2,
                city="Amsterdam",
                activities=[
                    Activity(
                        name="Canal walk",
                        description="Amsterdam route",
                        tags=["History"],
                        duration_hours=2.0,
                        cost=10.0,
                    )
                ],
            ),
        ],
    )
    prefs = Preferences(
        city="Rotterdam, Amsterdam",
        budget=500,
        days=2,
        interests=["Food", "History"],
    )

    is_valid = planner._check_constraints(itinerary, prefs)

    assert is_valid is True
    assert itinerary.city == "Rotterdam, Amsterdam"


def test_constraint_checking_ignores_short_partial_destination_fragment(planner):
    itinerary = Itinerary(
        city="Amsterdam, Netherlands",
        recommended_destination="Amsterdam, Netherlands",
        cost_breakdown=CostBreakdown(
            transport=50,
            stay=100,
            food=40,
            activities=20,
        ),
        days=[
            DayPlan(
                day_number=1,
                city="Amsterdam",
                activities=[
                    Activity(
                        name="Canal walk",
                        description="Amsterdam route",
                        tags=["History"],
                        duration_hours=2.0,
                        cost=20.0,
                    )
                ],
            )
        ],
    )
    prefs = Preferences(
        city="Amsterdam, Rott",
        budget=500,
        days=1,
        interests=["History"],
    )

    is_valid = planner._check_constraints(itinerary, prefs)

    assert is_valid is True
    assert itinerary.city == "Amsterdam, Rott"


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


def test_local_budget_plan_stream_status_omits_dollar_symbol(planner):
    itinerary = Itinerary(
        city="Tokyo",
        cost_breakdown=CostBreakdown(
            transport=10000,
            stay=20000,
            food=8000,
            activities=5000,
            total=43000,
            remaining_budget=7000,
        ),
        days=[
            DayPlan(
                day_number=1,
                activities=[
                    Activity(name="Ramen walk", description="Food route", cost=5000)
                ],
            )
        ],
    )

    with patch.object(planner, "generate_initial_plan", return_value=itinerary):
        events = list(
            planner.plan_trip_stream(
                Preferences(
                    city="Tokyo",
                    local_budget=50000,
                    days=1,
                    interests=["Food"],
                )
            )
        )

    status_text = "\n".join(event for event in events if isinstance(event, str))
    assert "Estimated Cost:" in status_text
    assert "$" not in status_text


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
