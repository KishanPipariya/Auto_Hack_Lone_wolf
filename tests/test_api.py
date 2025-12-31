import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from fastapi.testclient import TestClient
from app.api.routers.plan import agent
from app.main import app
from unittest.mock import MagicMock, patch

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_plan_endpoint_success():
    """Verifies POST /plan returns a valid itinerary."""

    # Mock the planner execution to avoid real API calls
    mock_itinerary = {
        "city": "Test City",
        "total_cost": 100.0,
        "valid": True,
        "validation_error": None,
        "days": [],
    }

    with patch.object(agent, "plan_trip") as mock_plan:
        # We need the return value to accept .model_dump() or just be a dict if Pydantic handles it,
        # but since planner returns an Itinerary object, let's mock the object.
        mock_obj = MagicMock()
        mock_obj.model_dump.return_value = mock_itinerary
        # Fastapi will try to serialise the object, so having it behave like the Pydantic model is key
        # Simplest is to just return a real (empty) Itinerary object
        from app.models.domain import Itinerary

        real_itinerary = Itinerary(city="Test City", days=[])
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


def test_plan_stream_structure():
    """Verifies POST /plan_stream returns NDJSON events."""

    # Mock the streaming generator
    def mock_generator(prefs):
        yield "Status Update 1"
        from app.models.domain import Itinerary

        yield Itinerary(city="Stream City", days=[])

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

        # Check first event (Status)
        import json

        evt1 = json.loads(lines[0])
        assert evt1["type"] == "status"

        # Check last event (Result)
        evt2 = json.loads(lines[-1])
        assert evt2["type"] == "result"
        assert evt2["data"]["city"] == "Stream City"


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

        assert response.status_code == 200  # Streaming response starts 200 usually
        # But checks the content for the error event

        lines = response.text.strip().split("\n")
        err_evt = json.loads(lines[0])

        assert err_evt["type"] == "error"
        # Since we mocked "429" string in exception, it should be sanitized
        assert "High traffic volume" in err_evt["message"]
