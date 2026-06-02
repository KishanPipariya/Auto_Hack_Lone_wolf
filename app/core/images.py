import logging
import urllib.parse
from collections.abc import Callable

from ddgs import DDGS

logger = logging.getLogger("travel_agent_server.images")


def generated_image_url(query: str) -> str:
    safe_query = urllib.parse.quote(f"{query} aesthetic")
    return f"https://image.pollinations.ai/prompt/{safe_query}?width=800&height=600&nologo=true"


def search_real_image(query: str) -> str | None:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=1, safesearch="on"))
            if results and "image" in results[0]:
                logger.debug("Found real image for %r: %s", query, results[0]["image"])
                return str(results[0]["image"])
    except Exception:
        logger.warning("Image search failed for %r", query, exc_info=True)

    return None


def resolve_activity_image(
    activity: dict,
    city: str,
    image_search: Callable[[str], str | None] | None = None,
) -> str:
    current_image = activity.get("image_url")
    if isinstance(current_image, str) and current_image.strip():
        return current_image

    query = f"{activity.get('name', 'Travel activity')} {city}".strip()
    if image_search:
        real_image = image_search(query)
    else:
        real_image = search_real_image(query)

    return real_image or generated_image_url(query)
