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


def test_money_formatter_preserves_small_nonzero_amounts() -> None:
    html, _ = parse_index()

    assert "Math.abs(numeric) < 1 ? 2 : 0" in html
    assert "minimumFractionDigits: fractionDigits" in html
    assert "maximumFractionDigits: fractionDigits" in html
    assert "function formatItineraryMoney" in html
    assert "return formatMoney(value);" in html


def test_budget_form_supports_exactly_one_currency_amount() -> None:
    html, elements = parse_index()
    by_id = {attrs.get("id"): attrs for _, attrs in elements if attrs.get("id")}

    assert 'class="budget-fields"' in html
    assert "display: grid !important;" in html
    assert "@media (max-width: 520px)" in html
    assert "local_budget" in by_id
    assert "required" not in by_id["budget"]
    assert "local_budget" not in html.split("const data = {", 1)[1].split("};", 1)[0]
    assert "data.budget = parseFloat(usdBudget)" in html
    assert "data.local_budget = parseFloat(localBudget)" in html
    assert "Boolean(usdBudget) === Boolean(localBudgetValue)" in html


def test_itinerary_cost_rendering_uses_currency_formatter() -> None:
    html, _ = parse_index()

    assert "Total Trip Cost: $${formatMoney" not in html
    assert "Day total: $${formatMoney" not in html
    assert "Cost: $${formatMoney" not in html
    assert "Estimated total: $${formatMoney" not in html
    assert "Remaining budget: $${formatMoney" not in html
    assert "const prefix = itineraryUsesLocalBudget" not in html
    assert "Total Trip Cost: ${formatItineraryMoney(total, data)}" in html
    assert "Day total: ${formatItineraryMoney(dayTotal, itinerary)}" in html
    assert "Cost: ${formatItineraryMoney(activity.cost, itinerary)}" in html
    assert "function stripDollarSymbolsForLocalBudget" in html
    assert "function cleanTextForLocalBudget" in html
    assert "function sanitizeItineraryForLocalBudget" in html
    assert "function sanitizeDollarStrings" in html
    assert "replace(/\\$/g, '')" in html
    assert "stripDollarSymbolsForLocalBudget(resultDiv, data)" in html
    assert "cleanTextForLocalBudget(msg.message, data)" in html
    assert "sanitizeItineraryForLocalBudget(data)" in html
