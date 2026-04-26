from __future__ import annotations

from datetime import date, timedelta

from moodle_crawler import MoodleCrawler, MoodleEvent


def test_normalize_input_url_adds_https_scheme() -> None:
    crawler = MoodleCrawler()

    assert crawler._normalize_input_url("moodle.example.edu/course/view.php?id=12") == (
        "https://moodle.example.edu/course/view.php?id=12"
    )
    assert crawler._normalize_input_url("   ") == ""


def test_extract_first_date_supports_moodle_due_text() -> None:
    crawler = MoodleCrawler()

    parsed = crawler._extract_first_date("Due: Friday, May 1, 2026, 11:59 PM")

    assert parsed == (date(2026, 5, 1), "11:59 PM")


def test_submission_url_canonicalizes_assignment_actions() -> None:
    crawler = MoodleCrawler()

    normalized = crawler._to_submission_page_url(
        "https://moodle.example.edu/mod/assign/view.php?id=42&action=editsubmission"
    )

    assert normalized == "https://moodle.example.edu/mod/assign/view.php?id=42"
    assert crawler._is_canonical_submission_page_url(normalized)


def test_dedupe_events_prefers_assignment_source_over_course_source() -> None:
    crawler = MoodleCrawler()
    due_date = date.today() + timedelta(days=7)
    generic = MoodleEvent(
        title="Homework item",
        category="Homework",
        event_date=due_date,
        source_url="https://moodle.example.edu/course/view.php?id=12",
    )
    specific = MoodleEvent(
        title="Homework item",
        category="Homework",
        event_date=due_date,
        details="Due soon",
        source_url="https://moodle.example.edu/mod/assign/view.php?id=44",
    )

    deduped = crawler._dedupe_events([generic, specific])

    assert deduped == [specific]
