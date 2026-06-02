from app.core.destinations import recommend_destinations
from app.models.domain import Preferences


def test_vibe_and_interests_select_expected_destinations():
    prefs = Preferences(
        budget=1500,
        days=3,
        interests=["Food", "Art"],
        vibe="ancient town cafes beach",
    )

    suggestions = recommend_destinations(prefs)

    assert suggestions
    assert suggestions[0].city == "Hoi An"
    assert "Food" in suggestions[0].tags


def test_budget_deprioritizes_destinations_above_budget():
    prefs = Preferences(
        budget=900,
        days=3,
        interests=["Hiking"],
        vibe="mountain trekking",
    )

    suggestions = recommend_destinations(prefs)

    assert suggestions
    assert suggestions[0].estimated_total_cost <= 900


def test_recommendation_count_is_capped_to_three():
    prefs = Preferences(
        budget=2000,
        days=3,
        interests=["Nature"],
        vibe="beach relaxation",
    )

    assert len(recommend_destinations(prefs)) == 3
