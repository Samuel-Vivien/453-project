# TESTING.md

## P#12 Desktop App Testing Procedure

This document explains how to run the automated testing process for the desktop application, how the tests are expected to behave, and how the testing procedure maps to the P#12 QA milestone requirements.

Primary product type: **Desktop App**

Recommended stack:

- Python
- pytest
- pytest-cov
- ruff
- pytest-qt, if the app uses PySide/PyQt/Qt and GUI automation is feasible
- GitHub Actions or GitLab CI for automated testing on push or merge request

---

## 1. Testing Goals

The goal of P#12 testing is to prove that the desktop application can be checked consistently and automatically after changes are made.

The testing process should verify:

1. Important non-UI logic works correctly.
2. The main user workflow, also called the **golden path**, still works.
3. Tests run locally and in CI.
4. Coverage results are generated and documented.
5. The team can explain what is automated, what is manual, and why.

---

## 2. Expected Project Structure

Recommended testing layout:

```text
your-repo/
  src/
    yourapp/
      __init__.py
      main.py
      services/
      ui/
  tests/
    unit/
    integration/
    e2e/
  pyproject.toml
  requirements.txt
  requirements-dev.txt
  TESTING.md
  TEST-RESULTS.md
  README.md
```

Replace `yourapp` with the actual Python package name used by the project.

---

## 3. Prerequisites

Before running tests, make sure the following are installed:

- Python 3.11 or 3.12
- pip
- Project dependencies
- Development/testing dependencies

If the app uses Qt/PySide/PyQt, GUI tests may also require additional display libraries on Linux or WSL.

---

## 4. Environment Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Activate it on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install project dependencies:

```bash
python -m pip install -U pip
python -m pip install -r requirements.txt
```

Install testing/development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

If `requirements-dev.txt` does not exist yet, create one with dependencies such as:

```text
pytest
pytest-cov
ruff
pytest-qt
```

Only include `pytest-qt` if the application uses Qt, PySide, or PyQt.

---

## 5. Unit Testing Procedure

Unit tests should focus on meaningful application logic rather than only checking that files import successfully.

Recommended areas to test:

- Business rules
- Validation logic
- Calculations
- File input/output helpers
- Data parsing
- Services
- Controllers or view-models
- Database adapters, using temporary test databases where possible

Run unit tests:

```bash
pytest tests/unit -q
```

Expected result:

```text
All unit tests should pass.
No test should depend on a developer's local machine state.
No test should require manual clicking or opening the full desktop UI.
```

---

## 6. Integration Testing Procedure

Integration tests should verify that multiple parts of the app work together.

Examples:

- Service plus database adapter
- File loader plus parser
- Controller plus mocked service
- CLI smoke test
- App startup check without full GUI automation

Run integration tests:

```bash
pytest tests/integration -q
```

Expected result:

```text
Integration tests should pass consistently.
Temporary files should use pytest fixtures such as tmp_path.
External services should be mocked unless specifically required.
```

---

## 7. Coverage Procedure

Coverage should be measured with `pytest-cov`.

Run coverage:

```bash
pytest tests/unit tests/integration --cov=yourapp --cov-report=term --cov-report=html
```

Replace `yourapp` with the actual package name.

Expected result:

```text
Coverage should be generated in the terminal.
An HTML coverage report should be created in htmlcov/.
Coverage should meet the threshold documented by the team.
```

Recommended starting threshold:

```text
70% line coverage
```

A lower threshold is acceptable only if the team documents a clear reason in `TEST-RESULTS.md` and the P#12 report.

Suggested `pyproject.toml` configuration:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-ra -q --strict-markers"
markers = [
    "slow: marks tests as slow",
    "gui: marks tests that need a display",
]

[tool.coverage.run]
branch = true
source = ["yourapp"]
omit = ["*/tests/*", "*/__main__.py"]

[tool.coverage.report]
fail_under = 70
show_missing = true
```

---

## 8. Golden Path / E2E Testing Procedure

The project must include at least one test or approved fallback that proves the main P#10 user task still works.

This main user task is called the **golden path**.

Example golden path format:

```text
1. Start the desktop app.
2. Enter required user input.
3. Trigger the main action.
4. Confirm the expected result appears.
5. Confirm the app does not crash or show an invalid state.
```

---

## 9. Option A: Automated GUI E2E Test

Use this option if the desktop app uses Qt, PySide, or PyQt and can be tested through stable widgets.

Recommended tool:

```text
pytest-qt
```

Run GUI/E2E tests locally:

```bash
pytest tests/e2e -m gui -v
```

Expected result:

```text
The E2E test should launch the relevant window or dialog.
The test should perform the golden path actions.
The test should assert that the expected output or UI state appears.
The test should pass without manual interaction.
```

For Linux CI, run with Xvfb:

```bash
xvfb-run -a pytest tests/e2e -m gui -v
```

Recommended GUI testing practices:

- Set stable `objectName` values on important widgets.
- Avoid pixel-based assertions.
- Test labels, model state, saved files, or service results.
- Keep GUI tests limited to the most important workflows.

---

## 10. Option B: Headless Golden Path / CLI Smoke Test

Use this option if the app can expose a command that runs the core workflow without opening the full GUI.

Example command:

```bash
python -m yourapp --smoke-test
```

A test can call this command using `subprocess` and assert that it exits successfully.

Expected result:

```text
The smoke command should complete with exit code 0.
The command should exercise the same core logic as the main user workflow.
The result should be checked automatically in CI.
```

---

## 11. Option C: Approved Manual Fallback

Use this only if GUI automation is not feasible.

Valid reasons may include:

- The app requires hardware not available in CI.
- The app is Windows-only and no Windows runner is available.
- GUI automation is unstable or unsupported for the current framework.
- The workflow depends on a manual operating system interaction that cannot be automated reasonably.

If using this fallback, the team must provide:

1. A numbered manual smoke checklist.
2. A short screen recording of the golden path.
3. A clear explanation in `TESTING.md`, `TEST-RESULTS.md`, and the P#12 report.
4. A rule for when the checklist must be run, such as before merging to `main`.

Manual smoke checklist template:

```text
Manual Golden Path Smoke Test

