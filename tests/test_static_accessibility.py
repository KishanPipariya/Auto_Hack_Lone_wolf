from html.parser import HTMLParser
from pathlib import Path


STATIC_INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


class ElementCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))


def parse_index() -> tuple[str, list[tuple[str, dict[str, str | None]]]]:
    html = STATIC_INDEX.read_text()
    parser = ElementCollector()
    parser.feed(html)
    return html, parser.elements


def test_static_page_has_required_live_regions_and_skip_link() -> None:
    _, elements = parse_index()
    by_id = {attrs.get("id"): (tag, attrs) for tag, attrs in elements if attrs.get("id")}

    assert by_id["main-content"][0] == "main"
    assert by_id["live-status"][1]["role"] == "status"
    assert by_id["alert-region"][1]["role"] == "alert"
    assert by_id["toast-container"][1]["aria-live"] == "polite"

    skip_links = [
        attrs for tag, attrs in elements
        if tag == "a" and attrs.get("class") == "skip-link"
    ]
    assert skip_links
    assert skip_links[0]["href"] == "#main-content"


def test_no_invalid_or_redundant_static_interaction_patterns() -> None:
    html, elements = parse_index()

    assert "can-tab" not in html
    assert "alert(" not in html

    for tag, attrs in elements:
        assert not any(name.startswith("on") for name in attrs), (tag, attrs)
        assert not (tag == "a" and attrs.get("href") == "#" and attrs.get("role") == "button")


def test_ids_are_unique_and_aria_descriptions_exist() -> None:
    _, elements = parse_index()
    ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
    duplicate_ids = {element_id for element_id in ids if ids.count(element_id) > 1}
    assert duplicate_ids == set()

    id_set = set(ids)
    for tag, attrs in elements:
        describedby = attrs.get("aria-describedby")
        if not describedby:
            continue
        missing = [ref for ref in describedby.split() if ref not in id_set]
        assert missing == [], (tag, attrs, missing)


def test_controls_have_accessible_names() -> None:
    _, elements = parse_index()
    labels_for = {attrs["for"] for tag, attrs in elements if tag == "label" and "for" in attrs}

    for tag, attrs in elements:
        if tag == "input" and attrs.get("type") != "hidden":
            assert (
                attrs.get("id") in labels_for
                or attrs.get("aria-label")
                or attrs.get("aria-labelledby")
            ), attrs
        if tag == "button" and not attrs.get("aria-label"):
            assert attrs.get("id") or attrs.get("class"), attrs


def test_dynamic_rendering_uses_escaped_content_and_event_listeners() -> None:
    html, _ = parse_index()

    assert "function escapeHTML" in html
    assert "function escapeAttr" in html
    assert "addEventListener('click'" in html
    assert "data-action=\"download-pdf\"" in html
    assert "data-history-id=" in html
    assert "onerror=" not in html


def test_history_api_calls_use_canonical_slash_url() -> None:
    html, _ = parse_index()

    assert "fetch('/history/'," in html
    assert "fetch('/history'," not in html


def test_cost_breakdown_uses_capitalized_display_labels() -> None:
    html, _ = parse_index()

    assert "const costLabels = {" in html
    assert "transport: 'Transport'" in html
    assert "stay: 'Stay'" in html
    assert "food: 'Food'" in html
    assert "activities: 'Activities'" in html
    assert "<dt>${costLabels[key]}</dt>" in html
    assert "<dt>${key}</dt>" not in html
