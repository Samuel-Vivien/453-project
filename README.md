# Desktop Calendar App

Single-window desktop calendar built with Python + Tkinter.

## Features

- Add multiple items to any day
- Edit existing items inline in the same window
- Remove items inline in the same window
- Stores data in `calendar_items.json` in the project directory
- No popup dialogs required for item view/edit flows

## Install (One Click)

1. Double-click `Install Calendar App.bat`.
2. After installation finishes, double-click `Run Calendar App.bat`.

## Run (Manual)

```powershell
py -3 -m pip install -r requirements.txt
py -3 calendar_app.py
```

## Notes

- Click a day on the month grid to load its items.
- Use the right-side `View / Edit Item` section to add or update items.
- Item count for each day is shown on the day button as `(count)`.
- Use `Moodle Import` to crawl a Moodle URL and auto-import homework, quiz, and test dates.
- If the Moodle page requires authentication, enter username/password in the same panel and import again.
- For external SSO (for example Microsoft login), install Selenium once (`py -3 -m pip install selenium`) so the app can automate sign-in and import dates.
- During Microsoft SSO, the app waits up to 60 seconds for username correction, 60 seconds for password correction, and then 60 seconds for phone-based MFA approval.
