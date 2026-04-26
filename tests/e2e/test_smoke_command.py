from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_headless_golden_path_smoke_command() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [sys.executable, "calendar_app.py", "--smoke-test"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Smoke test passed" in completed.stdout


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__]))
