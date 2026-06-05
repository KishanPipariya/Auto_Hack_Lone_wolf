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

    def test_cost_breakdown_activities_uses_activity_total(self):
        itinerary = parse_llm_response(
            """
            {
              "city": "Lisbon",
              "cost_breakdown": {
                "transport": 100,
                "stay": 200,
                "food": 80,
                "activities": 10
              },
              "days": [
                {
                  "day_number": 1,
                  "activities": [
                    {"name": "Food walk", "cost": 25, "duration_hours": 2}
                  ]
                }
              ]
            }
            """,
            image_search=lambda _: None,
        )

        assert itinerary.cost_breakdown.activities == 25
        assert itinerary.cost_breakdown.total == 405

    def test_parser_normalizes_llm_alias_schema(self):
        itinerary = parse_llm_response(
            """
            {
              "destination": "Rotterdam, Netherlands",
              "destination_suggestions": [
                {
                  "name": "Krakow, Poland",
                  "estimated_total_usd": 630,
                  "tags": ["History", "Nightlife"],
                  "rationale": "Affordable and lively."
                }
              ],
              "days": [
                {
                  "day": 1,
                  "date": "2026-02-04",
                  "weekday": "Wednesday",
                  "plan": [
                    {
                      "time": "Morning",
                      "activity": "Walk around Markthal"
                    },
                    {
                      "time": "Afternoon",
                      "activity": "Kunsthal Rotterdam",
                      "opening_hours_checked": "Tuesday to Sunday, 10:00-17:00",
                      "cost_usd": 19
                    }
                  ]
                }
              ],
              "cost_breakdown": {
                "transport": 60,
                "stay": 175,
                "food": 95,
                "activities": 19,
                "total": 349,
                "remaining_budget": 151
              }
            }
            """,
            image_search=lambda _: None,
        )

        assert itinerary.city == "Rotterdam, Netherlands"
        assert itinerary.recommended_destination == "Rotterdam, Netherlands"
        assert itinerary.destination_suggestions[0].city == "Krakow, Poland"
        assert itinerary.destination_suggestions[0].estimated_total_cost == 630
        assert itinerary.days[0].day_number == 1
        assert itinerary.days[0].activities[0].name == "Walk around Markthal"
        assert itinerary.days[0].activities[0].tags == ["Morning"]
        assert itinerary.days[0].activities[1].name == "Kunsthal Rotterdam"
        assert itinerary.days[0].activities[1].cost == 19

    def test_parser_uses_day_city_for_activity_image_context(self):
        image_queries = []

        def fake_image_search(query):
            image_queries.append(query)
            return None

        itinerary = parse_llm_response(
            """
            {
              "city": "Rotterdam, Amsterdam",
              "days": [
                {
                  "day_number": 1,
                  "city": "Rotterdam",
                  "activities": [
                    {"name": "Markthal", "cost": 0, "duration_hours": 1}
                  ]
                },
                {
                  "day_number": 2,
                  "city": "Amsterdam",
                  "activities": [
                    {"name": "Canal walk", "cost": 0, "duration_hours": 2}
                  ]
                }
              ]
            }
            """,
            image_search=fake_image_search,
        )

        assert itinerary.days[0].city == "Rotterdam"
        assert itinerary.days[1].city == "Amsterdam"
        assert image_queries == ["Markthal Rotterdam", "Canal walk Amsterdam"]


if __name__ == "__main__":
    unittest.main()
