import json
from pathlib import Path

from dining_checker import _extract_items_by_meal, _find_keyword_details_from_items


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "menu_sample.json"


def _load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_extract_items_by_meal():
    data = _load_fixture()
    items = _extract_items_by_meal(data)
    assert "Breakfast" in items
    assert "Brunch" in items
    assert "Jalapeno Poppers" in items["Breakfast"]
    assert "Shrimp Tacos" in items["Brunch"]


def test_find_keyword_details_from_items():
    data = _load_fixture()
    items = _extract_items_by_meal(data)
    matches = _find_keyword_details_from_items(items, ["jalapeno poppers", "shrimp"])
    assert matches["jalapeno poppers"] == {"Breakfast"}
    assert matches["shrimp"] == {"Brunch"}
