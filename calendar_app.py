"""Single-window desktop calendar application.

This module provides a Tkinter application that supports adding, editing, and
removing multiple calendar items per day without opening extra windows.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta
import calendar
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tkinter as tk
import subprocess
from tkinter import ttk
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import webbrowser
from moodle_crawler import MoodleCrawler, MoodleEvent
from typing import Dict, List, Optional, Tuple
import threading
import os
from tkinter import filedialog, messagebox
from tkinter import font as tkfont


class _Tooltip:
    """Simple tooltip implementation for Tkinter widgets."""

    def __init__(self, widget, text: str = "") -> None:
        self.widget = widget
        self.text = text
        self.tipwindow: Optional[tk.Toplevel] = None
        self.widget.bind("<Enter>", self._enter)
        self.widget.bind("<Leave>", self._leave)

    def _enter(self, _event: object) -> None:
        if self.tipwindow:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tipwindow = tk.Toplevel(self.widget)
        self.tipwindow.wm_overrideredirect(True)
        self.tipwindow.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tipwindow, text=self.text, justify="left", bg="#ffffe0", relief="solid", borderwidth=1)
        label.pack(ipadx=6, ipady=3)

    def _leave(self, _event: object) -> None:
        if self.tipwindow:
            try:
                self.tipwindow.destroy()
            except Exception:
                pass
        self.tipwindow = None

from ai_slides import (
    summarize_from_url,
    summarize_from_file,
)
APP_NAME = "Desktop Calendar"

def _source_app_dir() -> Path:
    """Returns the source directory for the application code."""
    return Path(__file__).resolve().parent
DATA_FILENAME = "calendar_items.json"
URL_PATTERN = re.compile(r"(?i)\b((?:https?://|www\.)[^\s<>\"']+)")


def _runtime_app_dir() -> Path:
    """Returns the directory containing the running app bundle or source file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _source_app_dir()


def _get_user_data_dir() -> Path:
    """Returns the per-user writable directory for packaged app data."""
    if sys.platform.startswith("win"):
        appdata_root = os.environ.get("APPDATA")
        if appdata_root:
            return Path(appdata_root) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def _migrate_packaged_data_file(target_file: Path) -> None:
    """Copies legacy local data into the packaged app-data folder on first run."""
    if target_file.exists():
        return

    candidate_paths = [
        _runtime_app_dir() / DATA_FILENAME,
        _source_app_dir() / DATA_FILENAME,
    ]
    seen_paths: set[Path] = set()
    for candidate_path in candidate_paths:
        normalized_candidate = candidate_path.resolve(strict=False)
        if normalized_candidate in seen_paths:
            continue
        seen_paths.add(normalized_candidate)
        if normalized_candidate == target_file.resolve(strict=False) or not candidate_path.exists():
            continue
        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate_path, target_file)
        except OSError:
            pass
        return


def _resolve_data_file() -> Path:
    """Finds a writable JSON data file location for both source and packaged runs."""
    if not getattr(sys, "frozen", False):
        return _source_app_dir() / DATA_FILENAME

    target_file = _get_user_data_dir() / DATA_FILENAME
    try:
        target_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _runtime_app_dir() / DATA_FILENAME

    _migrate_packaged_data_file(target_file)
    return target_file


DATA_FILE = _resolve_data_file()

LIGHT_THEME = {
    "bg": "#f4f6fb",
    "panel": "#ffffff",
    "panel_alt": "#eef2f7",
    "text": "#1f1f1f",
    "muted": "#5f6b7a",
    "accent": "#2563eb",
    "accent_text": "#ffffff",
    "border": "#cbd5e1",
    "input_bg": "#ffffff",
    "input_fg": "#1f1f1f",
    "list_select_bg": "#2563eb",
    "list_select_fg": "#ffffff",
    "overflow": "#8a8f98",
    "status_bg": "#e5e7eb",
}

