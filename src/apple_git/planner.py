"""CLI-backed issue planning."""
from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger("apple_git.planner")

_BACKEND_ALIASES: dict[str, str] = {
    "claude_cli": "claude",
    "codex_cli": "codex",
    "kilo_cli": "kilo",
}
_SUPPORTED_BACKENDS = {"claude", "codex", "kilo"}


class IssuePlanner:
    """Generate a structured implementation plan through a configured CLI backend."""

    def __init__(self, *, backend: str, command: str = "", model: str = "") -> None:
        normalized = _BACKEND_ALIASES.get((backend or "").strip().lower(), (backend or "").strip().lower())
        if normalized not in _SUPPORTED_BACKENDS:
            raise ValueError(f"Unsupported planner backend: {backend}")
        self.backend = normalized
        self.command = (command or normalized).strip() or normalized
        self.model = (model or "").strip()

    def is_available(self) -> bool:
        return bool(shutil.which(self.command))

    def plan(self, *, prompt: str) -> str:
        """Return a structured implementation plan or an empty string on failure."""
        if not self.is_available():
            logger.warning("Planner backend %s is not available on PATH", self.backend)
            return ""

        cmd, uses_stdin = self._build_command(prompt)
        try:
            result = subprocess.run(
                cmd,
                input=prompt if uses_stdin else None,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Timed out generating implementation plan via %s", self.backend)
            return ""
        except FileNotFoundError:
            logger.warning("Planner command not found: %s", self.command)
            return ""
        except Exception as exc:
            logger.warning("Failed to generate implementation plan via %s: %s", self.backend, exc)
            return ""

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            logger.warning(
                "Planner backend %s failed with exit code %s: %s",
                self.backend,
                result.returncode,
                stderr or "no stderr",
            )
            return ""
        return (result.stdout or "").strip()

    def _build_command(self, prompt: str) -> tuple[list[str], bool]:
        if self.backend == "codex":
            cmd = [self.command, "exec", "--yolo", "--skip-git-repo-check"]
            if self.model:
                cmd.extend(["-m", self.model])
            return cmd, True

        if self.backend == "kilo":
            cmd = [self.command, "run", "--auto"]
            if self.model:
                cmd.extend(["--model", self.model])
            return cmd, True

        cmd = [self.command, "--dangerously-skip-permissions"]
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.extend(["-p", prompt])
        return cmd, False


def build_issue_planner(*, backend: str, model: str = "", command: str = "") -> IssuePlanner | None:
    normalized = _BACKEND_ALIASES.get((backend or "").strip().lower(), (backend or "").strip().lower())
    if normalized not in _SUPPORTED_BACKENDS:
        logger.warning("Unsupported planner backend requested: %s", backend)
        return None

    planner = IssuePlanner(backend=normalized, model=model, command=command or normalized)
    if not planner.is_available():
        logger.warning("Planner backend %s is unavailable", normalized)
        return None
    return planner