Date performed:
Tester:
Commit SHA:
Operating system:

Steps:
1. Launch the application.
2. Navigate to the main workflow.
3. Enter test input: [...]
4. Click or trigger: [...]
5. Confirm expected output: [...]
6. Confirm no crash or error state occurs.

Result:
Pass / Fail

Recording link or file path:
[Insert link]
```

Expected result:

```text
The fallback should be structured and repeatable.
It should not simply say "we tested manually."
It should provide evidence that the golden path was checked.
```

---

## 12. Linting Procedure

Use `ruff` to check code quality.

Run linting:

```bash
ruff check src tests
```

Check formatting:

```bash
ruff format --check src tests
```

Expected result:

```text
No linting errors should remain before merging.
Formatting should be consistent across source and test files.
```

---

## 13. Full Local Test Procedure

Run the following before opening or merging a pull request / merge request:

```bash
ruff check src tests
ruff format --check src tests
pytest tests/unit -q
pytest tests/integration -q
pytest tests/unit tests/integration --cov=yourapp --cov-report=term --cov-report=html
pytest tests/e2e -m gui -v
```

If GUI automation is not available, replace the final command with the approved manual smoke checklist.

Expected result:

```text
Lint checks pass.
Unit tests pass.
Integration tests pass.
Coverage is generated and meets the documented threshold.
Golden path test passes, or approved manual fallback evidence is recorded.
```

---

## 14. CI Testing Procedure

CI should run automatically on every push or merge request.

Minimum expected CI jobs:

```text
1. Install dependencies
2. Run linting
3. Run unit tests
4. Generate coverage report
5. Run E2E or golden path test if feasible
```

Expected CI behavior:

```text
Unit test failures should fail the pipeline.
Coverage results should be saved as an artifact if supported.
GUI/E2E tests should run in CI if feasible.
If GUI/E2E cannot run in CI, the reason must be documented.
```

Suggested GitLab CI flow:

```text
lint -> unit_tests -> gui_tests -> package_smoke
```

Suggested GitHub Actions flow:

```text
checkout -> setup Python -> install dependencies -> lint -> pytest coverage -> optional xvfb GUI tests
```

---

## 15. Expected CI Evidence

For P#12 submission, provide one of the following:

- Link to a recent green CI pipeline
- Screenshot of a passing CI run
- Screenshot of terminal output if CI is not available, with explanation

The evidence should show:

```text
Unit tests ran.
Coverage was generated.
The golden path was tested or fallback was documented.
```

---

## 16. TEST-RESULTS.md Expectations

Create a separate `TEST-RESULTS.md` file with the following information:

```text
Date:
Commit SHA:
Pipeline link or screenshot:

Unit test count:
Integration test count:
E2E / golden path test count:

Coverage percentage:
Coverage command used:

Known skipped tests:
Known flaky tests:
Manual fallback used: Yes / No

Biggest testing win:
Biggest remaining testing gap:
```

---

## 17. README Testing Section

The `README.md` file should include a short Testing section with copy-paste commands.

Suggested README section:

```md
## Testing

Install development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run unit tests:

```bash
pytest tests/unit -q
```

Run coverage:

```bash
pytest tests/unit tests/integration --cov=yourapp --cov-report=term --cov-report=html
```

Run golden path / GUI tests:

```bash
pytest tests/e2e -m gui -v
```

See `TESTING.md` for the full testing procedure.
```

---

## 18. Troubleshooting

### Problem: `ImportError: No module named yourapp`

Fix:

```bash
export PYTHONPATH=src
```

Or install the package in editable mode:

```bash
python -m pip install -e .
```

---

### Problem: Qt tests fail with display errors on Linux

Fix:

```bash
xvfb-run -a pytest tests/e2e -m gui -v
```

Also confirm required Linux libraries are installed in CI.

---

### Problem: Coverage shows 0%

Fix:

Check that the package name in the coverage command matches the actual app package:

```bash
pytest --cov=yourapp
```

Replace `yourapp` with the real package name.

---

### Problem: Tests pass locally but fail in CI

Fix:

- Pin dependency versions.
- Confirm the same Python version is used locally and in CI.
- Avoid tests that depend on local files outside the repo.
- Use `tmp_path` for temporary file testing.

---

## 19. Completion Checklist

Use this checklist before submitting P#12:

```text
[ ] Unit tests exist under tests/unit/
[ ] Unit tests contain meaningful assertions
[ ] Integration tests exist if needed
[ ] Coverage is generated with pytest-cov
[ ] Coverage threshold is documented
[ ] Golden path is automated or fallback is documented
[ ] CI runs tests on push or merge request
[ ] CI failure blocks merging or is clearly explained
[ ] TESTING.md is complete
[ ] TEST-RESULTS.md is complete
[ ] README has a Testing section
[ ] P#12 report includes test inventory, CI evidence, and results summary
```

---

## 20. Final Expected Submission Evidence

For a strong P#12 desktop app submission, the repository should include:

```text
tests/unit/
tests/integration/ if applicable
tests/e2e/ or documented fallback
pyproject.toml or pytest.ini coverage configuration
.gitlab-ci.yml or .github/workflows/ci.yml
TESTING.md
TEST-RESULTS.md
README.md Testing section
Completed P#12 report PDF
Recent green pipeline link or screenshot
```

