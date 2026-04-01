# Desktop Calendar App

Single-window desktop calendar built with Python + Tkinter.

## Features

- Add multiple items to any day
- Edit existing items inline in the same window
- Remove items inline in the same window
- Stores data in `calendar_items.json` in the project directory
- No popup dialogs required for item view/edit flows
- While the app is open, shows a popup and plays a sound every other day leading up to the next due date

## Install (One Click)

### Windows

1. Double-click `Install Calendar App.bat`.
2. After installation finishes, double-click `Run Calendar App.bat`.
3. The launcher activates `.venv` automatically and deactivates it when the app closes.

### macOS

1. Double-click `Install Calendar App.command`.
2. After installation finishes, double-click `Run Calendar App.command`.
3. If macOS blocks the installer the first time, use `Right-click -> Open` on `Install Calendar App.command` once, or click `Open Anyway` in `Privacy & Security`.
4. After that first approved run, the installer clears macOS quarantine from the project so future double-click launches work normally.
5. If Terminal is still needed, run this once from the project folder:
   - `chmod +x "Install Calendar App.command" "Run Calendar App.command" "Uninstall Calendar App.command"`
   - then run `./Install\ Calendar\ App.command`
6. The launcher activates `.venv` automatically and deactivates it when the app closes.

### Linux

1. Run `chmod +x "Install Calendar App.sh" "Run Calendar App.sh" "Uninstall Calendar App.sh"` once from the project folder if your desktop does not preserve executable permissions.
2. Start the installer with `./Install\ Calendar\ App.sh`.
3. After installation finishes, run `./Run\ Calendar\ App.sh` or double-click `Run Calendar App.sh` from your file manager.
4. On supported distros, the installer automatically uses `apt-get`, `dnf`, `yum`, or `pacman` to install missing Python 3 / Tkinter / venv system packages.
5. The launcher uses the project `.venv` automatically.

## Uninstall (One Click)

### Windows

1. Double-click `Uninstall Calendar App.bat`.
2. It removes `.venv` and Python cache files.
3. It asks whether to also delete `calendar_items.json`.

### macOS

1. Double-click `Uninstall Calendar App.command`.
2. It removes `.venv` and Python cache files.
3. It asks whether to also delete `calendar_items.json`.

### Linux

1. Run `./Uninstall\ Calendar\ App.sh`.
2. It removes `.venv` and Python cache files.
3. It asks whether to also delete `calendar_items.json`.

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
- Use `Moodle Import` to crawl a Moodle URL and auto-import homework/assignment due dates.
- Imported homework items are only added when a valid assignment submission page link is found.
- macOS SSL certificate validation for Moodle imports uses the bundled `certifi` CA store installed by the app installer.
- Imported homework titles include course/class context (for example `[Course] Assignment ...`) to reduce ambiguity.
- If the Moodle page requires authentication, enter username/password in the same panel and import again.
- For external SSO (for example Microsoft login), install Selenium once (`py -3 -m pip install selenium`) so the app can automate sign-in and import dates.
- For external SSO browser automation, the app tries the user's system default browser first, then falls back to Safari on macOS or Edge on Windows.
- On Linux, Tkinter may come from a distro package instead of pip; the Linux installer attempts to add it automatically on supported package managers.
- During Microsoft SSO, the app waits up to 60 seconds for username correction, 60 seconds for password correction, and then 60 seconds for phone-based MFA approval.
- Import/data errors open in a resizable window that can be closed at any time.
