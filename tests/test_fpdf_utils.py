import pytest
from unittest.mock import AsyncMock, patch
from app.models.domain import Itinerary, DayPlan, Activity
from app.services.pdf import generate_pdf, itinerary_money
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_itinerary_money_omits_currency_symbol():
    usd_itinerary = Itinerary(city="Paris", days=[], uses_local_budget=False)
    local_itinerary = Itinerary(city="Tokyo", days=[], uses_local_budget=True)

    assert itinerary_money(500, usd_itinerary) == "500"
    assert itinerary_money(500, local_itinerary) == "500"


@pytest.mark.asyncio
async def test_generate_pdf_mixed_costs():
    # Setup mixed cost data
    activities = [
        Activity(
            name="Paid Activity",
            description="Costs money",
            cost=25.0,
            duration_hours=2.0,
            tags=["fun"],
            image_url="http://example.com/1.jpg",
        ),
        Activity(
            name="Free Activity",
            description="Is free",
            cost="Free",  # String cost
            duration_hours=1.0,
            tags=["budget"],
            image_url="http://example.com/2.jpg",
        ),
        Activity(
            name="Unicode Activity – Café",
            description="Rotterdam’s harbor tour includes architecture, art, and €25 snacks.",
            cost="€25",  # Unicode string cost
            tags=["euro"],
            duration_hours=3.0,
            duration_str="2–3 hours",
            image_url="http://example.com/3.jpg",
        ),
    ]

    day = DayPlan(day_number=1, activities=activities)
    itinerary = Itinerary(
        city="Rótterdam",
        days=[day],
        total_cost=25.0,  # Only sums numeric
    )

    # Mock aiohttp
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"fakeimagebytes"
        mock_get.return_value.__aenter__.return_value = mock_resp

        # Run generation
        try:
            response = await generate_pdf(itinerary)
            assert response.media_type == "application/pdf"
            assert response.body.startswith(b"%PDF")
            assert (
                response.headers["Content-Disposition"]
                == "attachment; filename=Trip_to_Rotterdam.pdf"
            )
            print("PDF Generated Successfully")
        except Exception as e:
            pytest.fail(f"PDF Generation failed: {e}")


if __name__ == "__main__":
    # Allow running directly
    import asyncio

    asyncio.run(test_generate_pdf_mixed_costs())
