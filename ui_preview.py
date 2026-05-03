"""UI Preview/Mockup for Desktop Calendar App - 3 Design Options

This file demonstrates 3 possible UI directions without modifying the working app:
1. Modern Light Theme
2. Dark Mode Dashboard
3. Sidebar Student Dashboard with Upcoming Deadlines

Run with: python ui_preview.py
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta
from typing import List, Tuple


# Sample data
SAMPLE_ASSIGNMENTS = [
    ("CMPS 453 - Midterm Project", "2024-05-10", "Today"),
    ("CMPS 456 - Essay Assignment", "2024-05-12", "2 days away"),
    ("MATH 201 - Problem Set", "2024-05-15", "5 days away"),
    ("PHYS 301 - Lab Report", "2024-05-18", "8 days away"),
    ("CMPS 453 - Final Exam", "2024-05-25", "15 days away"),
]

SAMPLE_CALENDAR_ITEMS = {
    1: ["Lecture: Databases", "Office Hours 2pm"],
    5: ["Midterm Prep", "Team Meeting 3pm"],
    10: ["Midterm Project Due", "Review Session"],
    12: ["Essay Draft Due"],
    15: ["Problem Set Due"],
}


class ModernLightTheme(tk.Tk):
    """Design Option 1: Clean, minimalist modern light theme"""
    
    def __init__(self):
        super().__init__()
        self.title("📅 Desktop Calendar - Modern Light")
        self.geometry("900x650")
        self.configure(bg="#FFFFFF")
        
        # Colors
        self.PRIMARY = "#0066CC"
        self.SECONDARY = "#F0F4F8"
        self.TEXT = "#1A1A1A"
        self.TEXT_LIGHT = "#666666"
        self.ACCENT = "#FF6B6B"
        
        self._build_ui()
    
    def _build_ui(self):
        """Build the modern light theme UI"""
        # Header
        header = tk.Frame(self, bg=self.PRIMARY, height=80)
        header.pack(fill=tk.X, padx=0, pady=0)
        header.pack_propagate(False)
        
        title = tk.Label(
            header, 
            text="📅 My Calendar", 
            font=("Segoe UI", 24, "bold"),
            bg=self.PRIMARY,
            fg="white"
        )
        title.pack(side=tk.LEFT, padx=20, pady=20)
        
        # Main container
        main = tk.Frame(self, bg="white")
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Left column - Calendar days
        left = tk.Frame(main, bg="white")
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 20))
        
        cal_label = tk.Label(
            left, 
            text="May 2024", 
            font=("Segoe UI", 14, "bold"),
            bg="white",
            fg=self.TEXT
        )
        cal_label.pack(anchor=tk.W, pady=(0, 15))
        
        # Calendar grid (simple 7x5)
        for week in range(5):
            week_frame = tk.Frame(left, bg="white")
            week_frame.pack(fill=tk.X, pady=5)
            
            for day in range(7):
                day_num = week * 7 + day + 1
                if day_num > 31:
                    break
                
                day_frame = tk.Frame(
                    week_frame, 
                    bg=self.SECONDARY, 
                    width=100, 
                    height=70,
                    relief=tk.FLAT,
                    bd=1
                )
                day_frame.pack(side=tk.LEFT, padx=2, pady=2, fill=tk.BOTH, expand=True)
                day_frame.pack_propagate(False)
                
                # Day number
                day_label = tk.Label(
                    day_frame,
                    text=f"{day_num}",
                    font=("Segoe UI", 12, "bold"),
                    bg=self.SECONDARY,
                    fg=self.TEXT
                )
                day_label.pack(anchor=tk.NW, padx=5, pady=3)
                
                # Items preview
                if day_num in SAMPLE_CALENDAR_ITEMS:
                    items_text = ", ".join(SAMPLE_CALENDAR_ITEMS[day_num][:1])
                    item_label = tk.Label(
                        day_frame,
                        text=f"✓ {items_text[:15]}...",
                        font=("Segoe UI", 8),
                        bg=self.SECONDARY,
                        fg=self.TEXT_LIGHT,
                        wraplength=90,
                        justify=tk.LEFT
                    )
                    item_label.pack(anchor=tk.W, padx=5, pady=(25, 0))
        
        # Right column - Upcoming assignments
        right = tk.Frame(main, bg=self.SECONDARY, relief=tk.FLAT)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=15, pady=15)
        right.pack_propagate(False)
        
        upcoming_label = tk.Label(
            right,
            text="📌 Upcoming Deadlines",
            font=("Segoe UI", 14, "bold"),
            bg=self.SECONDARY,
            fg=self.TEXT
        )
        upcoming_label.pack(anchor=tk.W, padx=15, pady=(15, 10))
        
        for assignment, date, days in SAMPLE_ASSIGNMENTS:
            item_frame = tk.Frame(right, bg="white", height=50)
            item_frame.pack(fill=tk.X, padx=10, pady=8)
            item_frame.pack_propagate(False)
            
            title_label = tk.Label(
                item_frame,
                text=assignment,
                font=("Segoe UI", 10, "bold"),
                bg="white",
                fg=self.TEXT,
                justify=tk.LEFT
            )
            title_label.pack(anchor=tk.W, padx=10, pady=(5, 0))
            
            info_label = tk.Label(
                item_frame,
                text=f"📆 {date} • {days}",
                font=("Segoe UI", 9),
                bg="white",
                fg=self.TEXT_LIGHT
            )
            info_label.pack(anchor=tk.W, padx=10, pady=(0, 5))
        
        # Footer buttons
        footer = tk.Frame(self, bg="white")
        footer.pack(fill=tk.X, padx=20, pady=20)
        
        add_btn = tk.Button(
            footer,
            text="➕ Add Assignment",
            font=("Segoe UI", 10, "bold"),
            bg=self.PRIMARY,
            fg="white",
            relief=tk.FLAT,
            padx=20,
            pady=10
        )
        add_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        import_btn = tk.Button(
            footer,
            text="📥 Import from Moodle",
            font=("Segoe UI", 10, "bold"),
            bg=self.ACCENT,
            fg="white",
            relief=tk.FLAT,
            padx=20,
            pady=10
        )
        import_btn.pack(side=tk.LEFT)


class DarkModeDashboard(tk.Tk):
    """Design Option 2: Dark mode professional dashboard"""
    
    def __init__(self):
        super().__init__()
        self.title("📅 Desktop Calendar - Dark Mode")
        self.geometry("900x650")
        self.configure(bg="#0D0D0D")
        
        # Colors
        self.BG_DARK = "#0D0D0D"
        self.BG_CARD = "#1A1A1A"
        self.PRIMARY = "#00D4FF"
        self.ACCENT = "#FF6B9D"
        self.TEXT = "#FFFFFF"
        self.TEXT_DIM = "#A0A0A0"
        
        self._build_ui()
    
    def _build_ui(self):
        """Build dark mode dashboard UI"""
        # Header
        header = tk.Frame(self, bg=self.BG_CARD, height=70)
        header.pack(fill=tk.X, padx=0, pady=0)
        header.pack_propagate(False)
        
        title = tk.Label(
            header,
            text="📅 CALENDAR DASHBOARD",
            font=("Segoe UI", 20, "bold"),
            bg=self.BG_CARD,
            fg=self.PRIMARY
        )
        title.pack(side=tk.LEFT, padx=20, pady=15)
        
        # Main container
        main = tk.Frame(self, bg=self.BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Top stats
        stats_frame = tk.Frame(main, bg=self.BG_DARK)
        stats_frame.pack(fill=tk.X, pady=(0, 15))
        
        stats = [
            ("📊 Total Items", "24", self.PRIMARY),
            ("⏰ Due Today", "2", self.ACCENT),
            ("✅ Completed", "18", "#00FF00"),
        ]
        
        for label, value, color in stats:
            stat = tk.Frame(main, bg=self.BG_CARD, relief=tk.FLAT, bd=1)
            stat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
            
            stat_label = tk.Label(stat, text=label, font=("Segoe UI", 10), bg=self.BG_CARD, fg=self.TEXT_DIM)
            stat_label.pack(anchor=tk.W, padx=15, pady=(10, 0))
            
            stat_value = tk.Label(stat, text=value, font=("Segoe UI", 24, "bold"), bg=self.BG_CARD, fg=color)
            stat_value.pack(anchor=tk.W, padx=15, pady=(0, 10))
        
        # Content area
        content = tk.Frame(main, bg=self.BG_DARK)
        content.pack(fill=tk.BOTH, expand=True, pady=15)
        
        # Left - Calendar mini view
        left = tk.Frame(content, bg=self.BG_CARD, relief=tk.FLAT, bd=1)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        cal_title = tk.Label(left, text="May 2024", font=("Segoe UI", 12, "bold"), bg=self.BG_CARD, fg=self.TEXT)
        cal_title.pack(anchor=tk.W, padx=15, pady=10)
        
        for i in range(1, 32, 7):
            week = tk.Frame(left, bg=self.BG_CARD)
            week.pack(fill=tk.X, padx=10, pady=2)
            
            for day in range(min(7, 32 - i)):
                day_btn = tk.Button(
                    week,
                    text=str(i + day),
                    width=3,
                    bg=self.BG_DARK if (i + day) not in SAMPLE_CALENDAR_ITEMS else self.PRIMARY,
                    fg=self.TEXT if (i + day) not in SAMPLE_CALENDAR_ITEMS else "#000000",
                    relief=tk.FLAT,
                    font=("Segoe UI", 9)
                )
                day_btn.pack(side=tk.LEFT, padx=2)
        
        # Right - Task list
        right = tk.Frame(content, bg=self.BG_CARD, relief=tk.FLAT, bd=1)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        task_title = tk.Label(right, text="⚡ Priority Tasks", font=("Segoe UI", 12, "bold"), bg=self.BG_CARD, fg=self.PRIMARY)
        task_title.pack(anchor=tk.W, padx=15, pady=10)
        
        for assignment, date, days in SAMPLE_ASSIGNMENTS[:5]:
            task = tk.Frame(right, bg=self.BG_DARK, relief=tk.FLAT, bd=1)
            task.pack(fill=tk.X, padx=10, pady=5)
            task.pack_propagate(False)
            
            checkbox = tk.Label(task, text="☐", font=("Segoe UI", 12), bg=self.BG_DARK, fg=self.PRIMARY, width=2)
            checkbox.pack(side=tk.LEFT, padx=10, pady=8)
            
            info = tk.Frame(task, bg=self.BG_DARK)
            info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=0, pady=5)
            
            task_name = tk.Label(info, text=assignment, font=("Segoe UI", 9, "bold"), bg=self.BG_DARK, fg=self.TEXT, justify=tk.LEFT)
            task_name.pack(anchor=tk.W)
            
            task_meta = tk.Label(info, text=days, font=("Segoe UI", 8), bg=self.BG_DARK, fg=self.ACCENT)
            task_meta.pack(anchor=tk.W)
        
        # Footer
        footer = tk.Frame(self, bg=self.BG_CARD, height=60)
        footer.pack(fill=tk.X, padx=0, pady=0)
        footer.pack_propagate(False)
        
        btn1 = tk.Button(footer, text="➕ Add", bg=self.PRIMARY, fg="#000000", relief=tk.FLAT, font=("Segoe UI", 10, "bold"), padx=20)
        btn1.pack(side=tk.LEFT, padx=15, pady=10)
        
        btn2 = tk.Button(footer, text="📥 Moodle", bg=self.ACCENT, fg="#FFFFFF", relief=tk.FLAT, font=("Segoe UI", 10, "bold"), padx=20)
        btn2.pack(side=tk.LEFT, padx=5, pady=10)


class SidebarStudentDashboard(tk.Tk):
    """Design Option 3: Sidebar layout with upcoming deadlines focus"""
    
    def __init__(self):
        super().__init__()
        self.title("📅 Desktop Calendar - Student Dashboard")
        self.geometry("1000x700")
        self.configure(bg="#F5F7FA")
        
        # Colors
        self.BG = "#F5F7FA"
        self.SIDEBAR_BG = "#2C3E50"
        self.CARD_BG = "#FFFFFF"
        self.PRIMARY = "#3498DB"
        self.WARNING = "#E74C3C"
        self.SUCCESS = "#27AE60"
        self.TEXT = "#2C3E50"
        self.TEXT_LIGHT = "#7F8C8D"
        
        self._build_ui()
    
    def _build_ui(self):
        """Build sidebar student dashboard UI"""
        # Sidebar
        sidebar = tk.Frame(self, bg=self.SIDEBAR_BG, width=250)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        
        # Sidebar header
        sidebar_title = tk.Label(
            sidebar,
            text="📚 STUDENT",
            font=("Segoe UI", 16, "bold"),
            bg=self.SIDEBAR_BG,
            fg="white"
        )
        sidebar_title.pack(padx=15, pady=20)
        
        # Menu items
        menu_items = [
            ("📅 Dashboard", "dashboard"),
            ("📋 All Assignments", "all"),
            ("⏰ Due Soon", "due"),
            ("✅ Completed", "done"),
            ("📥 Import", "import"),
            ("⚙️  Settings", "settings"),
        ]
        
        for text, _ in menu_items:
            menu_btn = tk.Button(
                sidebar,
                text=text,
                font=("Segoe UI", 11),
                bg=self.SIDEBAR_BG,
                fg="white",
                relief=tk.FLAT,
                anchor=tk.W,
                padx=20,
                pady=12,
                bd=0
            )
            menu_btn.pack(fill=tk.X, pady=3)
        
        # Main content
        content = tk.Frame(self, bg=self.BG)
        content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Top bar
        topbar = tk.Frame(content, bg=self.CARD_BG, height=60)
        topbar.pack(fill=tk.X, padx=0, pady=0)
        topbar.pack_propagate(False)
        
        greeting = tk.Label(
            topbar,
            text="👋 Welcome back! You have 5 upcoming deadlines",
            font=("Segoe UI", 13, "bold"),
            bg=self.CARD_BG,
            fg=self.TEXT
        )
        greeting.pack(anchor=tk.W, padx=25, pady=15)
        
        # Main content area
        main = tk.Frame(content, bg=self.BG)
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Critical deadlines section
        critical_label = tk.Label(
            main,
            text="🔴 CRITICAL - Due This Week",
            font=("Segoe UI", 12, "bold"),
            bg=self.BG,
            fg=self.WARNING
        )
        critical_label.pack(anchor=tk.W, pady=(0, 10))
        
        for assignment, date, days in SAMPLE_ASSIGNMENTS[:2]:
            card = tk.Frame(main, bg=self.CARD_BG, relief=tk.RAISED, bd=1)
            card.pack(fill=tk.X, pady=8)
            card.pack_propagate(False)
            
            left_col = tk.Frame(card, bg=self.WARNING, width=5)
            left_col.pack(side=tk.LEFT, fill=tk.Y, padx=0)
            left_col.pack_propagate(False)
            
            info_col = tk.Frame(card, bg=self.CARD_BG)
            info_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=15, pady=12)
            
            title_label = tk.Label(info_col, text=assignment, font=("Segoe UI", 11, "bold"), bg=self.CARD_BG, fg=self.TEXT)
            title_label.pack(anchor=tk.W)
            
            meta_label = tk.Label(info_col, text=f"📆 {date} ({days})", font=("Segoe UI", 9), bg=self.CARD_BG, fg=self.TEXT_LIGHT)
            meta_label.pack(anchor=tk.W, pady=(3, 0))
            
            action_btn = tk.Button(card, text="📝", font=("Segoe UI", 10), bg=self.CARD_BG, relief=tk.FLAT, padx=15)
            action_btn.pack(side=tk.RIGHT, padx=10, pady=12)
        
        # Upcoming section
        upcoming_label = tk.Label(
            main,
            text="📌 Upcoming",
            font=("Segoe UI", 12, "bold"),
            bg=self.BG,
            fg=self.PRIMARY
        )
        upcoming_label.pack(anchor=tk.W, pady=(20, 10))
        
        for assignment, date, days in SAMPLE_ASSIGNMENTS[2:5]:
            card = tk.Frame(main, bg=self.CARD_BG, relief=tk.FLAT, bd=1)
            card.pack(fill=tk.X, pady=5)
            
            label_frame = tk.Frame(card, bg=self.CARD_BG)
            label_frame.pack(fill=tk.X, padx=15, pady=10)
            
            checkbox = tk.Label(label_frame, text="☐", font=("Segoe UI", 11), bg=self.CARD_BG, fg=self.PRIMARY)
            checkbox.pack(side=tk.LEFT, padx=(0, 10))
            
            text_frame = tk.Frame(label_frame, bg=self.CARD_BG)
            text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            assign_label = tk.Label(text_frame, text=assignment, font=("Segoe UI", 10), bg=self.CARD_BG, fg=self.TEXT)
            assign_label.pack(anchor=tk.W)
            
            date_label = tk.Label(text_frame, text=days, font=("Segoe UI", 8), bg=self.CARD_BG, fg=self.TEXT_LIGHT)
            date_label.pack(anchor=tk.W, pady=(2, 0))


class PreviewSelector(tk.Tk):
    """Main window to select which preview to view"""
    
    def __init__(self):
        super().__init__()
        self.title("Desktop Calendar UI Preview")
        self.geometry("500x400")
        self.configure(bg="#FFFFFF")
        
        # Header
        header = tk.Label(
            self,
            text="📅 UI Preview Selector",
            font=("Segoe UI", 20, "bold"),
            bg="#FFFFFF",
            fg="#0066CC"
        )
        header.pack(pady=30)
        
        description = tk.Label(
            self,
            text="Choose a design direction to preview:\n\n",
            font=("Segoe UI", 11),
            bg="#FFFFFF",
            fg="#666666",
            justify=tk.CENTER
        )
        description.pack(pady=(0, 20))
        
        # Buttons
        button_frame = tk.Frame(self, bg="#FFFFFF")
        button_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        
        designs = [
            ("✨ Modern Light Theme", ModernLightTheme),
            ("🌙 Dark Mode Dashboard", DarkModeDashboard),
            ("📚 Sidebar Student Dashboard", SidebarStudentDashboard),
        ]
        
        for text, window_class in designs:
            btn = tk.Button(
                button_frame,
                text=text,
                font=("Segoe UI", 12, "bold"),
                bg="#0066CC",
                fg="white",
                relief=tk.FLAT,
                pady=15,
                command=lambda wc=window_class: self._open_preview(wc)
            )
            btn.pack(fill=tk.X, pady=10)
        
        # Footer
        footer = tk.Label(
            self,
            text="These are mockups only - the working app remains unchanged.",
            font=("Segoe UI", 9),
            bg="#FFFFFF",
            fg="#999999"
        )
        footer.pack(pady=20, side=tk.BOTTOM)
    
    def _open_preview(self, window_class):
        """Open a preview window"""
        preview = window_class()
        preview.mainloop()


if __name__ == "__main__":
    app = PreviewSelector()
    app.mainloop()
