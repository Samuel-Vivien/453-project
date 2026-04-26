# TEST-RESULTS.md

Date: 2026-04-26
Commit SHA tested locally: 75b0038
Pipeline link or screenshot: Pending first GitHub Actions run on `test_integration`

Unit test count: 8
Integration test count: 1
E2E / golden path test count: 1

Coverage percentage: 22.35%
Coverage command used:

```powershell
python -m pytest tests/unit tests/integration --cov=calendar_app --cov=moodle_crawler --cov-report=term --cov-report=html
```

Known skipped tests: None
Known flaky tests: None
Manual fallback used: No

Local result summary:

```text
ruff check calendar_app.py moodle_crawler.py tests: passed
ruff format --check tests: passed
pytest tests/unit -q: 8 passed
pytest tests/integration -q: 1 passed
pytest tests/unit tests/integration --cov=calendar_app --cov=moodle_crawler --cov-report=term --cov-report=html: 9 passed, 22.35% coverage
pytest tests/e2e -q: 1 passed
```

Note: Local pytest runs reported a `.pytest_cache` write warning because this sandbox blocked cache-file creation. Test execution and results were unaffected.

Biggest testing win: The Moodle assignment parsing path is tested through calendar import storage without needing a live Moodle server.
Biggest remaining testing gap: The Tkinter widgets are not GUI-automated; the CI golden path uses the headless smoke command instead.
