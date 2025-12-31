import pytest
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import TravelAgent


class TestRealImageSearch:
    def test_search_real_image_integration(self):
        """
        Integration test to verify DuckDuckGo search returns a real URL.
        """
        agent = TravelAgent()
        query = "Eiffel Tower Paris"

        print(f"\nSearching for: {query}...")
        url = agent._search_real_image(query)

        print(f"Result: {url}")

        assert url is not None
        assert isinstance(url, str)
        assert url.startswith("http")
        # Ensure it's NOT a pollinations.ai generated URL (unless DDG returns it, which is unlikely for this query)
        assert "pollinations.ai" not in url, (
            "Should find a real image, not a generated one"
        )
