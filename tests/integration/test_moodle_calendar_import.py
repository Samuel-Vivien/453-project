from __future__ import annotations

import sys
from pathlib import Path
from types import MethodType

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from calendar_app import CalendarApp
from moodle_crawler import MoodleCrawler


def make_headless_app() -> CalendarApp:
    app = object.__new__(CalendarApp)
    app.items_by_day = {}
    app.next_item_id = 1
    app._save_items = MethodType(lambda self: None, app)
    return app


def test_moodle_assignment_page_imports_into_calendar() -> None:
    crawler = MoodleCrawler()
    assignment_url = "https://moodle.example.edu/mod/assign/view.php?id=77"
    assignment_html = """
    <html>
      <body>
        <h1>Project Integration Report</h1>
        <nav><a href="/course/view.php?id=453">CMPS453</a></nav>
        <section>
          <h2>Submission status</h2>
          <p>Due: Friday, May 1, 2026, 11:59 PM</p>
        </section>
      </body>
    </html>
    """

    assignment_index = crawler._build_assignment_index([(assignment_url, assignment_html)])
    events = crawler._extract_events_from_page(assignment_url, assignment_html, assignment_index)

    app = make_headless_app()
    added, skipped, updated = app._store_moodle_events(events)

    assert (added, skipped, updated) == (1, 0, 0)
    assert len(events) == 1
    event = events[0]
    assert event.title == "[CMPS453] Project Integration Report"
    assert event.event_date.isoformat() == "2026-05-01"
    assert event.time_label == "11:59 PM"

    stored = app.items_by_day["2026-05-01"][0]
    assert stored.title == "Homework: [CMPS453] Project Integration Report"
    assert stored.time_label == "11:59 PM"
    assert stored.details.endswith("Source: https://moodle.example.edu/mod/assign/view.php?id=77")


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__]))
