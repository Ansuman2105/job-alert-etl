"""Channel routing.

The false-positive cases matter most here: a substring match on "india" quietly
sends every Indianapolis job to the India channel, and nobody notices for weeks.
"""

import pytest

from jobalert.routing import INDIA, INTERNATIONAL, is_india, postgres_regex, route_of


@pytest.mark.parametrize(
    "location",
    [
        "Bengaluru, India",
        "bangalore",
        "Hyderabad, Telangana",
        "Pune",
        "Mumbai, Maharashtra, India",
        "New Delhi",
        "Gurugram",
        "Remote - India",
        "Chennai / Bangalore",
        "INDIA",
    ],
)
def test_indian_locations_route_to_india(location):
    assert route_of(location) == INDIA


@pytest.mark.parametrize(
    "location",
    [
        "Indianapolis, IN",       # contains "india" as a substring
        "Indiana, United States",  # ditto
        "London, UK",
        "San Francisco, CA",
        "Berlin, Germany",
        "Remote - US",
        "Tokyo, Japan",
    ],
)
def test_non_indian_locations_route_to_international(location):
    assert route_of(location) == INTERNATIONAL


def test_indianapolis_is_the_key_false_positive():
    """Word-boundary matching is the whole reason this is a regex, not a LIKE."""
    assert is_india("Indianapolis, IN") is False
    assert is_india("Bengaluru, India") is True


def test_missing_location_defaults_to_international():
    """A NULL location must land somewhere, not vanish from both channels."""
    assert route_of(None) == INTERNATIONAL
    assert route_of("") == INTERNATIONAL


def test_postgres_regex_uses_postgres_word_boundary():
    r"""Postgres spells it \y; \b means backspace there and matches nothing."""
    pattern = postgres_regex()
    assert pattern.startswith(r"\y(")
    assert pattern.endswith(r")\y")
    assert "india" in pattern
    assert r"\b" not in pattern


def test_every_job_gets_exactly_one_route():
    for location in ["Bengaluru", "Berlin", None, "", "Indianapolis"]:
        assert route_of(location) in {INDIA, INTERNATIONAL}
