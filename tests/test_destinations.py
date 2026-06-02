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


def test_vibe_only_discovery_uses_mood_terms_without_city():
    prefs = Preferences(
        budget=900,
        days=3,
        interests=[],
        vibe="quiet coastal cafes",
    )

    suggestions = recommend_destinations(prefs)

    assert suggestions[0].city == "Lisbon"
    assert "Food" in suggestions[0].tags


def test_interest_heavy_request_prioritizes_relevant_tags():
    prefs = Preferences(
        budget=1800,
        days=4,
        interests=["History", "Art"],
        vibe="ancient architecture",
    )

    suggestions = recommend_destinations(prefs)

    assert {"History", "Art"}.issubset(set(suggestions[0].tags))


def test_budget_constrained_results_stay_under_hard_cap():
    prefs = Preferences(
        budget=700,
        days=3,
        interests=["Nightlife"],
        vibe="music bars budget city",
    )

    suggestions = recommend_destinations(prefs)

    assert suggestions
    assert all(suggestion.estimated_total_cost <= 700 for suggestion in suggestions)


def test_work_friendly_request_favors_nomad_ready_destinations():
    prefs = Preferences(
        budget=800,
        days=3,
        interests=["Food"],
        vibe="quiet digital nomad cafes",
        work_friendly=True,
    )

    suggestions = recommend_destinations(prefs)

    assert suggestions[0].city == "Lisbon"
    assert suggestions[0].estimated_total_cost <= 800


def test_recommendation_count_is_capped_to_three():
    prefs = Preferences(
        budget=2000,
        days=3,
        interests=["Nature"],
        vibe="beach relaxation",
    )

    assert len(recommend_destinations(prefs)) == 3
