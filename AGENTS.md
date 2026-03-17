# AGENTS.md - apple-git Development Guide

This file provides guidelines for agentic coding agents working on the apple-git codebase.

## Project Overview

apple-git bridges Apple Reminders to GitHub Issues and Pull Requests. It polls a configured Reminders list and syncs tasks to GitHub issues, supporting a kanban-style workflow with sections for "issue-ready", "review", and "done".

## Build/Lint/Test Commands

### Installation
```bash
pip install -e ".[dev]"
```

### Running the Application
```bash
python -m apple_git
# or
apple-git
```

### Linting
```bash
# Run ruff linter
ruff check .

# Auto-fix linting issues
ruff check --fix .
```

### Testing
```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_filename.py

# Run a single test function
pytest tests/test_filename.py::test_function_name

# Run tests matching a pattern
pytest -k "test_pattern"

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src --cov-report=term-missing
```

## Code Style Guidelines

### Imports
- Always use `from __future__ import annotations` at the top of files
- Use relative imports for internal modules: `from . import module`
- Group imports in this order: stdlib, third-party, local
- Use blank lines between groups

```python
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from github import Github

from . import config, github, reminders, store
```

### Types
- Use Python 3.11+ type hints throughout
- Use `X | None` syntax (not `Optional[X]`)
- Use `dict[str, Any]` for untyped dictionaries
- Prefer explicit return types on all functions/methods
- Use `@dataclass` for simple data containers

```python
def fetch_all(self) -> list[Reminder]:
    ...

def get_settings(config_path: Path | None = None) -> AppleGitSettings:
    ...
```

### Naming Conventions
- **Classes**: PascalCase (e.g., `GitHubClient`, `RemindersSettings`)
- **Functions/variables**: snake_case (e.g., `fetch_all`, `db_path`)
- **Constants**: SCREAMING_SNAKE_CASE (e.g., `REMINDERS_APP_TARGET`)
- **Private methods**: prefix with underscore (e.g., `_resolve_list_selector`)
- **Module names**: snake_case (e.g., `apple_tools.py`)

### Dataclasses
Use `@dataclass` for simple data containers:

```python
@dataclass
class Reminder:
    id: str
    name: str
    body: str
    section_name: str
    list_name: str
    creation_date: str
    due_date: str
```

### Pydantic Settings
Use Pydantic for configuration with `BaseSettings`:

```python
class GitHubSettings(BaseSettings):
    token: str = ""
    repo: str = ""

class AppleGitSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="apple_git_",
        extra="ignore",
        env_file=".env",
    )

    github: GitHubSettings = Field(default_factory=GitHubSettings)
```

### Error Handling
- Use logging for errors and warnings
- Return `None` or `False` on failure rather than raising exceptions in client methods
- Use try/except with specific exception types
- Log exceptions with `logger.exception()` for tracebacks

```python
try:
    result = subprocess.run(...)
    if result.returncode != 0:
        logger.warning("Failed to fetch reminders: %s", result.stderr)
        return []
    return self._parse_output(result.stdout)
except subprocess.TimeoutExpired:
    logger.warning("Timed out fetching reminders")
    return []
except FileNotFoundError:
    logger.error("osascript not found - requires macOS")
    return []
except Exception as exc:
    logger.warning("Error fetching reminders: %s", exc)
    return []
```

### Logging
- Use module-level loggers with `__name__`
- Use appropriate log levels: `debug`, `info`, `warning`, `error`, `exception`

```python
logger = logging.getLogger("apple_git.github")

logger.info("Created issue #%d: %s", issue.number, title)
logger.warning("Unable to resolve Reminders selector %r", self.list_name)
logger.error("Failed to create issue: %s", exc)
```

### Thread Safety
- Use `threading.Lock()` for shared state (see `SQLiteStore`)
- Always acquire locks before accessing shared resources

```python
class SQLiteStore:
    def __init__(self, db_path: Path):
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            ...
```

### Configuration
- Configuration is loaded from `config/config.yaml`
- Environment variables are prefixed with `apple_git_`
- Use `.env.example` to document required variables

### File Structure
```
src/apple_git/
    __init__.py       # Package init, version
    __main__.py       # CLI entry point
    config.py         # Pydantic settings
    github.py         # GitHub API client
    reminders.py      # Apple Reminders client
    store.py          # SQLite persistence
    notes.py          # Apple Notes client (optional)
    apple_tools.py    # AppleScript utilities
tests/                # Test files (when added)
config/
    config.yaml       # Configuration file
```

### Running Subprocesses
- Always set timeouts on subprocess calls
- Use `capture_output=True` and `text=True`
- Handle specific exceptions: `TimeoutExpired`, `FileNotFoundError`

```python
result = subprocess.run(
    ["osascript", "-e", script],
    capture_output=True,
    text=True,
    timeout=30,
)
```

### File Paths
- Use `pathlib.Path` for file paths
- Handle both absolute and relative paths
- Use `Path.home()` for user directory paths

```python
db_path: Path = Path.home() / ".apple-git" / "apple_git.sqlite"
```

### Constants
- Define constants as module-level variables in SCREAMING_SNAKE_CASE
- Use descriptive names that indicate purpose

```python
REMINDERS_APP_TARGET = 'application id "com.apple.reminders"'
```
