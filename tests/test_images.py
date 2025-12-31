import pytest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import urllib.request
import urllib.error
from app.core.agent import TravelAgent

from unittest.mock import patch


class TestImageSystem:
    def test_fallback_injection(self):
        """Test that the parser injects a fallback URL when image_url is missing."""
        agent = TravelAgent()

        # Simulating an LLM response with no image_url
        raw_response = json.dumps(
            {
                "city": "Test City",
                "days": [
                    {
                        "day_number": 1,
                        "activities": [
                            {
                                "name": "Test Activity",
                                "description": "A test activity",
                                "cost": 10,
                                "duration": "1 hour",
                                # image_url intentionally missing
                            }
                        ],
                    }
                ],
            }
        )

        # Mock _search_real_image to return None, forcing the pollinations.ai fallback
        with patch.object(agent, "_search_real_image", return_value=None):
            itinerary = agent._parse_llm_response(raw_response)

        activity = itinerary.days[0].activities[0]

        assert activity.image_url is not None
        assert "pollinations.ai" in activity.image_url
        assert (
            "Test%20Activity" in activity.image_url
            or "Test Activity" in activity.image_url
        )

    def test_fallback_injection_empty_string(self):
        """Test that the parser injects a fallback URL when image_url is empty string."""
        agent = TravelAgent()

        raw_response = json.dumps(
            {
                "city": "Test City",
                "days": [
                    {
                        "day_number": 1,
                        "activities": [
                            {
                                "name": "Test Activity",
                                "cost": 10,
                                "duration": "1 hour",
                                "image_url": "",  # Empty string
                            }
                        ],
                    }
                ],
            }
        )

        # Mock _search_real_image to return None, forcing the pollinations.ai fallback
        with patch.object(agent, "_search_real_image", return_value=None):
            itinerary = agent._parse_llm_response(raw_response)

        activity = itinerary.days[0].activities[0]

        assert activity.image_url is not None
        assert "pollinations.ai" in activity.image_url

    def test_pollinations_availability(self):
        """Integration test: Verify that pollinations.ai returns 200 OK for a generated URL."""
        # Construct a real URL that the app would use
        url = "https://image.pollinations.ai/prompt/Eiffel%20Tower%20Paris%20aesthetic?width=800&height=600&nologo=true"

        try:
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "TravelPlannerTest/1.0")

            with urllib.request.urlopen(req, timeout=10) as response:
                assert response.status == 200
        except urllib.error.HTTPError as e:
            pytest.fail(f"HTTP Error checking URL: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            pytest.fail(f"URL Error: {e.reason}")
