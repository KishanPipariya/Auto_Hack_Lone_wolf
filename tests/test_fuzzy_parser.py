import unittest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import TravelAgent
import json

# This JSON mimics the real "broken" response from server.log
REAL_BROKEN_JSON = """
{
  "itinerary": {
    "title": "Amsterdam Budget Itinerary",
    "days": [
      {
        "day": 1,
        "activities": [
          {
            "name": "Free Walking Tour",
            "duration": "2.5 hours",
            "cost": "Tip-based (recommend €10-€15)",
            "interests": ["Art"]
          }
        ]
      }
    ]
  }
}
"""


class TestFuzzyParser(unittest.TestCase):
    def test_fuzzy_parser_normalization(self):
        agent = TravelAgent()
        # Mock client not needed for pure parsing test

        itinerary = agent._parse_llm_response(REAL_BROKEN_JSON)

        # Verify unnesting
        assert len(itinerary.days) == 1
        assert itinerary.days[0].day_number == 1

        # Verify type coercion
        act = itinerary.days[0].activities[0]
        assert act.duration_hours == 2.5  # Extracted from "2.5 hours"
        assert act.cost == 10.0  # Extracted first number from string
        assert act.tags == ["General"]  # Default added
        assert act.description == "Free Walking Tour"  # Default from name


if __name__ == "__main__":
    unittest.main()
