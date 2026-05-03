"""Single-window desktop calendar application.

This module provides a Tkinter application that supports adding, editing, and
removing multiple calendar items per day without opening extra windows.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
import calendar
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import webbrowser
from typing import Dict, List, Optional, Tuple

from moodle_crawler import MoodleCrawler, MoodleEvent


APP_NAME = "Desktop Calendar"
DATA_FILENAME = "calendar_items.json"
URL_PATTERN = re.compile(r"(?i)\b((?:https?://|www\.)[^\s<>\"']+)")


def _source_app_dir() -> Path:
    """Returns the source directory for the application code."""
    return Path(__file__).resolve().parent


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

DEFAULT_APP_SETTINGS = {
    "font_family_mode": "standard",
    "font_size": "medium",
    "color_blind_mode": False,
}

LIGHT_THEME = {
    "bg": "#f4f6fb",
    "panel": "#ffffff",
    "panel_alt": "#eef2f7",
    "sidebar": "#23364a",
    "sidebar_text": "#f3f4f6",
    "sidebar_muted": "#b8c2cf",
    "sidebar_active": "#33526f",
    "text": "#1f1f1f",
    "muted": "#5f6b7a",
    "accent": "#2563eb",
    "accent_text": "#ffffff",
    "danger": "#dc2626",
    "warning": "#d97706",
    "success": "#16a34a",
    "day_danger_bg": "#fee2e2",
    "day_warning_bg": "#fef3c7",
    "day_success_bg": "#dcfce7",
    "day_text": "#111827",
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
    "sidebar": "#121a24",
    "sidebar_text": "#f8fafc",
    "sidebar_muted": "#9aa4b2",
    "sidebar_active": "#1c2a3a",
    "text": "#ffffff",      
    "muted": "#aaaaaa",      
    "accent": "#0a84ff",      
    "accent_text": "#ffffff",
    "danger": "#ef4444",
    "warning": "#f59e0b",
    "success": "#22c55e",
    "day_danger_bg": "#2b1114",
    "day_warning_bg": "#2c220c",
    "day_success_bg": "#102317",
    "day_text": "#ffffff",
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
    due_date: str = ""
    due_time: str = ""
    details: str = ""
    time_label: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CalendarItem":
        """Builds a CalendarItem from persisted JSON data."""
        return cls(
            item_id=int(data["item_id"]),
            title=str(data["title"]),
            due_date=str(data.get("due_date", "")),
            due_time=str(data.get("due_time", data.get("time_label", ""))),
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
        self.app_settings: Dict[str, object] = dict(DEFAULT_APP_SETTINGS)
        self.active_view = "calendar"
        self.sidebar_buttons: Dict[str, tk.Button] = {}
        self.font_family_var = tk.StringVar(value=str(DEFAULT_APP_SETTINGS["font_family_mode"]))
        self.font_size_var = tk.StringVar(value="Medium")
        self.color_blind_var = tk.BooleanVar(value=bool(DEFAULT_APP_SETTINGS["color_blind_mode"]))
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
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)

        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self._build_layout()
        self._apply_theme()
        self._load_items()
        self._apply_accessibility_preferences()
        removed_count = self._dedupe_existing_import_items()
        if removed_count:
            self._save_items()
        self._refresh_calendar()
        self._refresh_upcoming_due_notice(update_status=True)
        self._schedule_due_reminder_check(initial_delay_ms=300)

    def _build_layout(self) -> None:
        """Creates and arranges all widgets in the single main window."""
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=5)
        self.columnconfigure(2, weight=4)
        self.rowconfigure(0, weight=1)

        sidebar = tk.Frame(self, bg=self.theme["sidebar"], width=210)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        self.sidebar_title_label = tk.Label(
            sidebar,
            text="📚 Student Dashboard",
            font=("Segoe UI", 13, "bold"),
            bg=self.theme["sidebar"],
            fg=self.theme["sidebar_text"],
            anchor="w",
        )
        self.sidebar_title_label.grid(row=0, column=0, sticky="ew", padx=14, pady=(16, 12))

        for row_idx, (view_name, label) in enumerate(
            [
                ("calendar", "📅 Calendar"),
                ("assignments", "🗂️ Assignments"),
                ("due", "⏰ Due Soon"),
                ("settings", "⚙️ Settings"),
            ],
            start=1,
        ):
            nav_btn = tk.Button(
                sidebar,
                text=" ".join(str(label).split()),
                font=("Segoe UI", 11),
                bg=self.theme["sidebar"],
                fg=self.theme["sidebar_text"],
                activebackground=self.theme["sidebar_active"],
                activeforeground=self.theme["sidebar_text"],
                relief="flat",
                bd=0,
                anchor="w",
                padx=16,
                pady=12,
                command=lambda name=view_name: self._set_active_view(name),
            )
            nav_btn.grid(row=row_idx, column=0, sticky="ew", padx=10, pady=4)
            nav_btn.bind("<Enter>", lambda _event, button=nav_btn: self._on_sidebar_hover(button, True))
            nav_btn.bind("<Leave>", lambda _event, button=nav_btn: self._on_sidebar_hover(button, False))
            self.sidebar_buttons[view_name] = nav_btn

        calendar_panel = ttk.Frame(self, padding=14, style="Panel.TFrame")
        calendar_panel.grid(row=0, column=1, sticky="nsew")
        calendar_panel.columnconfigure(0, weight=1)
        calendar_panel.rowconfigure(3, weight=1)

        self.view_title_label = ttk.Label(
            calendar_panel,
            text="Calendar",
            font=("Segoe UI", 15, "bold"),
            style="Panel.TLabel",
        )
        self.view_title_label.grid(row=0, column=0, sticky="w", pady=(0, 8))

        nav_frame = ttk.Frame(calendar_panel, style="Panel.TFrame")
        self.nav_frame = nav_frame
        nav_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        nav_frame.columnconfigure(0, weight=0)
        nav_frame.columnconfigure(1, weight=1)
        nav_frame.columnconfigure(2, weight=0)
        nav_frame.columnconfigure(3, weight=0)

        self.prev_btn = ttk.Button(nav_frame, text="<", width=4, command=self._go_previous_month)
        self.prev_btn.grid(row=0, column=0, sticky="w")

        self.month_label = ttk.Label(nav_frame, text="", font=("Segoe UI", 15, "bold"), style="Panel.TLabel")
        self.month_label.grid(row=0, column=1)

        self.next_btn = ttk.Button(nav_frame, text=">", width=4, command=self._go_next_month)
        self.next_btn.grid(row=0, column=2, sticky="e")

        self.nav_spacer = ttk.Label(nav_frame, text="", style="Panel.TLabel")
        self.nav_spacer.grid(row=0, column=3, sticky="e", padx=(8, 0))

        weekdays = ttk.Frame(calendar_panel, style="Panel.TFrame")
        weekdays.grid(row=2, column=0, sticky="ew")
        weekdays.columnconfigure(tuple(range(7)), weight=1)
        for idx, weekday in enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]):
            ttk.Label(weekdays, text=weekday, anchor="center", style="Muted.TLabel").grid(
                row=0, column=idx, sticky="ew", padx=2, pady=(0, 4)
            )

        self.calendar_grid = ttk.Frame(calendar_panel, style="Panel.TFrame")
        self.calendar_grid.grid(row=3, column=0, sticky="nsew")
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

        self.assignments_view = ttk.Frame(calendar_panel, style="Panel.TFrame")
        self.assignments_view.grid(row=2, column=0, sticky="nsew")
        self.assignments_view.columnconfigure(0, weight=1)
        self.assignments_view.rowconfigure(1, weight=1)
        ttk.Label(self.assignments_view, text="All Assignments", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.assignments_list = tk.Listbox(self.assignments_view, exportselection=False, height=14)
        self.assignments_list.grid(row=1, column=0, sticky="nsew")
        assignments_scroll = ttk.Scrollbar(self.assignments_view, orient="vertical", command=self.assignments_list.yview)
        assignments_scroll.grid(row=1, column=1, sticky="ns")
        self.assignments_list.config(yscrollcommand=assignments_scroll.set)

        self.due_view = ttk.Frame(calendar_panel, style="Panel.TFrame")
        self.due_view.grid(row=2, column=0, sticky="nsew")
        self.due_view.columnconfigure(0, weight=1)
        self.due_view.rowconfigure(1, weight=1)
        ttk.Label(self.due_view, text="Urgent Deadlines", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.due_list = tk.Listbox(self.due_view, exportselection=False, height=14)
        self.due_list.grid(row=1, column=0, sticky="nsew")
        due_scroll = ttk.Scrollbar(self.due_view, orient="vertical", command=self.due_list.yview)
        due_scroll.grid(row=1, column=1, sticky="ns")
        self.due_list.config(yscrollcommand=due_scroll.set)

        self.settings_view = ttk.Frame(calendar_panel, style="Panel.TFrame")
        self.settings_view.grid(row=2, column=0, sticky="nsew")
        self.settings_view.columnconfigure(0, weight=1)
        ttk.Label(self.settings_view, text="Settings", style="Panel.TLabel", font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        # Theme toggle retained below in settings controls to avoid duplicate controls
        ttk.Label(
            self.settings_view,
            text="Use the sidebar to switch between the calendar, assignment list, and urgent deadlines.",
            wraplength=520,
            style="Muted.TLabel",
        ).grid(row=2, column=0, sticky="w")

        settings_controls = ttk.Frame(self.settings_view, style="Panel.TFrame")
        settings_controls.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        settings_controls.columnconfigure(1, weight=1)

        ttk.Label(settings_controls, text="Dyslexic-friendly font", style="Panel.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.dyslexic_font_toggle = ttk.Checkbutton(
            settings_controls,
            text="Dyslexic-friendly font",
            variable=self.font_family_var,
            onvalue="dyslexic",
            offvalue="standard",
            command=self._on_accessibility_settings_changed,
        )
        self.dyslexic_font_toggle.grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(settings_controls, text="Font size", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        self.font_size_combo = ttk.Combobox(
            settings_controls,
            textvariable=self.font_size_var,
            values=["Small", "Medium", "Large"],
            state="readonly",
            width=12,
        )
        self.font_size_combo.grid(row=1, column=1, sticky="w", pady=4)
        self.font_size_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_accessibility_settings_changed())

        self.color_blind_toggle = ttk.Checkbutton(
            settings_controls,
            text="Color-blind friendly mode",
            variable=self.color_blind_var,
            command=self._on_accessibility_settings_changed,
        )
        self.color_blind_toggle.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 4))

        ttk.Button(settings_controls, text="Reset Font/Color Settings", command=self._reset_accessibility_settings).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        ttk.Button(settings_controls, text="Toggle Light / Dark Theme", command=self._toggle_theme).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

        metrics_frame = ttk.Frame(calendar_panel, style="Panel.TFrame")
        self.metrics_frame = metrics_frame
        self._refresh_day_button_fonts()
        metrics_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        for metric_col in range(3):
            metrics_frame.columnconfigure(metric_col, weight=1)

        self.metric_total_label = ttk.Label(metrics_frame, text="0", font=("Segoe UI", 16, "bold"), style="MetricValue.TLabel")
        self.metric_due_today_label = ttk.Label(metrics_frame, text="0", font=("Segoe UI", 16, "bold"), style="MetricDanger.TLabel")
        self.metric_completed_label = ttk.Label(metrics_frame, text="0", font=("Segoe UI", 16, "bold"), style="MetricSuccess.TLabel")

        metric_cards = [
            ("Total Assignments", self.metric_total_label),
            ("Due Today", self.metric_due_today_label),
            ("Completed", self.metric_completed_label),
        ]
        for idx, (title, value_label) in enumerate(metric_cards):
            card = ttk.Frame(metrics_frame, padding=(10, 8), style="Panel.TFrame")
            card.grid(row=0, column=idx, sticky="ew", padx=3)
            ttk.Label(card, text=title, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
            value_label.grid(in_=card, row=1, column=0, sticky="w", pady=(2, 0))

        self.progress_var = tk.DoubleVar(value=0)
        progress_row = ttk.Frame(calendar_panel, style="Panel.TFrame")
        self.progress_row = progress_row
        progress_row.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        progress_row.columnconfigure(1, weight=1)
        ttk.Label(progress_row, text="Progress", style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=(2, 8))
        self.progress_bar = ttk.Progressbar(progress_row, mode="determinate", maximum=100, variable=self.progress_var)
        self.progress_bar.grid(row=0, column=1, sticky="ew")
        self.progress_text_label = ttk.Label(progress_row, text="0%", style="Muted.TLabel")
        self.progress_text_label.grid(row=0, column=2, sticky="e", padx=(8, 0))

        side_panel = ttk.Frame(self, padding=14, style="Panel.TFrame")
        side_panel.grid(row=0, column=2, sticky="nsew")
        side_panel.columnconfigure(0, weight=1)
        side_panel.rowconfigure(2, weight=1)
        side_panel.rowconfigure(4, weight=1)

        self.selected_day_label = ttk.Label(side_panel, text="", font=("Segoe UI", 13, "bold"), style="Panel.TLabel")
        self.selected_day_label.grid(row=0, column=0, sticky="w", pady=(0, 6))

        summary_frame = ttk.Frame(side_panel, padding=8, style="Panel.TFrame")
        summary_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        summary_frame.columnconfigure(0, weight=1)
        ttk.Label(summary_frame, text="Upcoming Deadlines", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        legend_frame = ttk.Frame(summary_frame, style="Panel.TFrame")
        legend_frame.grid(row=1, column=0, sticky="w", pady=(0, 6))
        self.legend_canvas_red = tk.Canvas(legend_frame, width=12, height=12, highlightthickness=0, bg=self.theme["panel"])
        self.legend_canvas_yellow = tk.Canvas(legend_frame, width=12, height=12, highlightthickness=0, bg=self.theme["panel"])
        self.legend_canvas_green = tk.Canvas(legend_frame, width=12, height=12, highlightthickness=0, bg=self.theme["panel"])
        self.legend_label_red = ttk.Label(legend_frame, text="Overdue / <=24h", style="Muted.TLabel")
        self.legend_label_yellow = ttk.Label(legend_frame, text="<=3 days", style="Muted.TLabel")
        self.legend_label_green = ttk.Label(legend_frame, text="Later", style="Muted.TLabel")
        self.legend_canvas_red.grid(row=0, column=0, padx=(0, 4))
        self.legend_label_red.grid(row=0, column=1, padx=(0, 10))
        self.legend_canvas_yellow.grid(row=0, column=2, padx=(0, 4))
        self.legend_label_yellow.grid(row=0, column=3, padx=(0, 10))
        self.legend_canvas_green.grid(row=0, column=4, padx=(0, 4))
        self.legend_label_green.grid(row=0, column=5)
        self.deadline_list = tk.Listbox(summary_frame, height=7, exportselection=False)
        self.deadline_list.grid(row=2, column=0, sticky="nsew")
        summary_scroll = ttk.Scrollbar(summary_frame, orient="vertical", command=self.deadline_list.yview)
        summary_scroll.grid(row=2, column=1, sticky="ns")
        self.deadline_list.config(yscrollcommand=summary_scroll.set)

        items_frame = ttk.Frame(side_panel, padding=8, style="Panel.TFrame")
        ttk.Label(items_frame, text="Items", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        items_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        items_frame.columnconfigure(0, weight=1)
        items_frame.rowconfigure(0, weight=1)

        self.item_list = tk.Listbox(items_frame, height=10, exportselection=False)
        self.item_list.grid(row=0, column=0, sticky="nsew")
        self.item_list.bind("<<ListboxSelect>>", self._on_item_selected)

        list_scroll = ttk.Scrollbar(items_frame, orient="vertical", command=self.item_list.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.item_list.config(yscrollcommand=list_scroll.set)

        editor_frame = ttk.Frame(side_panel, padding=8, style="Panel.TFrame")
        ttk.Label(editor_frame, text="View / Edit Item", style="Panel.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        editor_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 8))
        editor_frame.columnconfigure(1, weight=1)

        ttk.Label(editor_frame, text="Title").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(editor_frame, textvariable=self.title_var)
        self.title_entry.grid(row=0, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(editor_frame, text="Due Date (MM/DD/YYYY)").grid(row=1, column=0, sticky="w", pady=(0, 4))
        self.due_date_var = tk.StringVar()
        self.due_date_entry = ttk.Entry(editor_frame, textvariable=self.due_date_var)
        self.due_date_entry.grid(row=1, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(editor_frame, text="Due Time (HH:MM AM/PM)").grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.time_var = tk.StringVar()
        self.time_entry = ttk.Entry(editor_frame, textvariable=self.time_var)
        self.time_entry.grid(row=2, column=1, sticky="ew", pady=(0, 4))

        ttk.Label(editor_frame, text="Details").grid(row=3, column=0, sticky="nw", pady=(0, 4))
        self.details_text = tk.Text(editor_frame, height=6, wrap="word")
        self.details_text.grid(row=3, column=1, sticky="nsew", pady=(0, 4))
        self.details_text.bind("<KeyRelease>", self._on_details_changed)
        editor_frame.rowconfigure(3, weight=1)

        action_frame = ttk.Frame(editor_frame, style="Panel.TFrame")
        action_frame.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
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
        moodle_frame.grid(row=4, column=0, sticky="nsew")
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

        ttk.Button(moodle_frame, text="Import Moodle Dates", command=self._import_moodle_dates).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(2, 4)
        )

        self.moodle_info_var = tk.StringVar(
            value="Imports homework/assignment due dates from Moodle text content."
        )
        ttk.Label(
            moodle_frame,
            textvariable=self.moodle_info_var,
            wraplength=320,
            style="Muted.TLabel",
        ).grid(row=4, column=0, columnspan=2, sticky="w")

        self.clear_all_button = ttk.Button(
            moodle_frame,
            text="Clear All Calendar Data",
            command=self._on_clear_all_requested,
        )
        self.clear_all_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = tk.Label(self, textvariable=self.status_var, anchor="w", padx=8, pady=6)
        self.status_label.grid(row=1, column=0, columnspan=3, sticky="ew")

        self._button_dates: Dict[int, Optional[date]] = {idx: None for idx in range(42)}
        self._set_active_view("calendar")

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
        self._refresh_calendar()

    def _apply_theme(self) -> None:
        """Applies the current theme colors to the app and popup windows."""
        t = self.theme

        self.configure(bg=t["bg"])

        self.style.configure("TFrame", background=t["bg"])
        self.style.configure("TLabel", background=t["bg"], foreground=t["text"])
        self.style.configure("Panel.TFrame", background=t["panel"])
        self.style.configure("Panel.TLabel", background=t["panel"], foreground=t["text"])
        self.style.configure("Sidebar.TFrame", background=t["sidebar"])
        self.style.configure("SidebarTitle.TLabel", background=t["sidebar"], foreground=t["sidebar_text"])
        self.style.configure("SidebarNav.TLabel", background=t["sidebar"], foreground=t["sidebar_muted"])
        self.style.configure("Muted.TLabel", background=t["bg"], foreground=t["muted"])
        self.style.configure("MetricValue.TLabel", background=t["panel"], foreground=t["accent"])
        self.style.configure("MetricDanger.TLabel", background=t["panel"], foreground=t["danger"])
        self.style.configure("MetricSuccess.TLabel", background=t["panel"], foreground=t["success"])
        self.style.configure("TProgressbar", troughcolor=t["panel_alt"], background=t["accent"], bordercolor=t["border"])

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
            "LightDangerDay.TButton",
            background=t["day_danger_bg"],
            foreground=t["day_text"],
            bordercolor=t["danger"],
            padding=10,
        )
        self.style.configure(
            "LightWarningDay.TButton",
            background=t["day_warning_bg"],
            foreground=t["day_text"],
            bordercolor=t["warning"],
            padding=10,
        )
        self.style.configure(
            "LightSuccessDay.TButton",
            background=t["day_success_bg"],
            foreground=t["day_text"],
            bordercolor=t["success"],
            padding=10,
        )
        self.style.configure(
            "DarkDangerDay.TButton",
            background=t["day_danger_bg"],
            foreground=t["text"],
            bordercolor=t["danger"],
            padding=10,
        )
        self.style.configure(
            "DarkWarningDay.TButton",
            background=t["day_warning_bg"],
            foreground=t["text"],
            bordercolor=t["warning"],
            padding=10,
        )
        self.style.configure(
            "DarkSuccessDay.TButton",
            background=t["day_success_bg"],
            foreground=t["text"],
            bordercolor=t["success"],
            padding=10,
        )

        self.style.configure(
            "DangerDay.TButton",
            background=t["panel"],
            foreground=t["danger"],
            bordercolor=t["border"],
            padding=10,
        )
        self.style.configure(
            "WarningDay.TButton",
            background=t["panel"],
            foreground=t["warning"],
            bordercolor=t["border"],
            padding=10,
        )
        self.style.configure(
            "SuccessDay.TButton",
            background=t["panel"],
            foreground=t["success"],
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

        if hasattr(self, "deadline_list"):
            self.deadline_list.configure(
                bg=t["input_bg"],
                fg=t["input_fg"],
                selectbackground=t["list_select_bg"],
                selectforeground=t["list_select_fg"],
                highlightbackground=t["border"],
                highlightcolor=t["accent"],
                relief="flat",
            )

        if hasattr(self, "assignments_list"):
            self.assignments_list.configure(
                bg=t["input_bg"],
                fg=t["input_fg"],
                selectbackground=t["list_select_bg"],
                selectforeground=t["list_select_fg"],
                highlightbackground=t["border"],
                highlightcolor=t["accent"],
                relief="flat",
            )

        if hasattr(self, "due_list"):
            self.due_list.configure(
                bg=t["input_bg"],
                fg=t["input_fg"],
                selectbackground=t["list_select_bg"],
                selectforeground=t["list_select_fg"],
                highlightbackground=t["border"],
                highlightcolor=t["accent"],
                relief="flat",
            )

        if hasattr(self, "legend_canvas_red"):
            self.legend_canvas_red.configure(bg=t["panel"])
            self.legend_canvas_yellow.configure(bg=t["panel"])
            self.legend_canvas_green.configure(bg=t["panel"])
            self.legend_canvas_red.delete("all")
            self.legend_canvas_yellow.delete("all")
            self.legend_canvas_green.delete("all")
            for canvas, color in (
                (self.legend_canvas_red, t["danger"]),
                (self.legend_canvas_yellow, t["warning"]),
                (self.legend_canvas_green, t["success"]),
            ):
                canvas.create_oval(2, 2, 10, 10, fill=color, outline=color)

        self._refresh_sidebar_state()
        self._refresh_view_content()

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

        self._refresh_legend_dots()
        self._apply_accessibility_preferences()

    def _get_font_family(self) -> str:
        """Returns the preferred application font family based on the accessibility setting."""
        if str(self.font_family_var.get()) == "dyslexic":
            available = set(tkfont.families(self))
            for candidate in ("Comic Sans MS", "Verdana", "Arial"):
                if candidate in available:
                    return candidate
        return "Segoe UI"

    def _get_font_size(self) -> int:
        """Returns the fixed font size in points based on the accessibility setting."""
        choice = str(self.font_size_var.get()).strip().lower()
        if choice == "small":
            return 10
        if choice == "large":
            return 14
        return 12  # Medium (default)

    def _apply_accessibility_preferences(self) -> None:
        """Applies font family and size preferences across the visible UI using fixed sizes."""
        family = self._get_font_family()
        target_size = self._get_font_size()
        seen: set[int] = set()

        def apply_to_widget(widget: tk.Widget) -> None:
            widget_id = id(widget)
            if widget_id in seen:
                return
            seen.add(widget_id)

            try:
                current_font = tkfont.Font(font=widget.cget("font"))
            except tk.TclError:
                current_font = None

            if current_font is not None:
                current_font.configure(family=family, size=target_size)
                try:
                    widget.configure(font=current_font)
                except tk.TclError:
                    pass

            for child in widget.winfo_children():
                apply_to_widget(child)

        apply_to_widget(self)

        for style_name in ("TLabel", "Panel.TLabel", "Muted.TLabel", "SidebarTitle.TLabel", "SidebarNav.TLabel"):
            try:
                font_spec = self.style.lookup(style_name, "font")
                if not font_spec:
                    font_spec = "TkDefaultFont"
                style_font = tkfont.Font(font=font_spec)
                style_font.configure(family=family, size=target_size)
                self.style.configure(style_name, font=style_font)
            except tk.TclError:
                pass

        for style_name in (
            "TButton",
            "NormalDay.TButton",
            "SelectedDay.TButton",
            "OverflowDay.TButton",
            "LightDangerDay.TButton",
            "LightWarningDay.TButton",
            "LightSuccessDay.TButton",
            "DarkDangerDay.TButton",
            "DarkWarningDay.TButton",
            "DarkSuccessDay.TButton",
            "DangerDay.TButton",
            "WarningDay.TButton",
            "SuccessDay.TButton",
        ):
            try:
                font_spec = self.style.lookup(style_name, "font")
                if not font_spec:
                    font_spec = "TkDefaultFont"
                style_font = tkfont.Font(font=font_spec)
                style_font.configure(family=family, size=target_size)
                self.style.configure(style_name, font=style_font)
            except tk.TclError:
                pass

        self._refresh_day_button_fonts(family)

        self._refresh_legend_dots()

    def _refresh_day_button_fonts(self, family: Optional[str] = None) -> None:
        """Keeps calendar day buttons compact even when accessibility fonts grow."""
        if family is None:
            family = self._get_font_family()

        try:
            day_font = tkfont.Font(family=family, size=9, weight="bold")
        except tk.TclError:
            day_font = tkfont.nametofont("TkDefaultFont")
            day_font.configure(size=9, weight="bold")

        for style_name in (
            "NormalDay.TButton",
            "SelectedDay.TButton",
            "OverflowDay.TButton",
            "LightDangerDay.TButton",
            "LightWarningDay.TButton",
            "LightSuccessDay.TButton",
            "DarkDangerDay.TButton",
            "DarkWarningDay.TButton",
            "DarkSuccessDay.TButton",
            "DangerDay.TButton",
            "WarningDay.TButton",
            "SuccessDay.TButton",
        ):
            try:
                self.style.configure(style_name, font=day_font)
            except tk.TclError:
                pass

    def _on_accessibility_settings_changed(self) -> None:
        """Normalizes the settings values, applies them, and persists them locally."""
        size_choice = str(self.font_size_var.get()).strip().title() or "Medium"
        if size_choice not in {"Small", "Medium", "Large"}:
            size_choice = "Medium"
        self.font_size_var.set(size_choice)

        family_mode = str(self.font_family_var.get()).strip().lower()
        if family_mode not in {"standard", "dyslexic"}:
            family_mode = "standard"
        self.font_family_var.set(family_mode)

        self.app_settings["font_family_mode"] = family_mode
        self.app_settings["font_size"] = size_choice.lower()
        self.app_settings["color_blind_mode"] = bool(self.color_blind_var.get())
        self._save_items()
        self._apply_accessibility_preferences()
        self._refresh_calendar()
        self._refresh_view_lists()

    def _reset_accessibility_settings(self) -> None:
        """Restores the default accessibility configuration."""
        self.font_family_var.set("standard")
        self.font_size_var.set("Medium")
        self.color_blind_var.set(False)
        self._on_accessibility_settings_changed()

    def _refresh_legend_dots(self) -> None:
        """Redraws the legend circles so they remain visible in both themes."""
        if not hasattr(self, "legend_canvas_red"):
            return

        if self.color_blind_var.get():
            self.legend_label_red.config(text="⚠️ URGENT")
            self.legend_label_yellow.config(text="SOON")
            self.legend_label_green.config(text="LATER")
        else:
            self.legend_label_red.config(text="Overdue / <=24h")
            self.legend_label_yellow.config(text="<=3 days")
            self.legend_label_green.config(text="Later")

        for canvas, color in (
            (self.legend_canvas_red, self.theme["danger"]),
            (self.legend_canvas_yellow, self.theme["warning"]),
            (self.legend_canvas_green, self.theme["success"]),
        ):
            canvas.delete("all")
            canvas.create_oval(1, 1, 11, 11, fill=color, outline=color)

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
                day_items = self.items_by_day.get(self._date_key(day), [])
                count = len(day_items)
                suffix = f"\n({count})" if count else ""
                btn.config(text=f"{day.day}{suffix}", state="normal")
                urgency = self._day_urgency(day_items, day)
                if day == self.selected_date and urgency == "none":
                    style_name = "SelectedDay.TButton"
                elif urgency == "danger":
                    style_name = "LightDangerDay.TButton" if self.theme_name == "light" else "DarkDangerDay.TButton"
                elif urgency == "warning":
                    style_name = "LightWarningDay.TButton" if self.theme_name == "light" else "DarkWarningDay.TButton"
                elif urgency == "success":
                    style_name = "LightSuccessDay.TButton" if self.theme_name == "light" else "DarkSuccessDay.TButton"
                elif day == self.selected_date:
                    style_name = "SelectedDay.TButton"
                else:
                    style_name = "NormalDay.TButton"
                btn.config(style=style_name)
            else:
                btn.config(text=f"{day.day}", state="disabled", style="OverflowDay.TButton")

        self._refresh_selected_day_label()
        self._refresh_item_list()
        self._refresh_dashboard_panels()
        self._refresh_view_content()

    def _select_day_from_button(self, idx: int) -> None:
        """Updates the active date based on the clicked calendar button."""
        mapped_date = self._button_dates.get(idx)
        if mapped_date is None:
            return
        self.selected_date = mapped_date
        self._refresh_calendar()
        self._set_status(f"Selected {self.selected_date.isoformat()}")

    def _set_active_view(self, view_name: str) -> None:
        """Switches the main workspace between calendar, assignment, deadline, and settings views."""
        self.active_view = view_name
        self._refresh_sidebar_state()
        self._refresh_view_content()

    def _refresh_sidebar_state(self) -> None:
        """Updates sidebar selection and hover-ready active styling."""
        if not hasattr(self, "sidebar_buttons"):
            return

        for view_name, button in self.sidebar_buttons.items():
            if view_name == self.active_view:
                button.config(bg=self.theme["sidebar_active"], relief="flat")
            else:
                button.config(bg=self.theme["sidebar"], relief="flat")

    def _on_sidebar_hover(self, button: tk.Button, is_hovering: bool) -> None:
        """Applies a subtle hover treatment to sidebar navigation items."""
        if button.cget("bg") == self.theme["sidebar_active"]:
            return
        button.config(bg=self.theme["sidebar_active"] if is_hovering else self.theme["sidebar"])

    def _refresh_view_content(self) -> None:
        """Shows the selected workspace and hides the others."""
        if not hasattr(self, "view_title_label"):
            return

        is_calendar = self.active_view == "calendar"
        self.view_title_label.config(
            text={
                "calendar": "Calendar",
                "assignments": "Assignments",
                "due": "Due Soon",
                "settings": "Settings",
            }.get(self.active_view, "Calendar")
        )

        for widget in (self.nav_frame, self.month_label, self.prev_btn, self.next_btn, self.nav_spacer):
            if is_calendar:
                widget.grid()
            else:
                widget.grid_remove()

        for widget in (self.calendar_grid, self.metrics_frame, self.progress_row):
            if is_calendar:
                widget.grid()
            else:
                widget.grid_remove()

        if hasattr(self, "assignments_view"):
            self.assignments_view.tkraise()
            if self.active_view == "assignments":
                self.assignments_view.grid()
            else:
                self.assignments_view.grid_remove()

        if hasattr(self, "due_view"):
            self.due_view.tkraise()
            if self.active_view == "due":
                self.due_view.grid()
            else:
                self.due_view.grid_remove()

        if hasattr(self, "settings_view"):
            self.settings_view.tkraise()
            if self.active_view == "settings":
                self.settings_view.grid()
            else:
                self.settings_view.grid_remove()

        if is_calendar:
            self.month_label.tkraise()
            self.calendar_grid.tkraise()

        self._refresh_view_lists()

    def _refresh_selected_day_label(self) -> None:
        """Updates the sidebar header with the currently selected day."""
        self.selected_day_label.config(text=f"Selected Day: {self.selected_date.strftime('%A, %b %d, %Y')}")

    def _refresh_item_list(self) -> None:
        """Rebuilds the listbox with all items for the selected day."""
        self.item_list.delete(0, tk.END)
        day_items = self.items_by_day.get(self._date_key(self.selected_date), [])
        for idx, item in enumerate(day_items):
            _, _, color = self._urgency_metadata(item, self.selected_date)
            self.item_list.insert(tk.END, self._format_item_display(item, self.selected_date))
            self.item_list.itemconfig(idx, foreground=color)
        self._clear_editor(keep_status=True)

    def _day_urgency(self, day_items: List[CalendarItem], day_value: date) -> str:
        """Returns the most urgent color key for a day based on all items due on that day."""
        if not day_items:
            return "none"

        urgencies = [self._item_urgency(item, day_value) for item in day_items]
        if "danger" in urgencies:
            return "danger"
        if "warning" in urgencies:
            return "warning"
        return "success"

    def _item_urgency(self, item: CalendarItem, fallback_day: date) -> str:
        """Computes urgency using the saved due date and exact due time."""
        due_dt = self._item_due_datetime(item, fallback_day)
        if due_dt is None:
            return "success"
        delta = due_dt - datetime.now()
        if delta.total_seconds() <= 24 * 60 * 60:
            return "danger"
        if delta.total_seconds() <= 3 * 24 * 60 * 60:
            return "warning"
        return "success"

    def _item_due_datetime(self, item: CalendarItem, fallback_day: date) -> Optional[datetime]:
        """Parses the saved due date/time, falling back to the calendar day for older records."""
        due_date_text = (item.due_date or fallback_day.isoformat()).strip()
        due_time_text = (item.due_time or item.time_label or "11:59 PM").strip() or "11:59 PM"
        try:
            due_day = date.fromisoformat(due_date_text)
        except ValueError:
            try:
                due_day = fallback_day
            except ValueError:
                return None

        time_formats = ["%I:%M %p", "%H:%M"]
        parsed_time = None
        for time_format in time_formats:
            try:
                parsed_time = datetime.strptime(due_time_text.upper(), time_format).time()
                break
            except ValueError:
                continue
        if parsed_time is None:
            return None
        return datetime.combine(due_day, parsed_time)

    def _parse_due_date(self, value: str) -> date:
        """Parses MM/DD/YYYY due dates from the editor."""
        return datetime.strptime(value.strip(), "%m/%d/%Y").date()

    def _parse_due_time(self, value: str) -> str:
        """Validates the due time editor field and normalizes it to HH:MM AM/PM."""
        cleaned = value.strip().upper()
        parsed = datetime.strptime(cleaned, "%I:%M %p")
        return parsed.strftime("%I:%M %p")

    def _urgency_metadata(self, item: CalendarItem, fallback_day: date) -> Tuple[str, str, str]:
        """Returns icon, label, and color for the item's urgency state."""
        urgency = self._item_urgency(item, fallback_day)
        if urgency == "danger":
            return "⚠️", "URGENT", self.theme["danger"]
        if urgency == "warning":
            return "⏳", "SOON", self.theme["warning"]
        return "✅", "LATER", self.theme["success"]

    def _format_due_display(self, item: CalendarItem, fallback_day: date) -> str:
        """Formats an item using the saved due date and due time."""
        due_dt = self._item_due_datetime(item, fallback_day)
        if due_dt is None:
            return item.title.strip()
        icon, label, _color = self._urgency_metadata(item, fallback_day)
        if self.color_blind_var.get():
            prefix = f"{icon} {label}"
        else:
            prefix = icon
        if due_dt.date() == date.today():
            day_text = f"Today at {due_dt.strftime('%I:%M %p')}"
        elif due_dt.date() < date.today():
            day_text = f"Overdue: {due_dt.strftime('%b %d, %Y at %I:%M %p')}"
        else:
            day_text = f"Due: {due_dt.strftime('%b %d, %Y at %I:%M %p')}"
        return f"{prefix} {day_text} - {item.title.strip()}"

    def _format_item_display(self, item: CalendarItem, fallback_day: date) -> str:
        """Formats one item for listbox display."""
        return self._format_due_display(item, fallback_day)

    def _iter_sorted_items(self) -> List[Tuple[date, CalendarItem]]:
        """Returns all stored items sorted by due date, time label, and title."""
        pairs: List[Tuple[date, CalendarItem]] = []
        for day_key, items in self.items_by_day.items():
            try:
                day_value = date.fromisoformat(day_key)
            except ValueError:
                continue
            for item in items:
                pairs.append((day_value, item))
        pairs.sort(key=lambda entry: (entry[0], (entry[1].due_time or entry[1].time_label).lower(), entry[1].title.lower()))
        return pairs

    def _refresh_dashboard_panels(self) -> None:
        """Updates sidebar deadline list and compact progress metrics."""
        all_items = self._iter_sorted_items()
        today = date.today()

        total_count = len(all_items)
        due_today_count = sum(1 for day_value, item in all_items if self._item_due_datetime(item, day_value) is not None and self._item_due_datetime(item, day_value).date() == today)
        completed_count = sum(1 for day_value, item in all_items if self._item_due_datetime(item, day_value) is not None and self._item_due_datetime(item, day_value) < datetime.now())

        self.metric_total_label.config(text=str(total_count))
        self.metric_due_today_label.config(text=str(due_today_count))
        self.metric_completed_label.config(text=str(completed_count))

        progress_pct = (completed_count / total_count * 100.0) if total_count else 0.0
        self.progress_var.set(progress_pct)
        self.progress_text_label.config(text=f"{int(round(progress_pct))}%")

        self.deadline_list.delete(0, tk.END)
        overdue_items = [entry for entry in all_items if entry[0] < today][-5:]
        upcoming_items = [entry for entry in all_items if entry[0] >= today][: max(0, 12 - len(overdue_items))]
        display_items = overdue_items + upcoming_items
        if not display_items:
            self.deadline_list.insert(tk.END, "No upcoming assignments.")
            self.deadline_list.itemconfig(0, foreground=self.theme["muted"])
            return

        for idx, (day_value, item) in enumerate(display_items):
            _, _, color = self._urgency_metadata(item, day_value)
            due_display = self._format_due_display(item, day_value)
            self.deadline_list.insert(tk.END, due_display)
            self.deadline_list.itemconfig(idx, foreground=color)

    def _on_item_selected(self, _event: object) -> None:
        """Loads the selected item into the inline editor fields."""
        selected_item = self._get_selected_item()
        if selected_item is None:
            return
        self.title_var.set(selected_item.title)
        self.due_date_var.set((selected_item.due_date or self.selected_date.isoformat()).strip())
        self.time_var.set((selected_item.due_time or selected_item.time_label or "11:59 PM").strip())
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

        try:
            due_date = self._parse_due_date(self.due_date_var.get())
        except ValueError:
            message = "Enter a valid due date in MM/DD/YYYY format."
            self._set_status(message)
            self._show_error(message, "Invalid Due Date")
            return

        try:
            due_time = self._parse_due_time(self.time_var.get())
        except ValueError:
            message = "Enter a valid due time in HH:MM AM/PM format."
            self._set_status(message)
            self._show_error(message, "Invalid Due Time")
            return

        new_item = CalendarItem(
            item_id=self.next_item_id,
            title=title,
            due_date=due_date.isoformat(),
            due_time=due_time,
            details=self.details_text.get("1.0", tk.END).strip(),
            time_label=due_time,
        )
        self.next_item_id += 1

        key = self._date_key(due_date)
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

        try:
            due_date = self._parse_due_date(self.due_date_var.get())
        except ValueError:
            message = "Enter a valid due date in MM/DD/YYYY format."
            self._set_status(message)
            self._show_error(message, "Invalid Due Date")
            return

        try:
            due_time = self._parse_due_time(self.time_var.get())
        except ValueError:
            message = "Enter a valid due time in HH:MM AM/PM format."
            self._set_status(message)
            self._show_error(message, "Invalid Due Time")
            return

        key = self._date_key(self.selected_date)
        items = self.items_by_day.get(key, [])
        if not (0 <= selected_index < len(items)):
            self._set_status("Selected item is no longer available.")
            return

        updated_item = items.pop(selected_index)
        if not items:
            self.items_by_day.pop(key, None)

        updated_item.title = title
        updated_item.due_date = due_date.isoformat()
        updated_item.due_time = due_time
        updated_item.time_label = due_time
        updated_item.details = self.details_text.get("1.0", tk.END).strip()

        target_key = self._date_key(due_date)
        self.items_by_day.setdefault(target_key, []).append(updated_item)
        if target_key != key:
            self.selected_date = due_date

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
        self.due_date_var.set(self.selected_date.strftime("%m/%d/%Y"))
        self.time_var.set("11:59 PM")
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
                    due_date=date_key,
                    due_time=event.time_label.strip() or "11:59 PM",
                    details=details_text,
                    time_label=event.time_label.strip() or "11:59 PM",
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
            upcoming_by_day[day_value] = list(items)

        if not upcoming_by_day:
            return "No upcoming due dates from today onward.", None, 0

        future_days = [day_value for day_value in upcoming_by_day if any(self._item_due_datetime(item, day_value) is not None and self._item_due_datetime(item, day_value).date() >= today for item in upcoming_by_day[day_value])]
        if not future_days:
            return "No upcoming due dates from today onward.", None, 0

        first_due_date = min(future_days)
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
                    (item.due_time or item.time_label).strip().lower(),
                    item.title.strip().lower(),
                ),
            )
            day_label = day_value.strftime("%a, %b %d")
            lines.append(f"{day_label} ({len(day_items)} item{'s' if len(day_items) != 1 else ''})")
            for item in day_items:
                due_dt = self._item_due_datetime(item, day_value)
                if due_dt is None:
                    lines.append(f"- {item.title}")
                else:
                    lines.append(f"- Due: {due_dt.strftime('%b %d, %Y at %I:%M %p')} - {item.title}")

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

    def _refresh_view_lists(self) -> None:
        """Updates the assignment and due-soon list views for the selected sidebar mode."""
        if not hasattr(self, "assignments_list"):
            return

        rows = self._iter_sorted_items()

        self.assignments_list.delete(0, tk.END)
        for idx, (day_value, item) in enumerate(rows):
            _, _, color = self._urgency_metadata(item, day_value)
            self.assignments_list.insert(tk.END, self._format_due_display(item, day_value))
            self.assignments_list.itemconfig(idx, foreground=color)

        self.due_list.delete(0, tk.END)
        urgent_rows = [entry for entry in rows if self._item_urgency(entry[1], entry[0]) in {"danger", "warning"}]
        if not urgent_rows:
            self.due_list.insert(tk.END, "No urgent deadlines right now.")
        else:
            for idx, (day_value, item) in enumerate(urgent_rows):
                _, _, color = self._urgency_metadata(item, day_value)
                self.due_list.insert(tk.END, self._format_due_display(item, day_value))
                self.due_list.itemconfig(idx, foreground=color)

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

        self._load_app_settings(payload.get("settings", {}))

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
                parsed_item = CalendarItem.from_dict(raw)
                if not parsed_item.due_date:
                    parsed_item.due_date = str(key)
                if not parsed_item.due_time:
                    parsed_item.due_time = parsed_item.time_label.strip() or "11:59 PM"
                if not parsed_item.time_label:
                    parsed_item.time_label = parsed_item.due_time
                parsed_items.append(parsed_item)
            if parsed_items:
                parsed_map[str(key)] = parsed_items

        self.items_by_day = parsed_map
        max_seen_id = max(
            (item.item_id for group in self.items_by_day.values() for item in group),
            default=0,
        )
        self.next_item_id = max(next_id, max_seen_id + 1)

    def _load_app_settings(self, payload: object) -> None:
        """Restores persisted accessibility settings from the data file."""
        settings = dict(DEFAULT_APP_SETTINGS)
        if isinstance(payload, dict):
            family_mode = str(payload.get("font_family_mode", DEFAULT_APP_SETTINGS["font_family_mode"]))
            if family_mode in {"standard", "dyslexic"}:
                settings["font_family_mode"] = family_mode

            font_size = str(payload.get("font_size", DEFAULT_APP_SETTINGS["font_size"]))
            if font_size in {"small", "medium", "large"}:
                settings["font_size"] = font_size

            settings["color_blind_mode"] = bool(payload.get("color_blind_mode", DEFAULT_APP_SETTINGS["color_blind_mode"]))

        self.app_settings = settings
        self.font_family_var.set(str(settings["font_family_mode"]))
        self.font_size_var.set(str(settings["font_size"]).title())
        self.color_blind_var.set(bool(settings["color_blind_mode"]))

    def _save_items(self) -> None:
        """Persists all calendar items to the active JSON data file."""
        serializable_map = {
            key: [asdict(item) for item in items]
            for key, items in self.items_by_day.items()
        }
        payload = {
            "next_item_id": self.next_item_id,
            "items_by_day": serializable_map,
            "settings": {
                "font_family_mode": self.font_family_var.get(),
                "font_size": str(self.font_size_var.get()).strip().lower(),
                "color_blind_mode": bool(self.color_blind_var.get()),
            },
        }
        try:
            DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            message = "Could not save data to disk."
            self._set_status(message)
            self._show_error(message, "Save Error")


