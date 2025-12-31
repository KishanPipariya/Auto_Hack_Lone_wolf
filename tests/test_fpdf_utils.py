import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from models import Itinerary, DayPlan, Activity
from fpdf_utils import generate_pdf
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
            name="Unicode Activity",
            description="Costs Euro",
            cost="€25",  # Unicode string cost
            tags=["euro"],
            duration_hours=3.0,
            image_url="http://example.com/3.jpg",
        ),
    ]

    day = DayPlan(day_number=1, activities=activities)
    itinerary = Itinerary(
        city="Paris",
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
            print("PDF Generated Successfully")
        except Exception as e:
            pytest.fail(f"PDF Generation failed: {e}")


if __name__ == "__main__":
    # Allow running directly
    import asyncio

    asyncio.run(test_generate_pdf_mixed_costs())
