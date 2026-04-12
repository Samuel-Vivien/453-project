How to use:
Step 1. Proceed to the release Branch
Step 2. Open the Release folder.
Step 3. Download attributed install folder for specified OS
Step 4. Unzip the folders
Step 5. Open the Desktop Calendar (insert_OS) folder
Step 6 (Windows): Run the 'Install Dekstop Calendar.batch' file. Then wait for the install to complete and then run the 'Run Desktop Calendar' file.
Step 6 (MacOS): Run the 'Install Dekstop Calendar.command' file. Mac OS will then warn user of potential virus, ignore this and go into your settings and in settings go to security. Scroll down until you see the file it blocked and click 'run anyway'. Then wait for the install to complete and then run the 'Run Desktop Calendar' file. (May need to proceed to settings again due to MacOS)
Step 6 (Linux): using the terminal cd into the location of the 'Install Desktop Calendar.sh' and then run './'Install Desktop Calendar.sh''. Once install is complete, run the 'Run Desktop Calendar' file.

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
- For a fresh machine with no Python installed, Windows and macOS use the official `python.org` installers, while Linux uses the distro package manager when supported.
- Standalone student releases built with `build_student_release.py` do not require Python on the student's machine.
- On Linux, Tkinter may come from a distro package instead of pip; the Linux installer attempts to add it automatically on supported package managers.
- Packaged builds store `calendar_items.json` in the user's profile instead of beside the executable so updates are safer.
- During Microsoft SSO, the app waits up to 60 seconds for username correction, 60 seconds for password correction, and then 60 seconds for phone-based MFA approval.
- Import/data errors open in a resizable window that can be closed at any time.
