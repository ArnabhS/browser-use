"""P0-4: the search_page / find_elements result serializers (the text the model reads)."""
from app.observation.page_query import find_args, format_find, format_search, search_args


def test_format_search_lists_matches_with_context():
    out = format_search({"matches": ["… buy now for $5 …", "add to cart"]})
    assert "2 match(es)" in out and "buy now for $5" in out


def test_format_search_no_matches_is_explicit():
    assert "no matches" in format_search({"matches": []})


def test_format_search_reports_error():
    assert "error" in format_search({"error": "bad pattern: x"}).lower()


def test_format_find_lists_elements_and_attrs():
    out = format_find({"count": 3, "results": [{"tag": "a", "text": "Home", "href": "/"}]})
    assert "3 element(s)" in out and "showing 1" in out
    assert "a" in out and "href='/'" in out


def test_format_find_none_matched():
    assert "no elements" in format_find({"count": 0, "results": []})


def test_arg_builders_apply_defaults():
    assert search_args({"pattern": "x"}) == ["x", False, False, 25, 60]
    assert find_args({"selector": "a"}) == ["a", None, 50, True]
