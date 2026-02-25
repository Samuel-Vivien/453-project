# Desktop Calendar App

Single-window desktop calendar built with Python + Tkinter.

## Features

- Add multiple items to any day
- Edit existing items inline in the same window
- Remove items inline in the same window
- Stores data in `calendar_items.json` in the project directory
- No popup dialogs required for item view/edit flows

## Install (One Click)

### Windows

1. Double-click `Install Calendar App.bat`.
2. After installation finishes, double-click `Run Calendar App.bat`.
3. The launcher activates `.venv` automatically and deactivates it when the app closes.

### macOS

1. Double-click `Install Calendar App.command`.
2. After installation finishes, double-click `Run Calendar App.command`.
3. If macOS blocks double-click execution, run this once in Terminal from the project folder:
   - `chmod +x "Install Calendar App.command" "Run Calendar App.command"`
   - then run `./Install\ Calendar\ App.command`
4. The launcher activates `.venv` automatically and deactivates it when the app closes.

## Run (Manual)

```powershell
py -3 -m pip install -r requirements.txt
py -3 calendar_app.py
```

```bash
python3 -m pip install -r requirements.txt
python3 calendar_app.py
```

## Notes

- Click a day on the month grid to load its items.
- Use the right-side `View / Edit Item` section to add or update items.
- Item count for each day is shown on the day button as `(count)`.
- Use `Moodle Import` to crawl a Moodle URL and auto-import homework, quiz, and test dates.
- Imported homework links prefer assignment submission pages, and imported quiz/test links prefer their activity module pages.
- Imported homework titles include course/class context (for example `[Course] Assignment ...`) to reduce ambiguity.
- If the Moodle page requires authentication, enter username/password in the same panel and import again.
- For external SSO (for example Microsoft login), install Selenium once (`py -3 -m pip install selenium`) so the app can automate sign-in and import dates.
- During Microsoft SSO, the app waits up to 60 seconds for username correction, 60 seconds for password correction, and then 60 seconds for phone-based MFA approval.
- Import/data errors open in a resizable window that can be closed at any time.
