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
        itinerary = parse_llm_response(REAL_BROKEN_JSON, image_search=lambda _: None)

        assert len(itinerary.days) == 1
        assert itinerary.days[0].day_number == 1

        act = itinerary.days[0].activities[0]
        assert act.duration_hours == 2.5
        assert act.cost == 10.0
        assert act.tags == ["Art"]
        assert act.description == "Free Walking Tour"

    def test_missing_cost_breakdown_uses_activity_total(self):
        itinerary = parse_llm_response(
            """
            {
              "city": "Porto",
              "days": [
                {
                  "day_number": 1,
                  "activities": [
                    {"name": "River walk", "cost": "$12", "duration_hours": "2 hours"},
                    {"name": "Market snack", "cost": "about 8 USD", "duration_hours": 1}
                  ]
                }
              ]
            }
            """,
            image_search=lambda _: None,
        )

        assert itinerary.cost_breakdown.activities == 20
        assert itinerary.cost_breakdown.total == 20
        assert itinerary.total_cost == 20

    def test_malformed_cost_breakdown_is_normalized_deterministically(self):
        itinerary = parse_llm_response(
            """
            {
              "city": "Madrid",
              "cost_breakdown": {
                "transport": "USD 40",
                "stay": "two hundred",
                "food": "$75",
                "activities": "$25",
                "total": "$999"
              },
              "days": [
                {
                  "day_number": 1,
                  "activities": [
                    {"name": "Museum", "cost": "$25", "duration_hours": 2}
                  ]
                }
              ]
            }
            """,
            image_search=lambda _: None,
        )

        assert itinerary.cost_breakdown.transport == 40
        assert itinerary.cost_breakdown.stay == 0
        assert itinerary.cost_breakdown.food == 75
        assert itinerary.cost_breakdown.activities == 25
        assert itinerary.cost_breakdown.total == 140


if __name__ == "__main__":
    unittest.main()
