import unittest

from app.core.parser import parse_llm_response


REAL_BROKEN_JSON = """
{
  "city": "Amsterdam",
  "days": [
    {
      "day_number": 1,
      "activities": [
        {
          "name": "Free Walking Tour",
          "duration_hours": "2.5 hours",
          "cost": "Tip-based (recommend €10-€15)",
          "tags": ["Art"]
        }
      ]
    }
  ]
}
"""


class TestFuzzyParser(unittest.TestCase):
    def test_fuzzy_parser_normalization(self):
        itinerary = parse_llm_response(REAL_BROKEN_JSON)

        assert len(itinerary.days) == 1
        assert itinerary.days[0].day_number == 1

        act = itinerary.days[0].activities[0]
        assert act.duration_hours == 2.5
        assert act.cost == 10.0
        assert act.tags == ["Art"]
        assert act.description == "Free Walking Tour"


if __name__ == "__main__":
    unittest.main()
