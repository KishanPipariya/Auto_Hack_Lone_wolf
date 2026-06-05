import json
import os
import urllib.error
import urllib.request

import pytest

from app.core.parser import parse_llm_response


class TestImageSystem:
    def test_fallback_injection(self):
        """Test that the parser injects a fallback URL when image_url is missing."""
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
                                "duration_hours": "1 hour",
                            }
                        ],
                    }
                ],
            }
        )

        itinerary = parse_llm_response(raw_response, image_search=lambda _: None)

        activity = itinerary.days[0].activities[0]

        assert activity.image_url is not None
        assert "pollinations.ai" in activity.image_url
        assert (
            "Test%20Activity" in activity.image_url
            or "Test Activity" in activity.image_url
        )

    def test_fallback_injection_empty_string(self):
        """Test that the parser injects a fallback URL when image_url is empty string."""
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
                                "duration_hours": "1 hour",
                                "image_url": "",
                            }
                        ],
                    }
                ],
            }
        )

        itinerary = parse_llm_response(raw_response, image_search=lambda _: None)

        activity = itinerary.days[0].activities[0]

        assert activity.image_url is not None
        assert "pollinations.ai" in activity.image_url

    def test_image_query_is_converted_to_renderable_url(self):
        """Test that search-query image_url values become usable image URLs."""
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
                                "duration_hours": "1 hour",
                                "image_url": "Test Activity Test City landmark photo",
                            }
                        ],
                    }
                ],
            }
        )

        itinerary = parse_llm_response(raw_response, image_search=lambda _: None)

        activity = itinerary.days[0].activities[0]

        assert activity.image_url is not None
        assert activity.image_url.startswith("https://")
        assert "pollinations.ai" in activity.image_url
        assert "Test%20Activity%20Test%20City%20landmark%20photo" in activity.image_url

    @pytest.mark.integration
    @pytest.mark.skipif(
        os.environ.get("RUN_REAL_IMAGE_SEARCH") != "1",
        reason="External image availability check is opt-in.",
    )
    def test_pollinations_availability(self):
        """Integration test: Verify that pollinations.ai returns 200 OK."""
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
