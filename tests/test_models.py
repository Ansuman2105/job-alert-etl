"""Tests for identity and normalisation — the logic dedup depends on."""

from jobalert.models import job_hash, normalise


def test_normalise_collapses_punctuation_and_case():
    assert normalise("Senior Data Engineer (Remote)") == "senior data engineer remote"
    assert normalise("  MULTIPLE   spaces  ") == "multiple spaces"
    assert normalise(None) == ""


def test_same_job_written_differently_hashes_the_same():
    a = job_hash("Databricks", "Senior Data Engineer", "Bengaluru, India")
    b = job_hash("databricks", "senior data engineer!", "Bengaluru,  India")
    assert a == b


def test_different_company_differs():
    a = job_hash("Databricks", "Data Engineer", "Pune")
    b = job_hash("Stripe", "Data Engineer", "Pune")
    assert a != b


def test_different_location_differs():
    """Same title at the same company in two cities is two jobs, not one."""
    a = job_hash("Stripe", "Data Engineer", "Bengaluru")
    b = job_hash("Stripe", "Data Engineer", "Pune")
    assert a != b


def test_hash_is_stable_across_calls():
    args = ("Acme", "Analyst", "Remote")
    assert job_hash(*args) == job_hash(*args)
