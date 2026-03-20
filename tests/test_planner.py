from __future__ import annotations

import subprocess
from unittest.mock import patch

from apple_git.planner import IssuePlanner


def test_codex_issue_planner_returns_stdout_text():
    planner = IssuePlanner(backend="codex", command="codex", model="gpt-5.4-mini")
    completed = subprocess.CompletedProcess(
        args=["codex"],
        returncode=0,
        stdout="## Problem\nPlanned work\n",
        stderr="",
    )

    with (
        patch.object(planner, "is_available", return_value=True),
        patch("apple_git.planner.subprocess.run", return_value=completed) as mock_run,
    ):
        result = planner.plan(prompt="Plan this")

    assert result == "## Problem\nPlanned work"
    mock_run.assert_called_once()