DARK_THEME = {
    "bg": "#000000",       
    "panel": "#0d0d0d",       
    "panel_alt": "#1a1a1a",   
    "text": "#ffffff",      
    "muted": "#aaaaaa",      
    "accent": "#0a84ff",      
    "accent_text": "#ffffff",
    "border": "#333333",
    "input_bg": "#0a0a0a",
    "input_fg": "#ffffff",
    "list_select_bg": "#2563eb",
    "list_select_fg": "#ffffff",
    "overflow": "#777777",
    "status_bg": "#0d0d0d",
}


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
        """Initializes UI state, loads persisted data, and renders first view."""
        super().__init__()
        self.theme_name = "dark"
        self.theme = DARK_THEME
        self.title("Desktop Calendar")
        self.geometry("1120x700")
        self.minsize(960, 620)

        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self.selected_date = today
        self.next_item_id = 1
        self.items_by_day: Dict[str, List[CalendarItem]] = {}
        # Higher page limit improves assignment metadata coverage for accurate class/date mapping.
        self.moodle_crawler = MoodleCrawler(max_pages=60)
        self._url_tag_to_link: Dict[str, str] = {}
        self._error_window: Optional[tk.Toplevel] = None
        self._error_text: Optional[tk.Text] = None
        self._due_notice_window: Optional[tk.Toplevel] = None
        self._due_notice_text: Optional[tk.Text] = None
        self._last_due_notice_day: Optional[date] = None
        self._last_due_notice_target: Optional[date] = None
        self._due_reminder_after_id: Optional[str] = None
        self._clear_all_confirm_pending = False
        self._clear_all_reset_after_id: Optional[str] = None
        # Safety: keep last saved payload for undo and backups
        self._last_saved_payload: Optional[str] = None
        self._undo_button: Optional[ttk.Button] = None
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self._build_layout()
        # Accessibility: keyboard shortcuts for navigation and item actions
        self.bind("<Left>", lambda e: self._move_selection_by_offset(-1))
        self.bind("<Right>", lambda e: self._move_selection_by_offset(1))
        self.bind("<Up>", lambda e: self._move_selection_by_offset(-7))
        self.bind("<Down>", lambda e: self._move_selection_by_offset(7))
        # Month navigation with Ctrl+Left/Right
        self.bind("<Control-Left>", lambda e: self._go_previous_month())
        self.bind("<Control-Right>", lambda e: self._go_next_month())
        self.bind("<Return>", self._on_enter_pressed)
        self.bind("<Delete>", self._on_delete_pressed)
        # PageUp/PageDown navigate items when the item list has focus
        self.bind("<Prior>", lambda e: self._select_prev_item())
        self.bind("<Next>", lambda e: self._select_next_item())
        self._apply_theme()
        self._load_items()
        removed_count = self._dedupe_existing_import_items()
        if removed_count:
            self._save_items()
        self._refresh_calendar()
        self._refresh_upcoming_due_notice(update_status=True)
        self._schedule_due_reminder_check(initial_delay_ms=300)

    def _build_layout(self) -> None:
        """Creates and arranges all widgets in the single main window."""
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        calendar_panel = ttk.Frame(self, padding=14, style="Panel.TFrame")
        calendar_panel.grid(row=0, column=0, sticky="nsew")
        calendar_panel.columnconfigure(0, weight=1)
        calendar_panel.rowconfigure(2, weight=1)

        nav_frame = ttk.Frame(calendar_panel, style="Panel.TFrame")
        nav_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        nav_frame.columnconfigure(1, weight=1)

        self.prev_btn = ttk.Button(nav_frame, text="<", width=4, command=self._go_previous_month)
        self.prev_btn.grid(row=0, column=0, sticky="w")

        self.month_label = ttk.Label(nav_frame, text="", font=("Segoe UI", 15, "bold"), style="Panel.TLabel")
        self.month_label.grid(row=0, column=1)

        self.next_btn = ttk.Button(nav_frame, text=">", width=4, command=self._go_next_month)
        self.next_btn.grid(row=0, column=2, sticky="e")

        self.theme_button = ttk.Button(nav_frame, text="Light Mode", command=self._toggle_theme)
        self.theme_button.grid(row=0, column=3, sticky="e", padx=(8, 0))

        weekdays = ttk.Frame(calendar_panel, style="Panel.TFrame")
        weekdays.grid(row=1, column=0, sticky="ew")
        weekdays.columnconfigure(tuple(range(7)), weight=1)
        for idx, weekday in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            ttk.Label(weekdays, text=weekday, anchor="center", style="Muted.TLabel").grid(
                row=0, column=idx, sticky="ew", padx=2, pady=(0, 4)
            )

        self.calendar_grid = ttk.Frame(calendar_panel, style="Panel.TFrame")
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
            # show hover preview of items for accessibility and quick scan
            btn.bind("<Enter>", lambda e, i=idx: self._show_day_preview(i))
            btn.bind("<Leave>", lambda e: self._hide_day_preview())
            self.day_buttons.append(btn)

        side_panel = ttk.Frame(self, padding=14, style="Panel.TFrame")
        side_panel.grid(row=0, column=1, sticky="nsew")
        side_panel.columnconfigure(0, weight=1)
        side_panel.rowconfigure(1, weight=1)

        self.selected_day_label = ttk.Label(side_panel, text="", font=("Segoe UI", 13, "bold"), style="Panel.TLabel")
        self.selected_day_label.grid(row=0, column=0, sticky="w", pady=(0, 6))

        items_frame = ttk.Frame(side_panel, padding=8, style="Panel.TFrame")
        ttk.Label(items_frame, text="Items", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        items_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        items_frame.columnconfigure(0, weight=1)
        items_frame.rowconfigure(0, weight=1)

        

        self.item_list = tk.Listbox(items_frame, height=10, exportselection=False)
        self.item_list.grid(row=1, column=0, sticky="nsew")
        self.item_list.bind("<<ListboxSelect>>", self._on_item_selected)

        list_scroll = ttk.Scrollbar(items_frame, orient="vertical", command=self.item_list.yview)
        list_scroll.grid(row=1, column=1, sticky="ns")
        self.item_list.config(yscrollcommand=list_scroll.set)

        # Search / filter for items in selected day
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(items_frame, textvariable=self.search_var)
        self.search_entry.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.search_entry.bind("<KeyRelease>", lambda e: self._apply_search_filter())

        editor_frame = ttk.Frame(side_panel, padding=8, style="Panel.TFrame")
        ttk.Label(editor_frame, text="View / Edit Item", style="Panel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        editor_frame.grid(row=2, column=0, sticky="nsew")
        editor_frame.columnconfigure(1, weight=1)

        ttk.Label(editor_frame, text="Title").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(editor_frame, textvariable=self.title_var)
        self.title_entry.grid(row=0, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(editor_frame, text="Time").grid(row=1, column=0, sticky="w", pady=(0, 4))
        self.time_var = tk.StringVar()
        self.time_entry = ttk.Entry(editor_frame, textvariable=self.time_var)
        self.time_entry.grid(row=1, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(editor_frame, text="Details").grid(row=2, column=0, sticky="nw", pady=(0, 4))
        self.details_text = tk.Text(editor_frame, height=6, wrap="word")
        self.details_text.grid(row=2, column=1, sticky="nsew", pady=(0, 4))
        self.details_text.bind("<KeyRelease>", self._on_details_changed)
        editor_frame.rowconfigure(2, weight=1)
        editor_frame.columnconfigure(2, weight=0)

        # Prev/Next buttons placed next to the Details editor for per-day item navigation
        nav_btn_frame = ttk.Frame(editor_frame)
        nav_btn_frame.grid(row=2, column=2, sticky="ns", padx=(8, 0))
        self.prev_item_btn = ttk.Button(nav_btn_frame, text="◀", width=3, command=self._select_prev_item)
        self.prev_item_btn.grid(row=0, column=0, pady=(0, 6))
        self.next_item_btn = ttk.Button(nav_btn_frame, text="▶", width=3, command=self._select_next_item)
        self.next_item_btn.grid(row=1, column=0)

        action_frame = ttk.Frame(editor_frame, style="Panel.TFrame")
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

        moodle_frame = ttk.Frame(side_panel, padding=8, style="Panel.TFrame")
        ttk.Label(moodle_frame, text="Moodle Import", style="Panel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        moodle_frame.grid(row=3, column=0, sticky="ew")
        moodle_frame.columnconfigure(1, weight=1)

        ttk.Label(moodle_frame, text="Moodle Dashboard Url").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.moodle_url_var = tk.StringVar()
        self.moodle_url_entry = ttk.Entry(moodle_frame, textvariable=self.moodle_url_var)
        self.moodle_url_entry.grid(row=0, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(moodle_frame, text="School Email").grid(row=1, column=0, sticky="w", pady=(0, 4))
        self.moodle_username_var = tk.StringVar()
        self.moodle_username_entry = ttk.Entry(moodle_frame, textvariable=self.moodle_username_var)
        self.moodle_username_entry.grid(row=1, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(moodle_frame, text="Password").grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.moodle_password_var = tk.StringVar()
        self.moodle_password_entry = ttk.Entry(moodle_frame, textvariable=self.moodle_password_var, show="*")
        self.moodle_password_entry.grid(row=2, column=1, sticky="ew", pady=(0, 4))

        self.import_moodle_btn = ttk.Button(moodle_frame, text="Import Moodle Dates", command=self._import_moodle_dates)
        self.import_moodle_btn.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 4))

        self.moodle_info_var = tk.StringVar(
            value="Imports homework/assignment due dates from Moodle text content."
        )
        ttk.Label(
            moodle_frame,
            textvariable=self.moodle_info_var,
            wraplength=320,
            style="Muted.TLabel",
        ).grid(row=4, column=0, columnspan=2, sticky="w")
        # AI Slides section
        ai_frame = ttk.Frame(side_panel, padding=8, style="Panel.TFrame")
        ttk.Label(ai_frame, text="AI Slides", style="Panel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ai_frame.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ai_frame.columnconfigure(1, weight=1)

        ttk.Label(ai_frame, text="Presentation File").grid(row=1, column=0, sticky="w", pady=(0, 4))
        self.ai_url_var = tk.StringVar()
        file_row = ttk.Frame(ai_frame)
        file_row.grid(row=1, column=1, sticky="ew", pady=(0, 4))
        file_row.columnconfigure(0, weight=1)
        self.ai_url_entry = ttk.Entry(file_row, textvariable=self.ai_url_var)
        self.ai_url_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(file_row, text="Browse…", command=self._browse_presentation_file).grid(row=0, column=1, sticky="e", padx=(6, 0))

        btn_row = ttk.Frame(ai_frame, style="Panel.TFrame")
        btn_row.grid(row=2, column=0, columnspan=2, sticky="ew")
        btn_row.columnconfigure((0, 1), weight=1)
        self.summarize_btn = ttk.Button(btn_row, text="Summarize Slides", command=self._on_summarize_slides)
        self.summarize_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.open_fullscreen_btn = ttk.Button(btn_row, text="Open Fullscreen", command=self._open_ai_fullscreen)
        self.open_fullscreen_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.ai_result_text = tk.Text(ai_frame, height=10, wrap="word")
        self.ai_result_text.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(8, 0), padx=8)
        ai_frame.rowconfigure(3, weight=1)

        self.clear_all_button = ttk.Button(
            moodle_frame,
            text="Clear All Calendar Data",
            command=self._on_clear_all_requested,
        )
        self.clear_all_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # (Import/Export removed)

        self.restore_backup_button = ttk.Button(moodle_frame, text="Restore Backup…", command=self._restore_backup)
        self.restore_backup_button.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # Tooltips for primary actions
        try:
            _Tooltip(self.prev_btn, "Previous month (Left / Ctrl+Left)")
            _Tooltip(self.next_btn, "Next month (Right / Ctrl+Right)")
            _Tooltip(self.theme_button, "Toggle light/dark theme")
            _Tooltip(self.add_button, "Add item (Enter)")
            _Tooltip(self.delete_button, "Remove selected item (Delete)")
            _Tooltip(self.clear_all_button, "Clear all saved calendar data (with confirmation)")
            _Tooltip(self.prev_item_btn, "Show previous item on selected day (PageUp)")
            _Tooltip(self.next_item_btn, "Show next item on selected day (PageDown)")
            _Tooltip(self.restore_backup_button, "Restore from a timestamped backup file")
            _Tooltip(self.import_moodle_btn, "Import due dates from Moodle pages")
            _Tooltip(self.summarize_btn, "Summarize selected presentation with AI")
        except Exception:
            pass

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = tk.Label(self, textvariable=self.status_var, anchor="w", padx=8, pady=6)
        self.status_label.grid(row=1, column=0, columnspan=2, sticky="ew")

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

    def _toggle_theme(self) -> None:
        """Switches between light mode and dark mode."""
        if self.theme_name == "dark":
            self.theme_name = "light"
            self.theme = LIGHT_THEME
        else:
            self.theme_name = "dark"
            self.theme = DARK_THEME

        self._apply_theme()
        self._refresh_details_links()

    def _apply_theme(self) -> None:
        """Applies the current theme colors to the app and popup windows."""
        t = self.theme

        self.configure(bg=t["bg"])

        self.style.configure("TFrame", background=t["bg"])
        self.style.configure("TLabel", background=t["bg"], foreground=t["text"])
        self.style.configure("Panel.TFrame", background=t["panel"])
        self.style.configure("Panel.TLabel", background=t["panel"], foreground=t["text"])
        self.style.configure("Muted.TLabel", background=t["bg"], foreground=t["muted"])

        self.style.configure(
            "TLabelFrame",
            background=t["panel"],
            foreground=t["text"],
            bordercolor=t["border"],
            relief="solid",
        )
        self.style.configure(
            "TLabelFrame.Label",
            background=t["panel"],
            foreground=t["text"],
        )

        self.style.configure(
            "TButton",
            background=t["panel_alt"],
            foreground=t["text"],
            bordercolor=t["border"],
            focuscolor=t["accent"],
            padding=6,
        )
        self.style.map(
            "TButton",
            background=[("active", t["accent"]), ("pressed", t["accent"])],
            foreground=[("active", t["accent_text"]), ("pressed", t["accent_text"])],
        )

        self.style.configure(
            "NormalDay.TButton",
            background=t["panel"],
            foreground=t["text"],
            bordercolor=t["border"],
            padding=10,
        )
        self.style.map(
            "NormalDay.TButton",
            background=[("active", t["panel_alt"])],
            foreground=[("active", t["text"])],
        )

        self.style.configure(
            "SelectedDay.TButton",
            background=t["accent"],
            foreground=t["accent_text"],
            bordercolor=t["accent"],
            padding=10,
        )
        self.style.map(
            "SelectedDay.TButton",
            background=[("active", t["accent"])],
            foreground=[("active", t["accent_text"])],
        )

        self.style.configure(
            "OverflowDay.TButton",
            background=t["panel_alt"],
            foreground=t["overflow"],
            bordercolor=t["border"],
            padding=10,
        )

        self.style.configure(
            "TEntry",
            fieldbackground=t["input_bg"],
            foreground=t["input_fg"],
            bordercolor=t["border"],
            insertcolor=t["input_fg"],
        )

        self.style.configure(
            "Vertical.TScrollbar",
            background=t["panel_alt"],
            troughcolor=t["bg"],
            bordercolor=t["border"],
            arrowcolor=t["text"],
        )

        self.item_list.configure(
            bg=t["input_bg"],
            fg=t["input_fg"],
            selectbackground=t["list_select_bg"],
            selectforeground=t["list_select_fg"],
            highlightbackground=t["border"],
            highlightcolor=t["accent"],
            relief="flat",
        )

        self.details_text.configure(
            bg=t["input_bg"],
            fg=t["input_fg"],
            insertbackground=t["input_fg"],
            highlightbackground=t["border"],
            highlightcolor=t["accent"],
            relief="flat",
        )

        if hasattr(self, "status_label"):
            self.status_label.configure(bg=t["status_bg"], fg=t["text"])

        if hasattr(self, "theme_button"):
            self.theme_button.config(text="Light Mode" if self.theme_name == "dark" else "Dark Mode")

        if self._due_notice_window is not None and self._due_notice_window.winfo_exists():
            self._due_notice_window.configure(bg=t["bg"])
        if self._due_notice_text is not None and self._due_notice_text.winfo_exists():
            self._due_notice_text.configure(
                bg=t["input_bg"],
                fg=t["input_fg"],
                insertbackground=t["input_fg"],
            )

        if self._error_window is not None and self._error_window.winfo_exists():
            self._error_window.configure(bg=t["bg"])
        if self._error_text is not None and self._error_text.winfo_exists():
            self._error_text.configure(
                bg=t["input_bg"],
                fg=t["input_fg"],
                insertbackground=t["input_fg"],
            )

    def _refresh_calendar(self) -> None:
        """Renders the monthly grid showing current month dates with overflow from previous/next months."""
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
            is_current_month = day.month == self.current_month
            self._button_dates[idx] = day if is_current_month else None

            if is_current_month:
                count = len(self.items_by_day.get(self._date_key(day), []))
                suffix = f"\n({count})" if count else ""
                btn.config(text=f"{day.day}{suffix}", state="normal")
                style_name = "SelectedDay.TButton" if day == self.selected_date else "NormalDay.TButton"
                btn.config(style=style_name)
            else:
                btn.config(text=f"{day.day}", state="disabled", style="OverflowDay.TButton")

        self._refresh_selected_day_label()
        self._refresh_item_list()

    def _move_selection_by_offset(self, offset: int) -> None:
        """Move the selected day by an offset within the visible calendar grid."""
        # find current index
        current_idx = None
        for idx, d in self._button_dates.items():
            if d is not None and d == self.selected_date:
                current_idx = idx
                break
        if current_idx is None:
            return
        target = current_idx + offset
        # clamp and search nearest valid
        while 0 <= target < len(self.day_buttons):
            mapped = self._button_dates.get(target)
            if mapped is not None:
                self._select_day_from_button(target)
                return
            target += (1 if offset > 0 else -1)

    def _show_day_preview(self, idx: int) -> None:
        """Shows a small popup listing items for the hovered day button."""
        mapped = self._button_dates.get(idx)
        if mapped is None:
            return
        items = self.items_by_day.get(self._date_key(mapped), [])
        if not items:
            return
        try:
            widget = self.day_buttons[idx]
            text = "\n".join(f"[{it.time_label}] {it.title}" if it.time_label else it.title for it in items)
            # reuse tooltip class for preview
            if not hasattr(self, "_day_preview_tooltip") or self._day_preview_tooltip is None:
                self._day_preview_tooltip = _Tooltip(widget, text)
            else:
                # update text by recreating
                try:
                    self._day_preview_tooltip._leave(None)
                except Exception:
                    pass
                self._day_preview_tooltip = _Tooltip(widget, text)
        except Exception:
            pass

    def _hide_day_preview(self) -> None:
        try:
            if hasattr(self, "_day_preview_tooltip") and self._day_preview_tooltip is not None:
                self._day_preview_tooltip._leave(None)
                self._day_preview_tooltip = None
        except Exception:
            pass

    def _apply_search_filter(self) -> None:
        """Filters items shown in the sidebar listbox for the selected day."""
        term = (self.search_var.get() or "").strip().lower()
        # if placeholder text is present, ignore
        if term == "filter items...":
            term = ""
        self.item_list.delete(0, tk.END)
        day_items = self.items_by_day.get(self._date_key(self.selected_date), [])
        for item in day_items:
            time_part = f"[{item.time_label}] " if item.time_label.strip() else ""
            display = f"{time_part}{item.title}"
            details = (item.details or "").lower()
            if not term or term in display.lower() or term in details:
                self.item_list.insert(tk.END, display)

    def _select_day_from_button(self, idx: int) -> None:
        """Updates the active date based on the clicked calendar button."""
        mapped_date = self._button_dates.get(idx)
        if mapped_date is None:
            return
        # Select the date and show its items in the right-side panel.
        self.selected_date = mapped_date
        self._refresh_calendar()
        try:
            self._apply_search_filter()
            if self.item_list.size() > 0:
                # focus and auto-select the first item so editor is populated
                self.item_list.focus_set()
                try:
                    self.item_list.selection_clear(0, tk.END)
                    self.item_list.selection_set(0)
                    self.item_list.see(0)
                    # directly load the selected item into the editor
                    self._on_item_selected(None)
                except Exception:
                    pass
        except Exception:
            pass
        self._set_status(f"Selected {self.selected_date.isoformat()}")

    def _open_day_modal(self, day_value: date) -> None:
        """Opens a modal dialog showing items for `day_value` and allows editing.

        The dialog is transient and grabs focus; the main window is blocked until
        the dialog is closed to meet the requested workflow.
        """
        if hasattr(self, "_day_modal") and self._day_modal is not None and self._day_modal.winfo_exists():
            try:
                self._day_modal.lift()
            except Exception:
                pass
            return

        self.selected_date = day_value
        self._refresh_calendar()

        modal = tk.Toplevel(self)
        self._day_modal = modal
        modal.title(f"Day View — {day_value.strftime('%A, %b %d, %Y')}")
        # position on the right side of the main window
        try:
            self.update_idletasks()
            main_x = self.winfo_rootx()
            main_y = self.winfo_rooty()
            main_w = self.winfo_width()
            main_h = self.winfo_height()
            modal_w = max(420, int(main_w * 0.35))
            modal_h = max(360, int(main_h * 0.7))
            geom_x = main_x + main_w - modal_w - 20
            geom_y = main_y + 40
            modal.geometry(f"{modal_w}x{modal_h}+{geom_x}+{geom_y}")
        except Exception:
            pass

        modal.transient(self)
        modal.grab_set()
        modal.columnconfigure(0, weight=1)
        modal.rowconfigure(1, weight=1)

        header = ttk.Label(modal, text=f"Items for {day_value.strftime('%A, %b %d, %Y')}", font=(None, 12, "bold"))
        header.grid(row=0, column=0, sticky="w", padx=12, pady=(8, 4))

        list_frame = ttk.Frame(modal)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        day_list = tk.Listbox(list_frame, exportselection=False)
        day_list.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=day_list.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        day_list.config(yscrollcommand=scroll.set)

        editor = ttk.Frame(modal)
        editor.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 8))
        editor.columnconfigure(1, weight=1)

        ttk.Label(editor, text="Title").grid(row=0, column=0, sticky="w")
        m_title = tk.StringVar()
        m_title_entry = ttk.Entry(editor, textvariable=m_title)
        m_title_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(editor, text="Time").grid(row=1, column=0, sticky="w")
        m_time = tk.StringVar()
        m_time_entry = ttk.Entry(editor, textvariable=m_time)
        m_time_entry.grid(row=1, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(editor, text="Details").grid(row=2, column=0, sticky="nw")
        m_details = tk.Text(editor, height=6, wrap="word")
        m_details.grid(row=2, column=1, sticky="nsew", padx=(6, 0))

        btn_row = ttk.Frame(modal)
        btn_row.grid(row=3, column=0, sticky="e", padx=12, pady=(6, 12))

        def _refresh_day_list():
            day_list.delete(0, tk.END)
            items = self.items_by_day.get(self._date_key(day_value), [])
            for it in items:
                prefix = f"[{it.time_label}] " if it.time_label.strip() else ""
                day_list.insert(tk.END, prefix + it.title)

        def _on_day_selected(_ev=None):
            sel = day_list.curselection()
            if not sel:
                m_title.set("")
                m_time.set("")
                m_details.delete("1.0", tk.END)
                return
            idx = int(sel[0])
            items = self.items_by_day.get(self._date_key(day_value), [])
            if not (0 <= idx < len(items)):
                return
            it = items[idx]
            m_title.set(it.title)
            m_time.set(it.time_label)
            m_details.delete("1.0", tk.END)
            m_details.insert("1.0", it.details)

        def _add_modal_item():
            title = m_title.get().strip()
            if not title:
                self._set_status("Title required to add item.")
                return
            itm = CalendarItem(item_id=self.next_item_id, title=title, details=m_details.get("1.0", tk.END).strip(), time_label=m_time.get().strip())
            self.next_item_id += 1
            key = self._date_key(day_value)
            self.items_by_day.setdefault(key, []).append(itm)
            self._save_items()
            _refresh_day_list()
            self._refresh_calendar()
            self._set_status(f"Added item for {key}")

        def _update_modal_item():
            sel = day_list.curselection()
            if not sel:
                self._set_status("Select an item to update.")
                return
            idx = int(sel[0])
            key = self._date_key(day_value)
            items = self.items_by_day.get(key, [])
            if not (0 <= idx < len(items)):
                return
            items[idx].title = m_title.get().strip()
            items[idx].time_label = m_time.get().strip()
            items[idx].details = m_details.get("1.0", tk.END).strip()
            self._save_items()
            _refresh_day_list()
            self._refresh_calendar()
            self._set_status(f"Updated item for {key}")

        def _remove_modal_item():
            sel = day_list.curselection()
            if not sel:
                self._set_status("Select an item to remove.")
                return
            idx = int(sel[0])
            key = self._date_key(day_value)
            items = self.items_by_day.get(key, [])
            if not (0 <= idx < len(items)):
                return
            removed = items.pop(idx)
            if not items:
                self.items_by_day.pop(key, None)
            self._save_items()
            _refresh_day_list()
            self._refresh_calendar()
            self._set_status(f"Removed '{removed.title}' from {key}")

        day_list.bind("<<ListboxSelect>>", _on_day_selected)

        ttk.Button(btn_row, text="Add", command=_add_modal_item).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btn_row, text="Update", command=_update_modal_item).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(btn_row, text="Remove", command=_remove_modal_item).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(btn_row, text="Close", command=lambda: (modal.grab_release(), modal.destroy())).grid(row=0, column=3)

        _refresh_day_list()
        m_title_entry.focus_set()

    def _refresh_selected_day_label(self) -> None:
        """Updates the sidebar header with the currently selected day."""
        self.selected_day_label.config(text=f"Selected Day: {self.selected_date.strftime('%A, %b %d, %Y')}")

    def _refresh_item_list(self) -> None:
        """Rebuilds the listbox with all items for the selected day."""
        # Use the shared search/filter routine so the displayed list respects filters
        self._apply_search_filter()
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
        self._refresh_upcoming_due_notice()
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
        self._refresh_upcoming_due_notice()
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
        self._refresh_upcoming_due_notice()
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

    def _on_clear_all_requested(self) -> None:
        """Handles in-window two-click confirmation before deleting all saved data."""
        if not self.items_by_day:
            self._set_status("Calendar is already empty.")
            self._reset_clear_all_confirmation()
            return

        if not self._clear_all_confirm_pending:
            self._clear_all_confirm_pending = True
            self.clear_all_button.config(text="Confirm Clear All")
            if self._clear_all_reset_after_id is not None:
                self.after_cancel(self._clear_all_reset_after_id)
            self._clear_all_reset_after_id = self.after(
                8000,
                lambda: self._reset_clear_all_confirmation(timeout_notice=True),
            )
            self._set_status("Click 'Confirm Clear All' within 8 seconds to reset all calendar data.")
            return

        # Backup current data before clearing so undo is possible
        backup_path = self._backup_before_clear()
        day_count = len(self.items_by_day)
        item_count = sum(len(items) for items in self.items_by_day.values())
        self.items_by_day.clear()
        self.next_item_id = 1
        self._reset_clear_all_confirmation()
        self._save_items()
        self._refresh_calendar()
        self._refresh_upcoming_due_notice()
        self._clear_editor(keep_status=True)
        self._set_status(f"Cleared {item_count} items across {day_count} day(s).")

        # Show transient Undo button to restore last payload
        try:
            if self._undo_button is None or not self._undo_button.winfo_exists():
                self._undo_button = ttk.Button(self, text="Undo Clear", command=self._undo_clear)
                self._undo_button.grid(row=1, column=1, sticky="e", padx=8)
                # hide undo after 10s
                self.after(10000, lambda: (self._undo_button.destroy() if self._undo_button is not None else None))
            if backup_path is not None:
                self._set_status(self.status_var.get() + f" Backup: {backup_path.name}")
        except Exception:
            pass

    def _reset_clear_all_confirmation(self, timeout_notice: bool = False) -> None:
        """Resets clear-all confirmation state and restores default button text."""
        if self._clear_all_reset_after_id is not None:
            self.after_cancel(self._clear_all_reset_after_id)
            self._clear_all_reset_after_id = None
        self._clear_all_confirm_pending = False
        self.clear_all_button.config(text="Clear All Calendar Data")
        if timeout_notice:
            self._set_status("Clear-all confirmation timed out.")

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
            self.details_text.tag_configure(tag_name, foreground=self.theme["accent"], underline=True)
            self.details_text.tag_bind(
                tag_name,
                "<Button-1>",
                lambda _event, link=clean_link: self._open_link(link),
            )
            # Right-click (Windows) or middle-click (macOS) shows a browser choice menu
            self.details_text.tag_bind(
                tag_name,
                "<Button-3>",
                lambda event, link=clean_link: self._show_link_context_menu(event, link),
            )
            self.details_text.tag_bind(
                tag_name,
                "<Button-2>",
                lambda event, link=clean_link: self._show_link_context_menu(event, link),
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

    def _show_link_context_menu(self, event: object, link: str) -> None:
        """Shows a context menu offering browser choices for opening `link`."""
        try:
            menu = tk.Menu(self, tearoff=0)
            choices = [
                "System Default",
                "Microsoft Edge",
                "Google Chrome",
                "Firefox",
                "Brave",
                "Opera",
            ]

            for choice in choices:
                menu.add_command(
                    label=choice,
                    command=lambda c=choice, l=link: (
                        self._open_link_with_browser(l, c)
                    ),
                )

            # show menu at pointer
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        except Exception:
            # fallback to direct open
            self._open_link(link)

    def _open_link_with_browser(self, target_link: str, browser_name: str) -> bool:
        """Attempt to open `target_link` in the named browser. Returns True on success."""
        if not target_link.lower().startswith(("http://", "https://")):
            target_link = f"https://{target_link}"

        # System default just delegates to webbrowser
        if browser_name == "System Default":
            try:
                opened = webbrowser.open(target_link, new=2)
                if opened:
                    self._set_status(f"Opened {target_link} in system default browser")
                else:
                    self._set_status(f"Could not open {target_link} in system default browser")
                return bool(opened)
            except Exception:
                return False

        candidates: Dict[str, List[str]] = {
            "Google Chrome": [
                "chrome",
                "google-chrome",
                r"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                r"C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            ],
            "Microsoft Edge": [
                "msedge",
                r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
            ],
            "Firefox": [
                "firefox",
                r"C:\\Program Files\\Mozilla Firefox\\firefox.exe",
                r"C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe",
            ],
            "Brave": [
                "brave",
                r"C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
            ],
            "Opera": [
                "opera",
                r"C:\\Program Files\\Opera\\launcher.exe",
            ],
        }

        probes = candidates.get(browser_name, [])

        for probe in probes:
            try:
                exe = shutil.which(probe)
                if exe:
                    subprocess.Popen([exe, target_link], shell=False)
                    self._set_status(f"Opened {target_link} in {browser_name}")
                    return True
                # if probe looks like a path
                if os.path.exists(probe):
                    subprocess.Popen([probe, target_link], shell=False)
                    self._set_status(f"Opened {target_link} in {browser_name}")
                    return True
            except Exception:
                continue

        # Last resort: try webbrowser controllers by common names
        try:
            for key in ("chrome", "msedge", "firefox", "brave", "opera"):
                try:
                    ctrl = webbrowser.get(key)
                    ctrl.open(target_link, new=2)
                    self._set_status(f"Opened {target_link} in {browser_name}")
                    return True
                except Exception:
                    continue
        except Exception:
            pass

        # All attempts failed
        self._set_status(f"Could not open {target_link} in {browser_name}")
        return False

    def _import_moodle_dates(self) -> None:
        """Crawls Moodle pages and imports dated class items into the calendar."""
        moodle_url = self.moodle_url_var.get().strip()
        if not moodle_url:
            self._set_status("Enter a Moodle URL before importing.")
            self._show_error("Enter a Moodle URL before importing.", "Missing Moodle URL")
            return

        username = self.moodle_username_var.get().strip()
        password = self.moodle_password_var.get()
        self._set_status("Reading Moodle pages...")
        # feedback: disable import button and show busy cursor
        try:
            self.import_moodle_btn.config(state="disabled")
        except Exception:
            pass
        try:
            self.config(cursor="watch")
        except Exception:
            pass
        self.update_idletasks()

        try:
            events, login_required, message = self.moodle_crawler.crawl(
                moodle_url,
                username=username,
                password=password,
            )
        except Exception as exc:
            print(f"Moodle import exception: {exc}")
            safe_message = self._sanitize_user_message("Unexpected import error. Please try again.")
            self.moodle_info_var.set(safe_message)
            self._set_status(safe_message)
            self._show_error(safe_message, "Moodle Import Error")
            return
        finally:
            try:
                self.import_moodle_btn.config(state="normal")
            except Exception:
                pass
            try:
                self.config(cursor="")
            except Exception:
                pass

        safe_message = self._sanitize_user_message(message)
        if login_required:
            self.moodle_info_var.set(safe_message)
            self._set_status(safe_message)
            self._show_error(safe_message, "Moodle Login Error")
            self.moodle_username_entry.focus_set()
            return

        if not events:
            self.moodle_info_var.set(safe_message)
            self._set_status(safe_message)
            self._show_error(safe_message, "Moodle Import Error")
            return

        added_count, skipped_count, updated_count = self._store_moodle_events(events)
        self._refresh_calendar()
        self._refresh_upcoming_due_notice()
        self.moodle_info_var.set(safe_message)
        self._set_status(
            f"Imported {added_count} Moodle items. Updated {updated_count} existing items. Skipped {skipped_count} duplicates."
        )

    def _browse_presentation_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select presentation file",
            filetypes=(
                ("Presentations and PDFs", "*.pptx *.ppt *.pdf"),
                ("All files", "*.*"),
            ),
        )
        if path:
            self.ai_url_var.set(path)

    def _on_summarize_slides(self) -> None:
        url = self.ai_url_var.get().strip()
        if not url:
            self._set_status("Choose a presentation file first.")
            return
        self._set_status("Summarizing slides...")
        self.ai_result_text.delete("1.0", tk.END)
        # disable AI buttons while running
        try:
            self.summarize_btn.config(state="disabled")
            self.open_fullscreen_btn.config(state="disabled")
        except Exception:
            pass
        threading.Thread(target=self._summarize_worker, args=(url,), daemon=True).start()

    def _summarize_worker(self, url_or_path: str) -> None:
        import traceback

        summary = None
        try:
            self.after(0, lambda: self._set_status("Reading file for summarization..."))
            if os.path.exists(url_or_path):
                self.after(0, lambda: self._set_status("Extracting text from file..."))
                summary = summarize_from_file(url_or_path)
            else:
                self.after(0, lambda: self._set_status("Downloading and extracting slides..."))
                summary = summarize_from_url(url_or_path)
            self.after(0, lambda: self._set_status("Formatting summary..."))
        except Exception as exc:
            tb = traceback.format_exc()
            print("Summarize worker exception:\n", tb)
            # show detailed error to user
            self.after(0, lambda: self._show_error(f"AI summarize error:\n{tb}", "AI Error"))
            self.after(0, lambda: self._set_status("Summarize failed."))
            summary = None
        finally:
            # re-enable buttons on main thread
            self.after(0, lambda: self.summarize_btn.config(state="normal"))
            self.after(0, lambda: self.open_fullscreen_btn.config(state="normal"))

        if summary is not None:
            self.after(0, lambda: self._display_ai_result(summary))
            self.after(0, lambda: self._set_status("AI summary ready."))

    def _on_generate_questions(self) -> None:
        # Generate Questions feature removed — kept for backward compatibility placeholder.
        self._set_status("Generate Questions removed. Use Summarize Slides.")

    def _questions_worker(self, url_or_path: str) -> None:
        # Question generation worker removed.
        self.after(0, lambda: self._set_status("Generate Questions removed."))

    def _display_ai_result(self, content: str) -> None:
        self._ensure_ai_fonts()
        self.ai_result_text.config(state="normal")
        # ensure readable font and spacing in embedded view
        try:
            self.ai_result_text.configure(font=self._ai_fonts["body"])
        except Exception:
            pass
        self.ai_result_text.delete("1.0", tk.END)
        mode = getattr(self, "ai_format_var", None)
        mode_val = mode.get() if mode is not None else "Sections"
        self._format_and_insert_text(self.ai_result_text, content, compact=True, mode=mode_val)
        self.ai_result_text.config(state="disabled")
        self._set_status("AI content ready")

    def _ensure_ai_fonts(self) -> None:
        if hasattr(self, "_ai_fonts"):
            return
        base = tkfont.nametofont("TkDefaultFont")
        self._ai_fonts = {
            "heading": tkfont.Font(family=base.cget("family"), size=max(base.cget("size") + 6, 14), weight="bold"),
            "body": tkfont.Font(family=base.cget("family"), size=base.cget("size") + 2),
            "mono": tkfont.Font(family="Consolas" if os.name == "nt" else "Courier", size=base.cget("size") + 1),
        }

    def _format_and_insert_text(self, widget: tk.Text, content: str, compact: bool = False, mode: str = "Sections") -> None:
        """Insert `content` into `widget` with simple formatting: heading, bullets, paragraphs.

        If `compact` is True use slightly smaller spacing for the embedded panel.
        """
        self._ensure_ai_fonts()
        widget.tag_configure("heading", font=self._ai_fonts["heading"], spacing1=6, spacing3=12)
        widget.tag_configure(
            "para",
            font=self._ai_fonts["body"],
            lmargin1=4,
            lmargin2=8,
            spacing1=4,
            spacing3=(8 if compact else 14),
        )
        widget.tag_configure(
            "bullet",
            font=self._ai_fonts["body"],
            lmargin1=20,
            lmargin2=36,
            spacing1=2,
            spacing3=(6 if compact else 10),
        )
        widget.tag_configure(
            "code",
            font=self._ai_fonts["mono"],
            background=self.theme.get("panel_alt", "#f0f0f0"),
            lmargin1=6,
            lmargin2=6,
            spacing3=(6 if compact else 10),
        )

        lines = [ln.rstrip() for ln in content.splitlines()]
        # If the user prefers sentence-mode, split into sentences instead of sections.
        if mode is not None and mode.lower().startswith("senten"):
            import re

            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', content) if s.strip()]
            for sent in sentences:
                widget.insert(tk.END, sent + "\n", "para")
            return
        # Find first non-empty line and treat it as a heading if it's short
        idx = 0
        while idx < len(lines) and not lines[idx].strip():
            idx += 1

        if idx < len(lines):
            first = lines[idx].strip()
            if len(first) <= 120 and (len(content) > len(first) + 40):
                widget.insert(tk.END, first + "\n\n", "heading")
                idx += 1

        para_lines: List[str] = []
        for i in range(idx, len(lines)):
            line = lines[i]
            if not line.strip():
                if para_lines:
                    paragraph = "\n".join(para_lines).strip()
                    # bullets inside paragraph
                    for pl in paragraph.splitlines():
                        pls = pl.strip()
                        if pls.startswith("-") or pls.startswith("*"):
                            widget.insert(tk.END, "• " + pls.lstrip("-* ") + "\n", "bullet")
                        elif pls.startswith("    ") or pls.startswith("\t"):
                            widget.insert(tk.END, pls + "\n", "code")
                        else:
                            widget.insert(tk.END, pls + "\n", "para")
                    widget.insert(tk.END, "\n")
                    para_lines = []
                continue

            para_lines.append(line)

        if para_lines:
            paragraph = "\n".join(para_lines).strip()
            for pl in paragraph.splitlines():
                pls = pl.strip()
                if pls.startswith("-") or pls.startswith("*"):
                    widget.insert(tk.END, "• " + pls.lstrip("-* ") + "\n", "bullet")
                elif pls.startswith("    ") or pls.startswith("\t"):
                    widget.insert(tk.END, pls + "\n", "code")
                else:
                    widget.insert(tk.END, pls + "\n", "para")

    def _open_ai_fullscreen(self) -> None:
        content = self.ai_result_text.get("1.0", "end-1c").strip()
        if not content:
            self._set_status("No AI content to show.")
            return

        win = tk.Toplevel(self)
        win.title("AI Result")
        # try fullscreen, fall back to maximized
        try:
            win.attributes("-fullscreen", True)
        except Exception:
            try:
                win.state("zoomed")
            except Exception:
                # best-effort sizing
                w = self.winfo_screenwidth()
                h = self.winfo_screenheight()
                win.geometry(f"{w}x{h}+0+0")

        frame = ttk.Frame(win)
        frame.grid(row=0, column=0, sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        text = tk.Text(frame, wrap="word")
        text.grid(row=0, column=0, sticky="nsew", padx=12, pady=8)
        # format using the same routine so fullscreen looks good
        self._ensure_ai_fonts()
        try:
            text.configure(font=self._ai_fonts["body"])
        except Exception:
            pass
        mode = getattr(self, "ai_format_var", None)
        mode_val = mode.get() if mode is not None else "Sections"
        # enable, insert formatted text, then disable
        text.config(state="normal")
        self._format_and_insert_text(text, content, compact=False, mode=mode_val)
        text.config(state="disabled")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=1, column=0, sticky="ew", pady=8)
        ttk.Button(btn_row, text="Close", command=win.destroy).grid(row=0, column=0, sticky="e")

        def _on_escape(event: object) -> None:
            try:
                win.destroy()
            except Exception:
                pass

        win.bind("<Escape>", _on_escape)

    def _sanitize_user_message(self, message: str) -> str:
        """Converts technical exceptions into clean, user-facing status text."""
        clean_message = (message or "").strip()
        if not clean_message:
            return "An error occurred. Please try again."

        lowered = clean_message.lower()
        if any(token in lowered for token in ("invalid element state", "stacktrace", "session info", "webdriver")):
            return (
                "Moodle sign-in could not be completed automatically. "
                "Please try again and complete login in the opened browser window."
            )

        if "browser sso login failed" in lowered:
            return "Moodle sign-in failed. Please verify credentials and try again."

        if "could not start browser automation for sso login" in lowered:
            return "Could not start browser sign-in. Make sure Edge or Chrome is installed, then try again."

        sanitized_lines: List[str] = []
        for raw_line in clean_message.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line_lower = line.lower()
            if "stacktrace" in line_lower or "symbols not available" in line_lower:
                continue
            if line_lower.startswith("0x"):
                continue
            if line_lower.startswith("traceback"):
                continue
            sanitized_lines.append(line)

        if not sanitized_lines:
            return "An error occurred. Please try again."

        sanitized = " ".join(sanitized_lines)
        if len(sanitized) > 320:
            return f"{sanitized[:317].rstrip()}..."
        return sanitized

    def _restore_backup(self) -> None:
        """Allow the user to choose a timestamped backup file to restore from."""
        backup_dir = DATA_FILE.parent
        initialdir = str(backup_dir) if backup_dir.exists() else str(Path.home())
        path = filedialog.askopenfilename(
            title="Restore backup",
            initialdir=initialdir,
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not path:
            self._set_status("Restore cancelled.")
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            self._show_error(str(exc), "Restore Error")
            self._set_status("Restore failed.")
            return

        # Confirm with user before overwriting
        confirm = tk.messagebox.askyesno("Restore Backup", f"Restore data from {os.path.basename(path)}? This will overwrite current data.")
        if not confirm:
            self._set_status("Restore cancelled.")
            return

        loaded_map = payload.get("items_by_day", {})
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
        self.next_item_id = max(max_seen_id + 1, payload.get("next_item_id", 1))
        self._save_items()
        self._refresh_calendar()
        self._refresh_upcoming_due_notice()
        self._set_status(f"Restored backup from {os.path.basename(path)}")

    def _store_moodle_events(self, events: List[MoodleEvent]) -> tuple[int, int, int]:
        """Adds parsed Moodle events and upgrades duplicate source URLs when possible."""
        removed_count = self._dedupe_existing_import_items()
        existing_signatures = set()
        existing_legacy_signatures = set()
        existing_source_signatures = set()
        for day_key, day_items in self.items_by_day.items():
            for item in day_items:
                signature = (
                    day_key,
                    item.title.strip().lower(),
                    item.time_label.strip().lower(),
                )
                existing_signatures.add(signature)
                existing_legacy_signatures.add(
                    (
                        day_key,
                        self._strip_class_title_prefix(item.title).lower(),
                        item.time_label.strip().lower(),
                    )
                )
                source_url = self._extract_source_url(item.details)
                source_signature = self._source_signature(day_key, source_url)
                if source_signature is not None:
                    existing_source_signatures.add(source_signature)

        added_count = 0
        skipped_count = 0
        updated_count = 0
        for event in events:
            date_key = event.event_date.isoformat()
            title = event.title.strip() or f"{event.category} item"
            if event.category.lower() not in title.lower():
                title = f"{event.category}: {title}"

            normalized_signature = (
                date_key,
                title.strip().lower(),
                event.time_label.strip().lower(),
            )
            legacy_signature = (
                date_key,
                self._strip_class_title_prefix(title).lower(),
                event.time_label.strip().lower(),
            )
            source_signature = self._source_signature(date_key, event.source_url)
            if (
                normalized_signature in existing_signatures
                or legacy_signature in existing_legacy_signatures
                or (source_signature is not None and source_signature in existing_source_signatures)
            ):
                existing_item = self._find_item_by_signature(
                    date_key,
                    title=title,
                    time_label=event.time_label,
                )
                if existing_item is None:
                    existing_item = self._find_item_by_legacy_signature(
                        date_key,
                        title=title,
                        time_label=event.time_label,
                    )
                if existing_item is None and source_signature is not None:
                    existing_item = self._find_item_by_source_signature(
                        date_key,
                        source_url=event.source_url,
                    )
                if existing_item is not None:
                    if existing_item.title != title and self._is_better_event_title(existing_item.title, title):
                        existing_item.title = title
                        updated_count += 1
                if existing_item is not None and self._try_upgrade_item_source_url(existing_item, event.source_url):
                    updated_count += 1
                skipped_count += 1
                continue

            details_parts = [event.details.strip()]
            if event.source_url and event.source_url not in event.details:
                details_parts.append(f"Source: {event.source_url}")
            details_text = "\n".join(part for part in details_parts if part).strip()

            self.items_by_day.setdefault(date_key, []).append(
                CalendarItem(
                    item_id=self.next_item_id,
                    title=title,
                    details=details_text,
                    time_label=event.time_label.strip(),
                )
            )
            self.next_item_id += 1
            existing_signatures.add(normalized_signature)
            existing_legacy_signatures.add(legacy_signature)
            if source_signature is not None:
                existing_source_signatures.add(source_signature)
            added_count += 1

        if added_count or updated_count or removed_count:
            self._save_items()
        return added_count, skipped_count, updated_count

    def _find_item_by_signature(self, date_key: str, title: str, time_label: str) -> Optional[CalendarItem]:
        """Returns an existing item matching the import signature tuple."""
        target_title = title.strip().lower()
        target_time = time_label.strip().lower()
        for item in self.items_by_day.get(date_key, []):
            if item.title.strip().lower() == target_title and item.time_label.strip().lower() == target_time:
                return item
        return None

    def _find_item_by_legacy_signature(self, date_key: str, title: str, time_label: str) -> Optional[CalendarItem]:
        """Finds existing items by normalized title without class-prefix decorations."""
        target_title = self._strip_class_title_prefix(title).lower()
        target_time = time_label.strip().lower()
        for item in self.items_by_day.get(date_key, []):
            item_title = self._strip_class_title_prefix(item.title).lower()
            if item_title == target_title and item.time_label.strip().lower() == target_time:
                return item
        return None

    def _find_item_by_source_signature(self, date_key: str, source_url: str) -> Optional[CalendarItem]:
        """Finds an existing item by normalized same-day source URL."""
        target_signature = self._source_signature(date_key, source_url)
        if target_signature is None:
            return None
        for item in self.items_by_day.get(date_key, []):
            item_source = self._extract_source_url(item.details)
            item_signature = self._source_signature(date_key, item_source)
            if item_signature == target_signature:
                return item
        return None

    def _try_upgrade_item_source_url(self, item: CalendarItem, new_source_url: str) -> bool:
        """Upgrades an item's Source URL when import provides a better assignment link."""
        new_source = new_source_url.strip()
        if not new_source:
            return False

        old_source = self._extract_source_url(item.details)
        if not self._is_better_source_url(old_source, new_source):
            return False

        item.details = self._replace_source_url(item.details, new_source)
        return True

    def _extract_source_url(self, details: str) -> str:
        """Extracts the current Source URL from details text, if present."""
        for line in reversed(details.splitlines()):
            trimmed = line.strip()
            if trimmed.lower().startswith("source:"):
                return trimmed.split(":", 1)[1].strip()
        return ""

    def _source_signature(self, date_key: str, source_url: str) -> Optional[Tuple[str, str]]:
        """Builds a same-day source key used to collapse duplicate imported items."""
        normalized_source = self._normalize_source_url_for_match(source_url)
        if not normalized_source:
            return None
        return date_key, normalized_source

    def _normalize_source_url_for_match(self, source_url: str) -> str:
        """Canonicalizes Moodle source URLs so equivalent links compare equal."""
        candidate = source_url.strip()
        if not candidate:
            return ""
        if not candidate.lower().startswith(("http://", "https://")):
            candidate = f"https://{candidate}"

        parsed = urlparse(candidate)
        if not parsed.netloc:
            return ""

        path = parsed.path or "/"
        lowered_path = path.lower()
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query_map = {key.lower(): value for key, value in query_pairs}

        if lowered_path == "/mod/assign/view.php":
            assign_id = (query_map.get("id") or query_map.get("cmid") or "").strip()
            canonical_pairs = [("id", assign_id)] if assign_id else []
            normalized_query = urlencode(canonical_pairs, doseq=True)
            return urlunparse(
                (
                    parsed.scheme.lower(),
                    parsed.netloc.lower(),
                    path,
                    "",
                    normalized_query,
                    "",
                )
            )

        if lowered_path == "/mod/quiz/view.php":
            quiz_id = (query_map.get("id") or query_map.get("cmid") or "").strip()
            canonical_pairs = [("id", quiz_id)] if quiz_id else []
            normalized_query = urlencode(canonical_pairs, doseq=True)
            return urlunparse(
                (
                    parsed.scheme.lower(),
                    parsed.netloc.lower(),
                    path,
                    "",
                    normalized_query,
                    "",
                )
            )

        normalized_query = urlencode(sorted(query_pairs), doseq=True)
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                "",
                normalized_query,
                "",
            )
        )

    def _replace_source_url(self, details: str, source_url: str) -> str:
        """Replaces existing Source line or appends one when missing."""
        lines = details.splitlines()
        replaced = False
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].strip().lower().startswith("source:"):
                lines[idx] = f"Source: {source_url}"
                replaced = True
                break

        if not replaced:
            stripped = details.strip()
            if stripped:
                return f"{stripped}\nSource: {source_url}"
            return f"Source: {source_url}"
        return "\n".join(lines).strip()

    def _strip_class_title_prefix(self, title: str) -> str:
        """Removes `[Class Name]` prefix so imports can match older title formats."""
        return re.sub(r"^\[[^\]]+\]\s*", "", title.strip())

    def _is_better_event_title(self, current_title: str, candidate_title: str) -> bool:
        """Returns True when candidate title has richer context than current title."""
        current_has_class = current_title.strip().startswith("[") and "]" in current_title
        candidate_has_class = candidate_title.strip().startswith("[") and "]" in candidate_title
        if candidate_has_class and not current_has_class:
            return True
        if len(candidate_title.strip()) > len(current_title.strip()) + 3:
            return True
        return False

    def _dedupe_existing_import_items(self) -> int:
        """Collapses existing same-day duplicates by title/time and by normalized source URL."""
        removed_count = 0
        for day_key, items in list(self.items_by_day.items()):
            best_by_key: Dict[tuple[str, str], CalendarItem] = {}
            for item in items:
                key = (
                    self._strip_class_title_prefix(item.title).lower(),
                    item.time_label.strip().lower(),
                )
                current = best_by_key.get(key)
                if current is None:
                    best_by_key[key] = item
                    continue
                best_by_key[key] = self._choose_preferred_import_item(current, item)

            title_deduped_items = list(best_by_key.values())
            best_by_source_key: Dict[str, CalendarItem] = {}
            no_source_items: List[CalendarItem] = []
            for item in title_deduped_items:
                source_key = self._normalize_source_url_for_match(self._extract_source_url(item.details))
                if not source_key:
                    no_source_items.append(item)
                    continue
                current = best_by_source_key.get(source_key)
                if current is None:
                    best_by_source_key[source_key] = item
                    continue
                best_by_source_key[source_key] = self._choose_preferred_import_item(current, item)

            deduped_items = list(best_by_source_key.values()) + no_source_items
            deduped_items.sort(key=lambda item: item.item_id)
            removed_count += max(0, len(items) - len(deduped_items))
            self.items_by_day[day_key] = deduped_items
        return removed_count

    def _choose_preferred_import_item(self, left: CalendarItem, right: CalendarItem) -> CalendarItem:
        """Keeps the stronger item when import dedupes existing same-signature entries."""
        left_source = self._extract_source_url(left.details)
        right_source = self._extract_source_url(right.details)
        if self._is_better_source_url(left_source, right_source):
            return right
        if self._is_better_source_url(right_source, left_source):
            return left

        if self._is_better_event_title(left.title, right.title):
            return right
        if self._is_better_event_title(right.title, left.title):
            return left
        if len(right.details) > len(left.details):
            return right
        return left

    def _is_better_source_url(self, current_url: str, candidate_url: str) -> bool:
        """Returns True when candidate URL is a higher-quality Moodle activity destination."""
        current = current_url.strip().lower()
        candidate = candidate_url.strip().lower()
        if not candidate:
            return False
        if candidate == current:
            return False
        if not current:
            return True

        current_is_course = "/course/view.php" in current
        candidate_is_course = "/course/view.php" in candidate
        current_is_assign = "/mod/assign/view.php" in current
        candidate_is_assign = "/mod/assign/view.php" in candidate
        current_is_quiz = "/mod/quiz/" in current
        candidate_is_quiz = "/mod/quiz/" in candidate
        if candidate_is_assign and not current_is_assign:
            return True
        if candidate_is_quiz and not current_is_quiz:
            return True
        if current_is_course and not candidate_is_course:
            return True
        if candidate_is_assign and current_is_assign:
            current_has_action = "action=editsubmission" in current or "action=submit" in current
            candidate_has_action = "action=editsubmission" in candidate or "action=submit" in candidate
            if current_has_action and not candidate_has_action:
                # Prefer stable assignment id pages over submission-action variants.
                return True
            if candidate_has_action and not current_has_action:
                return False
        if candidate_is_quiz and current_is_quiz:
            current_is_view = "/mod/quiz/view.php" in current
            candidate_is_view = "/mod/quiz/view.php" in candidate
            if candidate_is_view and not current_is_view:
                return True
            current_has_id = "id=" in current
            candidate_has_id = "id=" in candidate
            if candidate_has_id and not current_has_id:
                return True
        return False

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

    def _refresh_upcoming_due_notice(self, update_status: bool = False, notify_popup: bool = False) -> None:
        """Builds due-date notice text and optionally evaluates popup reminder timing."""
        notice_text, first_due_date, window_item_count = self._build_upcoming_due_notice()

        if notify_popup:
            self._maybe_show_due_reminder_popup(notice_text, first_due_date)

        if not update_status:
            return

        if first_due_date is None:
            self._set_status("No upcoming due dates from today onward.")
            return

        due_label = first_due_date.strftime("%A, %b %d, %Y")
        self._set_status(
            f"Next due date: {due_label}. {window_item_count} item(s) due within 3 days of that date."
        )

    def _maybe_show_due_reminder_popup(self, notice_text: str, first_due_date: Optional[date]) -> None:
        """Shows reminders every other day before the next due date while app is open."""
        if first_due_date is None:
            return

        today = date.today()
        days_until_due = (first_due_date - today).days
        if days_until_due <= 0:
            # "Leading up" reminders are only before the due day.
            return
        if days_until_due % 2 != 0:
            return

        if self._last_due_notice_day == today and self._last_due_notice_target == first_due_date:
            return

        self._show_due_notice_popup(notice_text)
        self._last_due_notice_day = today
        self._last_due_notice_target = first_due_date

    def _schedule_due_reminder_check(self, initial_delay_ms: int = 3_600_000) -> None:
        """Schedules the next periodic due-reminder check while app stays open."""
        if self._due_reminder_after_id is not None:
            try:
                self.after_cancel(self._due_reminder_after_id)
            except ValueError:
                pass
        self._due_reminder_after_id = self.after(initial_delay_ms, self._run_due_reminder_check)

    def _run_due_reminder_check(self) -> None:
        """Performs one periodic reminder cycle and schedules the next cycle."""
        self._due_reminder_after_id = None
        self._refresh_upcoming_due_notice(notify_popup=True)
        self._schedule_due_reminder_check()

    def _build_upcoming_due_notice(self) -> tuple[str, Optional[date], int]:
        """Builds upcoming due-date text using the nearest date and a three-day window."""
        upcoming_by_day: Dict[date, List[CalendarItem]] = {}
        today = date.today()

        for day_key, items in self.items_by_day.items():
            if not items:
                continue
            try:
                day_value = date.fromisoformat(day_key)
            except ValueError:
                continue
            if day_value < today:
                continue
            upcoming_by_day[day_value] = list(items)

        if not upcoming_by_day:
            return "No upcoming due dates from today onward.", None, 0

        first_due_date = min(upcoming_by_day)
        window_end = first_due_date + timedelta(days=3)
        window_dates = sorted(day_value for day_value in upcoming_by_day if first_due_date <= day_value <= window_end)
        window_item_count = sum(len(upcoming_by_day[day_value]) for day_value in window_dates)

        lines = [
            f"Next due date: {first_due_date.strftime('%A, %b %d, %Y')}",
            f"Also showing all due dates through {window_end.strftime('%A, %b %d, %Y')}:",
        ]
        for day_value in window_dates:
            day_items = sorted(
                upcoming_by_day[day_value],
                key=lambda item: (
                    item.time_label.strip().lower(),
                    item.title.strip().lower(),
                ),
            )
            day_label = day_value.strftime("%a, %b %d")
            lines.append(f"{day_label} ({len(day_items)} item{'s' if len(day_items) != 1 else ''})")
            for item in day_items:
                time_prefix = f"[{item.time_label}] " if item.time_label.strip() else ""
                lines.append(f"- {time_prefix}{item.title}")

        return "\n".join(lines), first_due_date, window_item_count

    def _show_due_notice_popup(self, message: str) -> None:
        """Shows a separate upcoming-due popup window and plays an auditory alert."""
        if self._due_notice_window is None or not self._due_notice_window.winfo_exists():
            self._due_notice_window = tk.Toplevel(self)
            self._due_notice_window.title("Upcoming Due Dates")
            self._due_notice_window.geometry("580x320")
            self._due_notice_window.minsize(460, 220)
            self._due_notice_window.resizable(True, True)
            self._due_notice_window.transient(self)
            self._due_notice_window.protocol("WM_DELETE_WINDOW", self._close_due_notice_window)
            self._due_notice_window.configure(bg=self.theme["bg"])
            self._due_notice_window.columnconfigure(0, weight=1)
            self._due_notice_window.rowconfigure(1, weight=1)

            ttk.Label(
                self._due_notice_window,
                text="Upcoming due-date reminder",
                style="Muted.TLabel",
            ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

            self._due_notice_text = tk.Text(
                self._due_notice_window,
                wrap="word",
                bg=self.theme["input_bg"],
                fg=self.theme["input_fg"],
                insertbackground=self.theme["input_fg"],
            )
            self._due_notice_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
            self._due_notice_text.config(state="disabled")

            button_row = ttk.Frame(self._due_notice_window)
            button_row.grid(row=2, column=0, sticky="e", padx=12, pady=(4, 10))
            ttk.Button(button_row, text="Close", command=self._close_due_notice_window).grid(row=0, column=0)
        else:
            self._due_notice_window.title("Upcoming Due Dates")

        if self._due_notice_text is not None:
            self._due_notice_text.config(state="normal")
            self._due_notice_text.delete("1.0", tk.END)
            self._due_notice_text.insert("1.0", message)
            self._due_notice_text.config(state="disabled")

        self._due_notice_window.deiconify()
        self._due_notice_window.lift()
        self._due_notice_window.focus_set()
        self._play_due_notification_sound()

    def _play_due_notification_sound(self) -> None:
        """Plays a short built-in alert tone sequence for due-date notifications."""
        for offset_ms in (0, 140):
            self.after(offset_ms, self.bell)

    def _close_due_notice_window(self) -> None:
        """Closes the due-date notification popup."""
        if self._due_notice_window is not None and self._due_notice_window.winfo_exists():
            self._due_notice_window.destroy()
        self._due_notice_window = None
        self._due_notice_text = None

    def _on_app_close(self) -> None:
        """Cancels scheduled reminders and closes auxiliary windows before exiting."""
        if self._due_reminder_after_id is not None:
            try:
                self.after_cancel(self._due_reminder_after_id)
            except ValueError:
                pass
            self._due_reminder_after_id = None

        self._close_due_notice_window()
        self._close_error_window()
        self.destroy()

    def _show_error(self, message: str, title: str = "Error") -> None:
        """Shows a non-modal, resizable error window that the user can close anytime."""
        if self._error_window is None or not self._error_window.winfo_exists():
            self._error_window = tk.Toplevel(self)
            self._error_window.title(title)
            self._error_window.geometry("560x260")
            self._error_window.minsize(420, 180)
            self._error_window.resizable(True, True)
            self._error_window.transient(self)
            self._error_window.protocol("WM_DELETE_WINDOW", self._close_error_window)
            self._error_window.configure(bg=self.theme["bg"])
            self._error_window.columnconfigure(0, weight=1)
            self._error_window.rowconfigure(1, weight=1)

            ttk.Label(
                self._error_window,
                text="An error occurred. You can close or resize this window.",
                style="Muted.TLabel",
            ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

            self._error_text = tk.Text(
                self._error_window,
                wrap="word",
                bg=self.theme["input_bg"],
                fg=self.theme["input_fg"],
                insertbackground=self.theme["input_fg"],
            )
            self._error_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
            self._error_text.config(state="disabled")

            button_row = ttk.Frame(self._error_window)
            button_row.grid(row=2, column=0, sticky="e", padx=12, pady=(4, 10))
            ttk.Button(button_row, text="Close", command=self._close_error_window).grid(row=0, column=0)
        else:
            self._error_window.title(title)

        if self._error_text is not None:
            self._error_text.config(state="normal")
            self._error_text.delete("1.0", tk.END)
            self._error_text.insert("1.0", message)
            self._error_text.config(state="disabled")

        self._error_window.deiconify()
        self._error_window.lift()

    def _close_error_window(self) -> None:
        """Destroys the error window so users can continue with the main interface."""
        if self._error_window is not None and self._error_window.winfo_exists():
            self._error_window.destroy()
        self._error_window = None
        self._error_text = None

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
            message = "Could not parse existing data file; starting with empty data."
            self._set_status(message)
            self._show_error(message, "Data File Error")
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
        """Persists all calendar items to the active JSON data file."""
        serializable_map = {
            key: [asdict(item) for item in items]
            for key, items in self.items_by_day.items()
        }
        payload = {
            "next_item_id": self.next_item_id,
            "items_by_day": serializable_map,
        }
        try:
            # keep last payload in-memory for quick undo and safety
            self._last_saved_payload = json.dumps(payload, indent=2)
            DATA_FILE.write_text(self._last_saved_payload, encoding="utf-8")
        except OSError:
            message = "Could not save data to disk."
            self._set_status(message)
            self._show_error(message, "Save Error")

    def _backup_before_clear(self) -> Optional[Path]:
        """Write a timestamped backup of the current data file and keep payload in memory."""
        try:
            # ensure latest saved payload is current
            if self._last_saved_payload is None:
                # attempt to build payload
                serializable_map = {
                    key: [asdict(item) for item in items]
                    for key, items in self.items_by_day.items()
                }
                backup_payload = {
                    "next_item_id": self.next_item_id,
                    "items_by_day": serializable_map,
                }
                self._last_saved_payload = json.dumps(backup_payload, indent=2)

            backup_dir = DATA_FILE.parent
            backup_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            backup_path = backup_dir / f"calendar_backup_{ts}.json"
            backup_path.write_text(self._last_saved_payload or "{}", encoding="utf-8")
            return backup_path
        except Exception:
            return None

    def _undo_clear(self) -> None:
        """Restore last saved payload (undo clear-all) if available."""
        if not self._last_saved_payload:
            self._set_status("Nothing to undo.")
            return
        try:
            payload = json.loads(self._last_saved_payload)
            loaded_map = payload.get("items_by_day", {})
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
            self.next_item_id = max(max_seen_id + 1, payload.get("next_item_id", 1))
            self._save_items()
            self._refresh_calendar()
            self._refresh_upcoming_due_notice()
            self._set_status("Undo: restored previous calendar data.")
        except Exception:
            self._set_status("Undo failed.")

    # import/export JSON feature removed

    def _on_enter_pressed(self, event: object) -> None:
        """Enter: try to add item when editor fields have focus."""
        focused = self.focus_get()
        if focused in (self.title_entry, self.time_entry, self.details_text):
            self._add_item()

    def _on_delete_pressed(self, event: object) -> None:
        """Delete: remove selected item when item list has focus."""
        if self.focus_get() == self.item_list:
            self._remove_item()

    def _select_next_item(self) -> None:
        """Select the next visible item in the item_list (wraps)."""
        size = self.item_list.size()
        if size == 0:
            return
        sel = self.item_list.curselection()
        idx = int(sel[0]) if sel else -1
        next_idx = (idx + 1) % size
        try:
            self.item_list.selection_clear(0, tk.END)
            self.item_list.selection_set(next_idx)
            self.item_list.see(next_idx)
            self._on_item_selected(None)
        except Exception:
            pass

    def _select_prev_item(self) -> None:
        """Select the previous visible item in the item_list (wraps)."""
        size = self.item_list.size()
        if size == 0:
            return
        sel = self.item_list.curselection()
        idx = int(sel[0]) if sel else 0
        prev_idx = (idx - 1) % size
        try:
            self.item_list.selection_clear(0, tk.END)
            self.item_list.selection_set(prev_idx)
            self.item_list.see(prev_idx)
            self._on_item_selected(None)
        except Exception:
            pass


def main() -> None:
    """Application entry point."""
    app = CalendarApp()
    app.mainloop()


if __name__ == "__main__":
    main()
