"""MarkdownV2 escaping — the most common cause of a 400 from sendMessage."""

from jobalert.telegram import escape_md, format_job


def test_escape_md_escapes_reserved_characters():
    assert escape_md("C++ (Senior)") == r"C\+\+ \(Senior\)"
    assert escape_md("data-engineering") == r"data\-engineering"
    assert escape_md("3.5 years") == r"3\.5 years"


def test_escape_md_handles_none_and_numbers():
    assert escape_md(None) == ""
    assert escape_md(42) == "42"


def test_format_job_escapes_title_but_keeps_url_raw():
    """The URL sits inside (...) and must not be escaped, or the link breaks."""
    job = {
        "title": "Senior Engineer (Data)",
        "company": "Acme Corp.",
        "location": "Pune, India",
        "url": "https://example.com/jobs/1?ref=x&y=2",
        "family": "data-engineering",
        "seniority": "senior",
        "remote_policy": "hybrid",
        "skills": ["Spark", "Airflow"],
        "summary": "Own the ingestion layer.",
    }
    out = format_job(job)
    assert r"Senior Engineer \(Data\)" in out
    assert "https://example.com/jobs/1?ref=x&y=2" in out
    assert out.rstrip().endswith(")")


def test_format_job_omits_missing_optional_fields():
    job = {"title": "Engineer", "company": "Acme", "url": "https://x/1"}
    out = format_job(job)
    assert "📍" not in out
    assert "💰" not in out
    assert "🛠" not in out


def test_format_job_renders_salary_when_present():
    job = {
        "title": "Engineer", "company": "Acme", "url": "https://x/1",
        "salary_min": 2500000, "salary_max": 3500000, "salary_currency": "INR",
    }
    assert "💰" in format_job(job)
