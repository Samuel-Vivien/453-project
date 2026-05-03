# Desktop Calendar Program Summary

## What The Program Does

This project is a desktop calendar application built with Python and Tkinter. The main program lets a user view a monthly calendar, select a day, and manage multiple saved items for that day.

Core features include:

- Add, edit, and remove calendar items.
- Store item title, details, and an optional time label.
- Save calendar data locally in JSON.
- Import Moodle homework and assignment due dates from Moodle pages.
- Detect source links in item details and open them in a browser.
- Show upcoming due-date reminders while the app is running.
- Support light and dark themes.
- Provide a headless smoke-test mode for automated testing.

The main user-facing file is `calendar_app.py`. Moodle parsing and web crawling logic lives in `moodle_crawler.py`.

## Main Files

### `calendar_app.py`

This is the main desktop application. It defines:

- `CalendarItem`: a dataclass representing one saved calendar entry.
- `CalendarApp`: the Tkinter window and all calendar UI behavior.
- `main()`: the normal application entry point.
- `run_smoke_test()`: a command-line smoke test used by automated tests.

The app starts by creating a `CalendarApp` instance and entering Tkinter's event loop with `mainloop()`.

### `moodle_crawler.py`

This file contains the Moodle import system. It defines:

- `MoodleEvent`: a parsed Moodle due-date item.
- `MoodleCrawler`: the crawler/parser that reads Moodle pages and extracts assignment events.
- Internal HTML parsers for visible text, links, and login forms.

The crawler can fetch Moodle pages, detect login/SSO flows, parse assignment pages, normalize assignment URLs, and return structured `MoodleEvent` objects for the calendar app to store.

### `calendar_items.json`

This is the local data file used during source-code runs. It stores saved calendar items and the next item ID.

Packaged builds use a safer per-user data directory instead of writing beside the executable.

### `build_student_release.py`

This script builds a standalone student-facing release using PyInstaller. The standalone package includes the app runtime so users do not need to install Python manually.

## How The App Starts

Running:

```powershell
python calendar_app.py
```

calls `main()`, which creates `CalendarApp()` and opens the Tkinter window.

During initialization, `CalendarApp`:

1. Sets up theme, window title, size, and current date state.
2. Creates a `MoodleCrawler`.
3. Builds the calendar and sidebar layout.
4. Applies the current theme.
5. Loads saved items from disk.
6. Removes duplicate imported Moodle items if needed.
7. Renders the current month.
8. Builds upcoming due-date reminder text.
9. Schedules periodic due-date reminder checks.

## Calendar Data Model

Each item is stored as a `CalendarItem`:

```python
CalendarItem(
    item_id=1,
    title="Assignment 1",
    details="Read chapters 1-2",
    time_label="11:59 PM",
)
```

Items are grouped by ISO date string:

```json
{
  "next_item_id": 2,
  "items_by_day": {
    "2026-05-01": [
      {
        "item_id": 1,
        "title": "Assignment 1",
        "details": "Read chapters 1-2",
        "time_label": "11:59 PM"
      }
    ]
  }
}
```

The app keeps this data in memory as `items_by_day`, then writes it to JSON whenever items are added, edited, removed, imported, or cleared.

## Calendar UI Flow

The left side of the window is the month calendar. It shows the current month, navigation buttons, weekday labels, and one button per visible day.

When the user clicks a date:

1. The selected date changes.
2. The month grid refreshes.
3. The right-side item list shows items for that day.

The right side of the window contains the item editor. The user can:

- Type a title.
- Type optional time text.
- Type details.
- Add a new item.
- Select an existing item and update it.
- Remove the selected item.
- Clear all calendar data with a two-click confirmation.

## Moodle Import Flow

The Moodle import feature is handled by both `calendar_app.py` and `moodle_crawler.py`.

At a high level:

1. The user enters a Moodle URL and optional login credentials.
2. `CalendarApp._import_moodle_dates()` calls `MoodleCrawler.crawl()`.
3. The crawler fetches pages and follows Moodle-related links.
4. Assignment pages are parsed for due dates, titles, class labels, and source URLs.
5. The crawler returns `MoodleEvent` objects.
6. `CalendarApp._store_moodle_events()` converts those events into `CalendarItem` objects.
7. The calendar saves the updated JSON data and refreshes the UI.

Imported items are deduplicated. The app compares same-day title/time combinations, older class-prefix formats, and normalized source URLs so repeated imports do not create extra copies of the same assignment.

## URL Handling

The app scans item details for URLs. When it finds one, it adds a clickable text tag in the Tkinter details box.

If a link does not include `http://` or `https://`, the app opens it as an HTTPS link.

Moodle source URLs are normalized before duplicate checks. For example, assignment links with extra action parameters are reduced to a stable assignment page URL.

## Due-Date Reminders

The app builds an upcoming due-date notice from saved items. It finds the nearest due date from today onward and includes items due within a short window after that date.

While the app is open, it can show a reminder popup and play a notification sound. It avoids repeating the same reminder too often by tracking the last reminder date and target due date.

## Data File Location

When running from source, the app uses:

```text
calendar_items.json
```

in the project directory.

When running as a packaged executable, it stores data in a user-specific app data folder:

- Windows: `%APPDATA%\Desktop Calendar`
- macOS: `~/Library/Application Support/Desktop Calendar`
- Linux: `$XDG_DATA_HOME/Desktop Calendar` or `~/.local/share/Desktop Calendar`

This prevents app updates from overwriting saved user data.

## Testing Support

The app supports a headless smoke test:

```powershell
python calendar_app.py --smoke-test
```

This does not open the Tkinter window. Instead, it runs a small end-to-end check of the Moodle parsing and calendar import path. Automated tests use this command to verify the main workflow without requiring manual GUI interaction.

The test suite is organized under:

- `tests/unit/`
- `tests/integration/`
- `tests/e2e/`

## How To Run The Program

From the project root:

```powershell
python -m pip install -r requirements.txt
python calendar_app.py
```

Or, on systems where `python3` is used:

```bash
python3 -m pip install -r requirements.txt
python3 calendar_app.py
```

## High-Level Architecture

The project has a simple structure:

```text
Tkinter UI
  -> CalendarApp
      -> Loads and saves CalendarItem data
      -> Renders month/day/item views
      -> Handles user actions
      -> Calls MoodleCrawler for imports

Moodle parsing
  -> MoodleCrawler
      -> Fetches Moodle pages
      -> Parses links and visible text
      -> Extracts assignment due dates
      -> Returns MoodleEvent objects

Persistence
  -> JSON file
      -> Stores next item ID
      -> Stores items grouped by date
```

The UI layer owns the calendar state and saved data. The crawler layer is responsible for converting Moodle pages into structured events. The JSON file is the persistence layer.
