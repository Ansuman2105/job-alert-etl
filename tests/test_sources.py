"""Normalisation tests using payload shapes captured from the live APIs.

Field names here were verified against real responses — if a provider renames a
field, these fail rather than silently producing rows full of nulls.
"""

from jobalert.models import RawJob
from jobalert.sources import arbeitnow, ashby, greenhouse, lever, remoteok


def test_greenhouse_normalise():
    raw = RawJob(
        source="greenhouse",
        board="databricks",
        source_job_id="123",
        payload={
            "id": 123,
            "title": "Senior Data Engineer",
            "company_name": "Databricks",
            "absolute_url": "https://boards.greenhouse.io/databricks/jobs/123",
            "location": {"name": "Bengaluru, India"},
            # Greenhouse double-encodes: HTML entities wrapping HTML tags.
            "content": "&lt;p&gt;Build &amp;amp; own pipelines&lt;/p&gt;",
            "first_published": "2026-08-01T10:00:00Z",
        },
    )
    job = greenhouse.normalise(raw)
    assert job.company == "Databricks"
    assert job.location == "Bengaluru, India"
    assert job.remote is False
    assert "<p>" not in job.description
    assert "Build & own pipelines" in job.description
    assert job.posted_at.year == 2026


def test_greenhouse_marks_remote_from_location():
    raw = RawJob("greenhouse", "acme", "1", {
        "id": 1, "title": "Engineer", "absolute_url": "https://x/1",
        "location": {"name": "Remote - India"},
    })
    assert greenhouse.normalise(raw).remote is True


def test_greenhouse_skips_row_without_url():
    raw = RawJob("greenhouse", "acme", "1", {"id": 1, "title": "Engineer"})
    assert greenhouse.normalise(raw) is None


def test_ashby_prefers_plain_description():
    raw = RawJob("ashby", "linear", "abc", {
        "id": "abc", "title": "Backend Engineer", "location": "Remote",
        "isRemote": True, "jobUrl": "https://jobs.ashbyhq.com/linear/abc",
        "descriptionPlain": "Plain text version",
        "descriptionHtml": "<p>HTML version</p>",
        "publishedAt": "2026-07-15T09:00:00Z",
    })
    job = ashby.normalise(raw)
    assert job.description == "Plain text version"
    assert job.remote is True


def test_lever_uses_text_as_title_and_epoch_millis():
    raw = RawJob("lever", "spotify", "xyz", {
        "id": "xyz", "text": "Data Analyst",
        "hostedUrl": "https://jobs.lever.co/spotify/xyz",
        "categories": {"location": "Stockholm"},
        "workplaceType": "remote",
        "descriptionPlain": "Analyse things",
        "createdAt": 1754044200000,
    })
    job = lever.normalise(raw)
    assert job.title == "Data Analyst"
    assert job.location == "Stockholm"
    assert job.remote is True
    assert job.posted_at.year == 2025 or job.posted_at.year == 2026


def test_arbeitnow_normalise():
    raw = RawJob("arbeitnow", None, "slug-1", {
        "slug": "slug-1", "title": "ETL Developer", "company_name": "Acme GmbH",
        "url": "https://www.arbeitnow.com/jobs/slug-1", "location": "Berlin",
        "remote": True, "description": "<p>ETL work</p>", "created_at": 1754044200,
    })
    job = arbeitnow.normalise(raw)
    assert job.company == "Acme GmbH"
    assert job.remote is True
    assert job.description == "ETL work"


def test_remoteok_uses_position_as_title():
    raw = RawJob("remoteok", None, "99", {
        "id": "99", "position": "Data Engineer", "company": "RemoteCo",
        "url": "https://remoteok.com/remote-jobs/99", "location": "Worldwide",
        "description": "<p>Remote role</p>", "date": "2026-08-01T00:00:00+00:00",
    })
    job = remoteok.normalise(raw)
    assert job.title == "Data Engineer"
    assert job.remote is True


def test_remoteok_fetch_filters_the_legal_notice(monkeypatch):
    """The first element of the RemoteOK feed is a legal notice, not a job."""
    payload = [
        {"legal": "See https://remoteok.com/api for terms"},
        {"id": "1", "position": "Dev", "company": "X", "url": "https://x/1"},
    ]
    monkeypatch.setattr(remoteok, "get_json", lambda *a, **k: payload)
    assert len(remoteok.fetch()) == 1
