"""Single-window desktop calendar application.

This module provides a Tkinter application that supports adding, editing, and
removing multiple calendar items per day without opening extra windows.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
import calendar
import json
from pathlib import Path
import re
import tkinter as tk
from tkinter import ttk
import webbrowser
from typing import Dict, List, Optional


DATA_FILE = Path(__file__).with_name("calendar_items.json")
URL_PATTERN = re.compile(r"(?i)\b((?:https?://|www\.)[^\s<>\"']+)")


@dataclass
class CalendarItem:
    """Represents a user-created item for a calendar day."""

    item_id: int
    title: str
    details: str = ""
    time_label: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CalendarItem":
        """Builds a CalendarItem from persisted JSON data."""
        return cls(
            item_id=int(data["item_id"]),
            title=str(data["title"]),
            details=str(data.get("details", "")),
            time_label=str(data.get("time_label", "")),
        )


class CalendarApp(tk.Tk):
    """Main application window for managing daily calendar items."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Desktop Calendar")
        self.geometry("1120x700")
        self.minsize(960, 620)

        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.selected_date = today
        self.next_item_id = 1
        self.items_by_day: Dict[str, List[CalendarItem]] = {}
        self._url_tag_to_link: Dict[str, str] = {}

        self.style = ttk.Style(self)
        self.style.configure("SelectedDay.TButton", foreground="#0a4f9c")
        self.style.configure("NormalDay.TButton", foreground="#1f1f1f")
        self.style.configure("Muted.TLabel", foreground="#4a4a4a")

        self._build_layout()
        self._load_items()
        self._refresh_calendar()
        self._refresh_item_list()

    def _build_layout(self) -> None:
        """Creates and arranges all widgets in the single main window."""
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        calendar_panel = ttk.Frame(self, padding=14)
        calendar_panel.grid(row=0, column=0, sticky="nsew")
        calendar_panel.columnconfigure(0, weight=1)
        calendar_panel.rowconfigure(2, weight=1)

        nav_frame = ttk.Frame(calendar_panel)
        nav_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        nav_frame.columnconfigure(1, weight=1)

        self.prev_btn = ttk.Button(nav_frame, text="<", width=4, command=self._go_previous_month)
        self.prev_btn.grid(row=0, column=0, sticky="w")

        self.month_label = ttk.Label(nav_frame, text="", font=("Segoe UI", 15, "bold"))
        self.month_label.grid(row=0, column=1)

        self.next_btn = ttk.Button(nav_frame, text=">", width=4, command=self._go_next_month)
        self.next_btn.grid(row=0, column=2, sticky="e")

        weekdays = ttk.Frame(calendar_panel)
        weekdays.grid(row=1, column=0, sticky="ew")
        weekdays.columnconfigure(tuple(range(7)), weight=1)
        for idx, weekday in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            ttk.Label(weekdays, text=weekday, anchor="center", style="Muted.TLabel").grid(
                row=0, column=idx, sticky="ew", padx=2, pady=(0, 4)
            )

        self.calendar_grid = ttk.Frame(calendar_panel)
        self.calendar_grid.grid(row=2, column=0, sticky="nsew")
        for row in range(6):
            self.calendar_grid.rowconfigure(row, weight=1)
        for col in range(7):
            self.calendar_grid.columnconfigure(col, weight=1)

        self.day_buttons: List[ttk.Button] = []
        for idx in range(42):
            row, col = divmod(idx, 7)
            btn = ttk.Button(
                self.calendar_grid,
                text="",
                style="NormalDay.TButton",
                command=lambda pos=idx: self._select_day_from_button(pos),
            )
            btn.grid(row=row, column=col, sticky="nsew", padx=2, pady=2, ipadx=2, ipady=10)
            self.day_buttons.append(btn)

        side_panel = ttk.Frame(self, padding=14)
        side_panel.grid(row=0, column=1, sticky="nsew")
        side_panel.columnconfigure(0, weight=1)
        side_panel.rowconfigure(1, weight=1)

        self.selected_day_label = ttk.Label(side_panel, text="", font=("Segoe UI", 13, "bold"))
        self.selected_day_label.grid(row=0, column=0, sticky="w", pady=(0, 6))

        items_frame = ttk.LabelFrame(side_panel, text="Items", padding=8)
        items_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        items_frame.columnconfigure(0, weight=1)
        items_frame.rowconfigure(0, weight=1)

        self.item_list = tk.Listbox(items_frame, height=10, exportselection=False)
        self.item_list.grid(row=0, column=0, sticky="nsew")
        self.item_list.bind("<<ListboxSelect>>", self._on_item_selected)

        list_scroll = ttk.Scrollbar(items_frame, orient="vertical", command=self.item_list.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.item_list.config(yscrollcommand=list_scroll.set)

        editor_frame = ttk.LabelFrame(side_panel, text="View / Edit Item", padding=8)
        editor_frame.grid(row=2, column=0, sticky="nsew")
        editor_frame.columnconfigure(1, weight=1)

        ttk.Label(editor_frame, text="Title").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.title_var = tk.StringVar()
        ttk.Entry(editor_frame, textvariable=self.title_var).grid(row=0, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(editor_frame, text="Time").grid(row=1, column=0, sticky="w", pady=(0, 4))
        self.time_var = tk.StringVar()
        ttk.Entry(editor_frame, textvariable=self.time_var).grid(row=1, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(editor_frame, text="Details").grid(row=2, column=0, sticky="nw", pady=(0, 4))
        self.details_text = tk.Text(editor_frame, height=6, wrap="word")
        self.details_text.grid(row=2, column=1, sticky="nsew", pady=(0, 4))
        self.details_text.bind("<KeyRelease>", self._on_details_changed)
        editor_frame.rowconfigure(2, weight=1)

        action_frame = ttk.Frame(editor_frame)
        action_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        action_frame.columnconfigure(tuple(range(4)), weight=1)

        self.add_button = ttk.Button(action_frame, text="Add", command=self._add_item)
        self.add_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.update_button = ttk.Button(action_frame, text="Update", command=self._update_item)
        self.update_button.grid(row=0, column=1, sticky="ew", padx=3)
        self.delete_button = ttk.Button(action_frame, text="Remove", command=self._remove_item)
        self.delete_button.grid(row=0, column=2, sticky="ew", padx=3)
        self.clear_button = ttk.Button(action_frame, text="Clear", command=self._clear_editor)
        self.clear_button.grid(row=0, column=3, sticky="ew", padx=(3, 0))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, relief="groove", anchor="w", padding=6).grid(
            row=1, column=0, columnspan=2, sticky="ew"
        )

        self._button_dates: Dict[int, Optional[date]] = {idx: None for idx in range(42)}

    def _go_previous_month(self) -> None:
        """Navigates the calendar to the previous month."""
        if self.current_month == 1:
            self.current_month = 12
            self.current_year -= 1
        else:
            self.current_month -= 1
        self._refresh_calendar()

    def _go_next_month(self) -> None:
        """Navigates the calendar to the next month."""
        if self.current_month == 12:
            self.current_month = 1
            self.current_year += 1
        else:
            self.current_month += 1
        self._refresh_calendar()

    def _refresh_calendar(self) -> None:
        """Renders the monthly grid using only real dates for the active month view."""
        self.month_label.config(text=f"{calendar.month_name[self.current_month]} {self.current_year}")
        if self.selected_date.month != self.current_month or self.selected_date.year != self.current_year:
            # Keep selection valid when navigating months by snapping to the first day.
            self.selected_date = date(self.current_year, self.current_month, 1)

        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(self.current_year, self.current_month)
        flat_days = [day for week in weeks for day in week]
        visible_rows = len(weeks)
        for row in range(6):
            # Hidden rows receive zero weight so no extra empty row is shown.
            self.calendar_grid.rowconfigure(row, weight=1 if row < visible_rows else 0)

        for idx, btn in enumerate(self.day_buttons):
            if idx >= len(flat_days):
                self._button_dates[idx] = None
                btn.config(text="", state="disabled", style="NormalDay.TButton")
                btn.grid_remove()
                continue

            btn.grid()
            day = flat_days[idx]
            self._button_dates[idx] = day if day.month == self.current_month else None

            if day.month != self.current_month:
                btn.config(text="", state="disabled", style="NormalDay.TButton")
                continue

            count = len(self.items_by_day.get(self._date_key(day), []))
            suffix = f"\n({count})" if count else ""
            btn.config(text=f"{day.day}{suffix}", state="normal")

            style_name = "SelectedDay.TButton" if day == self.selected_date else "NormalDay.TButton"
            btn.config(style=style_name)

        self._refresh_selected_day_label()
        self._refresh_item_list()

    def _select_day_from_button(self, idx: int) -> None:
        """Updates the active date based on the clicked calendar button."""
        mapped_date = self._button_dates.get(idx)
        if mapped_date is None:
            return
        self.selected_date = mapped_date
        self._refresh_calendar()
        self._set_status(f"Selected {self.selected_date.isoformat()}")

    def _refresh_selected_day_label(self) -> None:
        """Updates the sidebar header with the currently selected day."""
        self.selected_day_label.config(text=f"Selected Day: {self.selected_date.strftime('%A, %b %d, %Y')}")

    def _refresh_item_list(self) -> None:
        """Rebuilds the listbox with all items for the selected day."""
        self.item_list.delete(0, tk.END)
        day_items = self.items_by_day.get(self._date_key(self.selected_date), [])
        for item in day_items:
            time_part = f"[{item.time_label}] " if item.time_label.strip() else ""
            self.item_list.insert(tk.END, f"{time_part}{item.title}")
        self._clear_editor(keep_status=True)

    def _on_item_selected(self, _event: object) -> None:
        """Loads the selected item into the inline editor fields."""
        selected_item = self._get_selected_item()
        if selected_item is None:
            return
        self.title_var.set(selected_item.title)
        self.time_var.set(selected_item.time_label)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", selected_item.details)
        self._refresh_details_links()
        self._set_status(f"Loaded item #{selected_item.item_id} into editor")

    def _add_item(self) -> None:
        """Creates a new item for the selected day and persists it."""
        title = self.title_var.get().strip()
        if not title:
            self._set_status("Title is required to add an item.")
            return

        new_item = CalendarItem(
            item_id=self.next_item_id,
            title=title,
            details=self.details_text.get("1.0", tk.END).strip(),
            time_label=self.time_var.get().strip(),
        )
        self.next_item_id += 1

        key = self._date_key(self.selected_date)
        self.items_by_day.setdefault(key, []).append(new_item)
        self._save_items()
        self._refresh_calendar()
        self._set_status(f"Added item for {key}")

    def _update_item(self) -> None:
        """Applies editor changes to the currently selected item."""
        selected_index = self._selected_index()
        if selected_index is None:
            self._set_status("Choose an item from the list before updating.")
            return

        title = self.title_var.get().strip()
        if not title:
            self._set_status("Title is required to update an item.")
            return

        key = self._date_key(self.selected_date)
        items = self.items_by_day.get(key, [])
        if not (0 <= selected_index < len(items)):
            self._set_status("Selected item is no longer available.")
            return

        items[selected_index].title = title
        items[selected_index].time_label = self.time_var.get().strip()
        items[selected_index].details = self.details_text.get("1.0", tk.END).strip()

        self._save_items()
        self._refresh_calendar()
        self.item_list.selection_set(selected_index)
        self._set_status(f"Updated item for {key}")

    def _remove_item(self) -> None:
        """Deletes the selected item from the selected day."""
        selected_index = self._selected_index()
        if selected_index is None:
            self._set_status("Choose an item from the list before removing.")
            return

        key = self._date_key(self.selected_date)
        items = self.items_by_day.get(key, [])
        if not (0 <= selected_index < len(items)):
            self._set_status("Selected item is no longer available.")
            return

        removed_item = items.pop(selected_index)
        if not items:
            self.items_by_day.pop(key, None)

        self._save_items()
        self._refresh_calendar()
        self._set_status(f"Removed '{removed_item.title}' from {key}")

    def _clear_editor(self, keep_status: bool = False) -> None:
        """Clears editor fields so the user can enter a new item quickly."""
        self.item_list.selection_clear(0, tk.END)
        self.title_var.set("")
        self.time_var.set("")
        self.details_text.delete("1.0", tk.END)
        self._refresh_details_links()
        if not keep_status:
            self._set_status("Editor cleared")

    def _on_details_changed(self, _event: object) -> None:
        """Schedules URL tagging after text edits complete."""
        self.after_idle(self._refresh_details_links)

    def _refresh_details_links(self) -> None:
        """Detects URLs in the details field and decorates them as clickable links."""
        for tag_name in list(self._url_tag_to_link):
            self.details_text.tag_delete(tag_name)
        self._url_tag_to_link.clear()

        details_value = self.details_text.get("1.0", "end-1c")
        for match in URL_PATTERN.finditer(details_value):
            raw_link = match.group(1)
            clean_link = raw_link.rstrip(".,;:!?)]}")
            if not clean_link:
                continue

            start_offset = match.start(1)
            end_offset = start_offset + len(clean_link)
            tag_name = f"url_{start_offset}_{end_offset}"
            start_index = f"1.0+{start_offset}c"
            end_index = f"1.0+{end_offset}c"

            self._url_tag_to_link[tag_name] = clean_link
            self.details_text.tag_add(tag_name, start_index, end_index)
            self.details_text.tag_configure(tag_name, foreground="#0a4f9c", underline=True)
            self.details_text.tag_bind(
                tag_name,
                "<Button-1>",
                lambda _event, link=clean_link: self._open_link(link),
            )
            self.details_text.tag_bind(
                tag_name,
                "<Enter>",
                lambda _event: self.details_text.config(cursor="hand2"),
            )
            self.details_text.tag_bind(
                tag_name,
                "<Leave>",
                lambda _event: self.details_text.config(cursor="xterm"),
            )

    def _open_link(self, raw_link: str) -> None:
        """Opens a detected details URL in the user's default web browser."""
        target_link = raw_link
        if not raw_link.lower().startswith(("http://", "https://")):
            target_link = f"https://{raw_link}"

        try:
            opened = webbrowser.open(target_link, new=2)
        except webbrowser.Error:
            opened = False

        if opened:
            self._set_status(f"Opened {target_link}")
        else:
            self._set_status(f"Could not open {target_link}")

    def _selected_index(self) -> Optional[int]:
        """Returns the currently selected listbox index, if any."""
        selection = self.item_list.curselection()
        if not selection:
            return None
        return int(selection[0])

    def _get_selected_item(self) -> Optional[CalendarItem]:
        """Returns the selected CalendarItem for the active day."""
        selected_index = self._selected_index()
        if selected_index is None:
            return None
        day_items = self.items_by_day.get(self._date_key(self.selected_date), [])
        if not (0 <= selected_index < len(day_items)):
            return None
        return day_items[selected_index]

    def _set_status(self, message: str) -> None:
        """Writes a short message into the in-window status bar."""
        self.status_var.set(message)

    def _date_key(self, value: date) -> str:
        """Normalizes a date object into the dictionary key format."""
        return value.isoformat()

    def _load_items(self) -> None:
        """Loads item data from disk, while tolerating malformed JSON safely."""
        if not DATA_FILE.exists():
            return
        try:
            payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._set_status("Could not parse existing data file; starting with empty data.")
            return

        loaded_map = payload.get("items_by_day", {})
        next_id = int(payload.get("next_item_id", 1))
        parsed_map: Dict[str, List[CalendarItem]] = {}
        for key, raw_items in loaded_map.items():
            if not isinstance(raw_items, list):
                continue
            parsed_items = []
            for raw in raw_items:
                if not isinstance(raw, dict) or "title" not in raw or "item_id" not in raw:
                    continue
                parsed_items.append(CalendarItem.from_dict(raw))
            if parsed_items:
                parsed_map[str(key)] = parsed_items

        self.items_by_day = parsed_map
        max_seen_id = max(
            (item.item_id for group in self.items_by_day.values() for item in group),
            default=0,
        )
        self.next_item_id = max(next_id, max_seen_id + 1)

    def _save_items(self) -> None:
        """Persists all calendar items to a JSON file beside the application."""
        serializable_map = {
            key: [asdict(item) for item in items]
            for key, items in self.items_by_day.items()
        }
        payload = {
            "next_item_id": self.next_item_id,
            "items_by_day": serializable_map,
        }
        try:
            DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            self._set_status("Could not save data to disk.")


def main() -> None:
    """Application entry point."""
    app = CalendarApp()
    app.mainloop()


if __name__ == "__main__":
    main()
