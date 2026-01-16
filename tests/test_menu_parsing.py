from pathlib import Path

from dining_checker import _extract_items_by_meal, _find_keyword_details_from_items


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "menu_sample.html"


def _load_fixture():
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_extract_items_by_meal():
    html = _load_fixture()
    items = _extract_items_by_meal(html)
    assert "Breakfast" in items
    assert "Brunch" in items
    assert "Jalapeno Poppers" in items["Breakfast"]
    assert "Shrimp Tacos" in items["Brunch"]


def test_find_keyword_details_from_items():
    html = _load_fixture()
    items = _extract_items_by_meal(html)
    matches = _find_keyword_details_from_items(items, ["jalapeno poppers", "shrimp"])
    assert matches["jalapeno poppers"] == {"Breakfast"}
    assert matches["shrimp"] == {"Brunch"}
