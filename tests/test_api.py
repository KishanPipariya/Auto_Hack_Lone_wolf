import json
import os
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fast_api_server import agent, app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_plan_endpoint_success():
    """Verifies POST /plan returns a valid itinerary."""
    with patch.object(agent, "plan_trip") as mock_plan:
        from app.models.domain import CostBreakdown, Itinerary

        real_itinerary = Itinerary(
            city="Test City",
            recommended_destination="Test City",
            cost_breakdown=CostBreakdown(
                transport=20,
                stay=30,
                food=25,
                activities=25,
                total=100,
                remaining_budget=400,
            ),
            days=[],
            valid=True,
        )
        real_itinerary.total_cost = 100.0

        mock_plan.return_value = real_itinerary

        response = client.post(
            "/plan",
            json={
                "city": "Test City",
                "budget": 500,
                "days": 1,
                "interests": ["Testing"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["city"] == "Test City"
        assert data["cost_breakdown"]["total"] == 100

        prefs = mock_plan.call_args.args[0]
        assert prefs.city == "Test City"


def test_plan_endpoint_allows_city_omitted_with_vibe():
    from app.models.domain import CostBreakdown, Itinerary

    with patch.object(agent, "plan_trip") as mock_plan:
        mock_plan.return_value = Itinerary(
            city="Lisbon",
            recommended_destination="Lisbon",
            vibe_rationale="Coastal cafe pace with art streets.",
            cost_breakdown=CostBreakdown(
                transport=120,
                stay=200,
                food=90,
                activities=60,
                total=470,
                remaining_budget=30,
            ),
            days=[],
            valid=True,
        )

        response = client.post(
            "/plan",
            json={
                "budget": 500,
                "days": 2,
                "interests": ["Art"],
                "vibe": "coastal cafes",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["recommended_destination"] == "Lisbon"
        prefs = mock_plan.call_args.args[0]
        assert prefs.city is None
        assert prefs.vibe == "coastal cafes"


def test_plan_stream_structure():
    """Verifies POST /plan_stream returns NDJSON events."""

    def mock_generator(prefs):
        yield "Status Update 1"
        from app.models.domain import CostBreakdown, Itinerary

        yield Itinerary(
            city="Stream City",
            recommended_destination="Stream City",
            cost_breakdown=CostBreakdown(total=100, remaining_budget=400),
            days=[],
            valid=True,
        )

    with patch.object(agent, "plan_trip_stream", side_effect=mock_generator):
        response = client.post(
            "/plan_stream",
            json={
                "city": "Stream City",
                "budget": 500,
                "days": 1,
                "interests": ["Testing"],
            },
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) >= 2

        evt1 = json.loads(lines[0])
        assert evt1["type"] == "status"

        evt2 = json.loads(lines[-1])
        assert evt2["type"] == "result"
        assert evt2["data"]["city"] == "Stream City"
        assert "cost_breakdown" in evt2["data"]
        assert "destination_suggestions" in evt2["data"]


def test_plan_stream_accepts_work_friendly_request():
    captured = {}

    def mock_generator(prefs):
        captured["prefs"] = prefs
        yield "Status Update 1"
        from app.models.domain import CostBreakdown, Itinerary

        yield Itinerary(
            city="Chiang Mai",
            recommended_destination="Chiang Mai",
            work_friendly_notes="Choose Nimman stays with coworking access.",
            cost_breakdown=CostBreakdown(
                transport=150,
                stay=180,
                food=80,
                activities=40,
                total=450,
                remaining_budget=50,
            ),
            days=[],
            valid=True,
        )

    with patch.object(agent, "plan_trip_stream", side_effect=mock_generator):
        response = client.post(
            "/plan_stream",
            json={
                "city": None,
                "budget": 500,
                "days": 3,
                "interests": ["Cafes"],
                "vibe": "quiet digital nomad",
                "work_friendly": True,
            },
        )

        assert response.status_code == 200
        data = json.loads(response.text.strip().split("\n")[-1])["data"]
        assert data["recommended_destination"] == "Chiang Mai"
        assert data["work_friendly_notes"]
        assert captured["prefs"].work_friendly is True


def test_api_error_handling():
    """Verifies that exceptions are sanitized."""
    from app.core.agent import TravelAgent

    with patch.object(
        TravelAgent, "plan_trip_stream", side_effect=Exception("Wait 429 Error")
    ):
        response = client.post(
            "/plan_stream",
            json={
                "city": "Fail City",
                "budget": 500,
                "days": 1,
                "interests": ["Testing"],
            },
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        err_evt = json.loads(lines[0])

        assert err_evt["type"] == "error"
        assert "High traffic volume" in err_evt["message"]


def test_calendar_endpoint_returns_downloadable_ics():
    response = client.post(
        "/calendar?start_date=2026-01-15",
        json={
            "city": "Paris",
            "recommended_destination": "Paris",
            "cost_breakdown": {"total": 42, "remaining_budget": 58},
            "days": [
                {
                    "day_number": 1,
                    "activities": [
                        {
                            "name": "Eiffel Tower",
                            "description": "Iron lady",
                            "cost": 25,
                            "duration_hours": 2,
                            "tags": ["Sightseeing"],
                        }
                    ],
                }
            ],
            "valid": True,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["content-disposition"] == 'attachment; filename="Trip_to_Paris.ics"'
    assert "BEGIN:VCALENDAR" in response.text
    assert "SUMMARY:Eiffel Tower (Paris)" in response.text
