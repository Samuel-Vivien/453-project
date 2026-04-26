from __future__ import annotations

from datetime import date
from types import MethodType

from calendar_app import CalendarApp, CalendarItem
from moodle_crawler import MoodleEvent


def make_headless_app() -> CalendarApp:
    app = object.__new__(CalendarApp)
    app.items_by_day = {}
    app.next_item_id = 1
    app._save_items = MethodType(lambda self: None, app)
    return app


def test_calendar_item_from_dict_defaults_missing_optional_fields() -> None:
    item = CalendarItem.from_dict({"item_id": "7", "title": "Project checkpoint"})

    assert item.item_id == 7
    assert item.title == "Project checkpoint"
    assert item.details == ""
    assert item.time_label == ""


def test_sanitize_user_message_hides_webdriver_stacktrace() -> None:
    app = make_headless_app()

    message = app._sanitize_user_message("Invalid element state\nStacktrace:\n0x12345")

    assert "Moodle sign-in could not be completed automatically" in message
    assert "Stacktrace" not in message


def test_source_url_normalization_collapses_assignment_action_links() -> None:
    app = make_headless_app()

    normalized = app._normalize_source_url_for_match(
        "HTTPS://Moodle.Example.edu/mod/assign/view.php?action=editsubmission&cmid=42"
    )

    assert normalized == "https://moodle.example.edu/mod/assign/view.php?id=42"


def test_store_moodle_events_adds_homework_and_skips_duplicate_source() -> None:
    app = make_headless_app()
    event = MoodleEvent(
        title="[CMPS453] Sprint review",
        category="Homework",
        event_date=date(2026, 5, 1),
        time_label="11:59 PM",
        details="Due Friday, May 1, 2026 at 11:59 PM",
        source_url="https://moodle.example.edu/mod/assign/view.php?id=88",
    )

    added, skipped, updated = app._store_moodle_events([event])
    duplicate_result = app._store_moodle_events([event])

    assert (added, skipped, updated) == (1, 0, 0)
    assert duplicate_result == (0, 1, 0)
    assert app.next_item_id == 2
    stored = app.items_by_day["2026-05-01"][0]
    assert stored.title == "Homework: [CMPS453] Sprint review"
    assert stored.time_label == "11:59 PM"
    assert "Source: https://moodle.example.edu/mod/assign/view.php?id=88" in stored.details
