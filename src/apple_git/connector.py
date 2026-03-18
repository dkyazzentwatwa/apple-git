"""CLI connector abstraction for spawning AI coding agents in the background."""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ConnectorProtocol(Protocol):
    def spawn(self, prompt: str, cwd: Path) -> subprocess.Popen: ...
    def is_available(self) -> bool: ...
    @property
    def backend_name(self) -> str: ...


class ClaudeCliConnector:
    """Spawns `claude -p <prompt>` as a background process."""

    backend_name = "claude"

    def __init__(
        self,
        *,
        command: str = "claude",
        model: str = "claude-haiku-4-5-20251001",
        dangerously_skip_permissions: bool = True,
    ) -> None:
        self.command = (command or "claude").strip() or "claude"
        self.model = (model or "").strip()
        self.dangerously_skip_permissions = dangerously_skip_permissions
        self._lock = threading.Lock()
        self._resolved: str = ""
        self._available: bool = False
        self._reason: str = ""
        self._last_check_at: float = 0.0
        self._resolve()

    def is_available(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._available and now - self._last_check_at < 30:
                return True
        self._resolve()
        with self._lock:
            return self._available

    def spawn(self, prompt: str, cwd: Path) -> subprocess.Popen:
        with self._lock:
            resolved = self._resolved
        cmd = [resolved]
        if self.dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        if self.model:
            cmd.extend(["--model", self.model])
        cmd.extend(["-p", prompt])
        return subprocess.Popen(cmd, cwd=str(cwd), start_new_session=True)

    def _resolve(self) -> None:
        resolved = shutil.which(self.command) or ""
        now = time.monotonic()
        with self._lock:
            self._resolved = resolved
            self._available = bool(resolved)
            self._reason = "" if resolved else f"Unable to resolve command '{self.command}'"
            self._last_check_at = now


class CodexCliConnector:
    """Spawns `codex exec` with prompt on stdin as a background process."""

    backend_name = "codex"

    def __init__(
        self,
        *,
        command: str = "codex",
        model: str = "",
        reasoning_effort: str = "",
    ) -> None:
        self.command = (command or "codex").strip() or "codex"
        self.model = (model or "").strip()
        self.reasoning_effort = (reasoning_effort or "").strip().lower()
        self._lock = threading.Lock()
        self._resolved: str = ""
        self._available: bool = False
        self._reason: str = ""
        self._last_check_at: float = 0.0
        self._resolve()

    def is_available(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._available and now - self._last_check_at < 30:
                return True
        self._resolve()
        with self._lock:
            return self._available

    def spawn(self, prompt: str, cwd: Path) -> subprocess.Popen:
        with self._lock:
            resolved = self._resolved
        cmd = [resolved, "exec", "--yolo", "--skip-git-repo-check"]
        if self.model:
            cmd.extend(["-m", self.model])
        if self.reasoning_effort:
            cmd.extend(["-c", f'model_reasoning_effort="{self.reasoning_effort}"'])
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            cwd=str(cwd),
            start_new_session=True,
        )
        if proc.stdin:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()
        return proc

    def _resolve(self) -> None:
        resolved = shutil.which(self.command) or ""
        now = time.monotonic()
        with self._lock:
            self._resolved = resolved
            self._available = bool(resolved)
            self._reason = "" if resolved else f"Unable to resolve command '{self.command}'"
            self._last_check_at = now


class KiloCliConnector:
    """Spawns `kilo run --auto` with prompt on stdin as a background process."""

    backend_name = "kilo"

    def __init__(
        self,
        *,
        command: str = "kilo",
        model: str = "",
    ) -> None:
        self.command = (command or "kilo").strip() or "kilo"
        self.model = (model or "").strip()
        self._lock = threading.Lock()
        self._resolved: str = ""
        self._available: bool = False
        self._reason: str = ""
        self._last_check_at: float = 0.0
        self._resolve()

    def is_available(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._available and now - self._last_check_at < 30:
                return True
        self._resolve()
        with self._lock:
            return self._available

    def spawn(self, prompt: str, cwd: Path) -> subprocess.Popen:
        with self._lock:
            resolved = self._resolved
        cmd = [resolved, "run", "--auto"]
        if self.model:
            cmd.extend(["--model", self.model])
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            cwd=str(cwd),
            start_new_session=True,
        )
        if proc.stdin:
            proc.stdin.write(prompt.encode())
            proc.stdin.close()
        return proc

    def _resolve(self) -> None:
        resolved = shutil.which(self.command) or ""
        now = time.monotonic()
        with self._lock:
            self._resolved = resolved
            self._available = bool(resolved)
            self._reason = "" if resolved else f"Unable to resolve command '{self.command}'"
            self._last_check_at = now


_BACKEND_ALIASES: dict[str, str] = {
    "claude_cli": "claude",
    "kilo_cli": "kilo",
    "codex_cli": "codex",
}

_SUPPORTED_BACKENDS = {"claude", "codex", "kilo"}


def build_connector(
    backend: str,
    *,
    model: str = "",
    command: str = "",
) -> ClaudeCliConnector | CodexCliConnector | KiloCliConnector:
    """Factory: instantiate the right connector for the given backend name."""
    normalized = _BACKEND_ALIASES.get(backend, backend).lower()
    if normalized == "codex":
        return CodexCliConnector(command=command or "codex", model=model)
    if normalized == "kilo":
        return KiloCliConnector(command=command or "kilo", model=model)
    # Default: claude
    return ClaudeCliConnector(command=command or "claude", model=model or "claude-haiku-4-5-20251001")