def main() -> None:
    """Application entry point."""
    if "--smoke-test" in sys.argv:
        raise SystemExit(run_smoke_test())

    app = CalendarApp()
    app.mainloop()


def run_smoke_test() -> int:
    """Runs the headless golden-path workflow used by automated tests."""
    crawler = MoodleCrawler()
    assignment_url = "https://moodle.example.edu/mod/assign/view.php?id=453"
    assignment_html = """
    <html>
      <body>
        <h1>Golden Path Assignment</h1>
        <p>Due: Friday, May 1, 2026, 11:59 PM</p>
      </body>
    </html>
    """
    assignment_index = crawler._build_assignment_index([(assignment_url, assignment_html)])
    events = crawler._extract_events_from_page(assignment_url, assignment_html, assignment_index)
    if len(events) != 1:
        print("Smoke test failed: expected one Moodle event.")
        return 1

    app = object.__new__(CalendarApp)
    app.items_by_day = {}
    app.next_item_id = 1
    app._save_items = lambda: None
    added_count, skipped_count, updated_count = app._store_moodle_events(events)
    if (added_count, skipped_count, updated_count) != (1, 0, 0):
        print("Smoke test failed: event was not imported into the calendar.")
        return 1

    stored_items = app.items_by_day.get(events[0].event_date.isoformat(), [])
    if len(stored_items) != 1 or events[0].source_url not in stored_items[0].details:
        print("Smoke test failed: imported calendar item did not match expected title/date.")
        return 1

    print("Smoke test passed: Moodle assignment imported into calendar data.")
    return 0


if __name__ == "__main__":
    main()
