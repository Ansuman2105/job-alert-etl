from datetime import UTC

from jobalert.util import parse_dt, strip_html, truncate


def test_strip_html_removes_tags_and_unescapes():
    html = "<p>Build &amp; run pipelines</p><ul><li>Spark</li><li>Airflow</li></ul>"
    out = strip_html(html)
    assert "<" not in out
    assert "&amp;" not in out
    assert "Build & run pipelines" in out
    assert "Spark" in out


def test_strip_html_handles_empty():
    assert strip_html(None) is None
    assert strip_html("") is None
    assert strip_html("<p></p>") is None


def test_parse_dt_iso_with_z():
    dt = parse_dt("2026-08-01T10:30:00Z")
    assert dt.year == 2026 and dt.month == 8
    assert dt.tzinfo == UTC


def test_parse_dt_naive_iso_assumed_utc():
    assert parse_dt("2026-08-01T10:30:00").tzinfo == UTC


def test_parse_dt_epoch_seconds_and_milliseconds_agree():
    """Lever sends milliseconds, Arbeitnow sends seconds — both must work."""
    seconds = parse_dt(1754044200)
    millis = parse_dt(1754044200000)
    assert seconds == millis


def test_parse_dt_rejects_garbage_without_raising():
    assert parse_dt("not a date") is None
    assert parse_dt(None) is None
    assert parse_dt("") is None


def test_truncate_respects_limit():
    text = "word " * 100
    out = truncate(text, 50)
    assert len(out) <= 53  # limit plus the ellipsis
    assert out.endswith("...")


def test_truncate_leaves_short_text_alone():
    assert truncate("short", 100) == "short"
