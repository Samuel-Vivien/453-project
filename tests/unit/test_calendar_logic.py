from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import MethodType
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from calendar_app import CalendarApp, CalendarItem
from moodle_crawler import MoodleEvent


def make_headless_app() -> CalendarApp:
    app = object.__new__(CalendarApp)
    app.items_by_day = {}
    app.next_item_id = 1
    app._save_items = MethodType(lambda self: None, app)
    app.color_blind_var = SimpleNamespace(get=lambda: False)
    return app


def test_calendar_item_from_dict_defaults_missing_optional_fields() -> None:
    item = CalendarItem.from_dict({"item_id": "7", "title": "Project checkpoint"})

    assert item.item_id == 7
    assert item.title == "Project checkpoint"
    assert item.details == ""
    assert item.time_label == ""


def test_calendar_item_from_dict_restores_due_fields() -> None:
    item = CalendarItem.from_dict(
        {
            "item_id": "8",
            "title": "Presentation",
            "due_date": "2026-05-05",
            "due_time": "11:59 PM",
            "time_label": "11:59 PM",
        }
    )

    assert item.due_date == "2026-05-05"
    assert item.due_time == "11:59 PM"


def test_item_due_datetime_uses_saved_date_and_time() -> None:
    app = make_headless_app()
    item = CalendarItem(item_id=1, title="Soon", due_date="2026-05-05", due_time="11:59 PM")

    due_dt = app._item_due_datetime(item, date(2026, 5, 1))

    assert due_dt == datetime(2026, 5, 5, 23, 59)


def test_item_urgency_marks_overdue_and_soon_deadlines_red_or_yellow() -> None:
    app = make_headless_app()
    now = datetime.now()

    overdue_time = now - timedelta(hours=1)
    soon_time = now + timedelta(days=2)
    later_time = now + timedelta(days=5)

    overdue_item = CalendarItem(
        item_id=2,
        title="Overdue",
        due_date=overdue_time.date().isoformat(),
        due_time=overdue_time.strftime("%I:%M %p"),
    )
    soon_item = CalendarItem(
        item_id=3,
        title="Soon",
        due_date=soon_time.date().isoformat(),
        due_time=soon_time.strftime("%I:%M %p"),
    )
    later_item = CalendarItem(
        item_id=4,
        title="Later",
        due_date=later_time.date().isoformat(),
        due_time=later_time.strftime("%I:%M %p"),
    )

    assert app._item_urgency(overdue_item, overdue_time.date()) == "danger"
    assert app._item_urgency(soon_item, soon_time.date()) in {"danger", "warning"}
    assert app._item_urgency(later_item, later_time.date()) == "success"


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


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__]))
