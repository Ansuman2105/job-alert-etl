"""The LLM returns text. These tests cover what happens when it misbehaves."""

import pytest

from jobalert.llm.base import LLMError, extract_json, parse_facts

FAMILIES = ["data-engineering", "software-backend", "other"]
LEVELS = ["entry", "mid", "senior"]


def test_extract_json_plain():
    assert extract_json('{"family": "data-engineering"}') == {"family": "data-engineering"}


def test_extract_json_inside_markdown_fence():
    """Small models wrap JSON in fences even when told not to."""
    raw = '```json\n{"family": "data-engineering"}\n```'
    assert extract_json(raw)["family"] == "data-engineering"


def test_extract_json_with_surrounding_prose():
    raw = 'Here is the result:\n{"family": "other"}\nHope that helps!'
    assert extract_json(raw)["family"] == "other"


def test_extract_json_raises_on_no_json():
    with pytest.raises(LLMError):
        extract_json("I cannot help with that.")


def test_parse_facts_maps_unknown_family_to_other():
    facts = parse_facts({"family": "underwater-basket-weaving"}, FAMILIES, LEVELS)
    assert facts.family == "other"


def test_parse_facts_drops_unknown_seniority():
    facts = parse_facts({"seniority": "wizard"}, FAMILIES, LEVELS)
    assert facts.seniority is None


def test_parse_facts_coerces_salary_written_as_string():
    """Models frequently return '₹25,00,000' instead of a number."""
    facts = parse_facts({"salary_min": "2,500,000"}, FAMILIES, LEVELS)
    assert facts.salary_min == 2500000.0


def test_parse_facts_caps_list_lengths():
    facts = parse_facts({"skills": [f"skill{i}" for i in range(50)]}, FAMILIES, LEVELS)
    assert len(facts.skills) == 12


def test_parse_facts_survives_empty_payload():
    facts = parse_facts({}, FAMILIES, LEVELS)
    assert facts.family == "other"
    assert facts.skills == []
    assert facts.remote_policy == "unclear"


def test_parse_facts_normalises_remote_policy():
    assert parse_facts({"remote_policy": "REMOTE"}, FAMILIES, LEVELS).remote_policy == "remote"
    assert parse_facts({"remote_policy": "banana"}, FAMILIES, LEVELS).remote_policy == "unclear"
