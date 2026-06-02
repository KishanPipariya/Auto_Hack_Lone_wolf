import pytest

from app.core.agent import TravelAgent


class TestRealImageSearch:
    @pytest.mark.integration
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
        assert "pollinations.ai" not in url, "Should find a real image, not a generated one"
