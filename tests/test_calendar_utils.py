import pytest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, date
from models import Itinerary, DayPlan, Activity
from calendar_utils import generate_ics


# Mock Data
@pytest.fixture
def mock_itinerary():
    return Itinerary(
        city="Paris",
        days=[
            DayPlan(
                day_number=1,
                activities=[
                    Activity(
                        name="Eiffel Tower",
                        description="Iron lady",
                        cost=25.0,
                        duration_hours=2.0,
                        duration_str="2 hours",
                        tags=["Sightseeing"],
                    ),
                    Activity(
                        name="Louvre Museum",
                        description="Home of Mona Lisa",
                        cost=17.0,
                        duration_hours=3.0,
                        duration_str="3 hours",
                        tags=["Art", "Museum"],
                    ),
                ],
            )
        ],
        total_cost=42.0,
    )


def test_generate_ics_valid_iso_date(mock_itinerary):
    """Test with standard YYYY-MM-DD format."""
    start_date = "2025-05-01"
    ics_bytes = generate_ics(mock_itinerary, start_date)
    ics_str = ics_bytes.decode("utf-8")

    assert "BEGIN:VCALENDAR" in ics_str
    assert "SUMMARY:Day 1: Paris Trip" in ics_str
    assert "DTSTART;VALUE=DATE:20250501" in ics_str  # All-day event check
    assert "SUMMARY:Eiffel Tower (Paris)" in ics_str
    assert "DTSTART:20250501T090000" in ics_str  # 9 AM start check


def test_generate_ics_valid_dmY_date(mock_itinerary):
    """Test with DD-MM-YYYY format (User Request)."""
    start_date = "25-12-2025"  # Christmas
    ics_bytes = generate_ics(mock_itinerary, start_date)
    ics_str = ics_bytes.decode("utf-8")

    assert "DTSTART;VALUE=DATE:20251225" in ics_str
    assert "SUMMARY:Day 1: Paris Trip" in ics_str


def test_generate_ics_default_date(mock_itinerary):
    """Test filtering back to tomorrow when date is missing."""
    ics_bytes = generate_ics(mock_itinerary, None)
    ics_str = ics_bytes.decode("utf-8")

    tomorrow = (datetime.now() + timedelta(days=1)).date()
    expected_date_str = tomorrow.strftime("%Y%m%d")

    assert f"DTSTART;VALUE=DATE:{expected_date_str}" in ics_str


def test_generate_ics_invalid_date_fallback(mock_itinerary):
    """Test filtering back to tomorrow when date is garbage."""
    ics_bytes = generate_ics(mock_itinerary, "invalid-date")
    ics_str = ics_bytes.decode("utf-8")

    tomorrow = (datetime.now() + timedelta(days=1)).date()
    expected_date_str = tomorrow.strftime("%Y%m%d")

    assert f"DTSTART;VALUE=DATE:{expected_date_str}" in ics_str
