# AGENTS.md - apple-git Development Guide

This file is the shared source of truth for coding agents working in this repository. Keep it concise, repo-specific, and aligned with the current codebase. Use `README.md` for user-facing setup and `docs/REMINDERS_SETUP.md` for the operator workflow in Apple Reminders.

## Project Overview

`apple-git` is a macOS automation tool that bridges Apple Reminders to GitHub Issues and Pull Requests.

The current workflow is:

- Reminders moved to `dev-issue-ready` create GitHub issues
- A configured connector backend (`claude`, `codex`, or `kilo`) is spawned to work on the issue branch
- Reminders moved to `dev-review` create or link pull requests
- Optional Anthropic-powered issue analysis, PR review, and security review can comment on the issue/PR
- Reminders moved to `dev-done` can merge the PR and close the issue
- SQLite stores reminder-to-issue / reminder-to-PR mappings

The main entry point is `src/apple_git/__main__.py`, where `AppleGit.process()` handles the polling loop and state transitions.

## Build, Lint, and Test

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
ruff check .
ruff check --fix .
```

### Testing
```bash
pytest
pytest tests/test_app.py
pytest tests/test_config.py
pytest tests/test_store.py
pytest tests/test_tree.py
pytest -k "process"
pytest -v
```

## Architecture

### Core Modules

- `src/apple_git/__main__.py`: orchestrator, polling loop, and reminder state transitions
- `src/apple_git/config.py`: Pydantic settings, `.env` loading, YAML loading, and env overrides
- `src/apple_git/reminders.py`: Apple Reminders integration via AppleScript
- `src/apple_git/github.py`: GitHub API wrapper built on PyGithub
- `src/apple_git/store.py`: SQLite persistence for reminder / issue / PR mappings
- `src/apple_git/connector.py`: connector abstraction for spawning `claude`, `codex`, or `kilo`
- `src/apple_git/issue_analyzer.py`: Anthropic-based issue analysis
- `src/apple_git/reviewer.py`: Anthropic-based PR review
- `src/apple_git/security_reviewer.py`: Anthropic-based security review
- `src/apple_git/setup.py`: setup helpers for local Apple Reminders configuration
- `src/apple_git/tree.py`: repository tree summarization used in connector prompts
- `src/apple_git/notes.py`: optional Apple Notes logging
- `src/apple_git/apple_tools.py`: AppleScript helpers

### Runtime Flow

`AppleGit.process()` currently works across multiple Reminders lists:

- `list_issue_ready`: create issues for unmapped reminders and spawn a connector
- `list_review`: create or link PRs for mapped reminders
- `list_done`: merge PRs when requested, close issues, and complete reminders

The default reminders settings are defined in `config.py`, `config/config.yaml`, and `config/config.yaml.example`. The shipped defaults are:

- `dev-backlog`
- `dev-issue-ready`
- `dev-review`
- `dev-done`

Do not document unsupported list names or stale states unless they are present in the code.

## Configuration

Configuration behavior must match `src/apple_git/config.py`.

### Sources

`AppleGitSettings` is loaded from:

1. Repo-root `.env`
2. `config/config.yaml`
3. Hardcoded defaults in `config.py`

### Important Settings

- `github.token`
- `github.repo`
- `reminders.list_inactive`
- `reminders.list_issue_ready`
- `reminders.list_review`
- `reminders.list_done`
- `notes.folder_name`
- `notes.log_enabled`
- `poll_interval_seconds`
- `db_path`
- `log_file`
- `repo_path`
- `anthropic_api_key`
- `enable_pr_review`
- `enable_security_review`
- `connector_backend`
- `connector_model`
- `connector_command`

### Environment Variables

- `APPLE_GIT_*` variables override root settings loaded through `AppleGitSettings`
- `GITHUB_TOKEN` is also read explicitly in `load_from_yaml()` and overrides YAML GitHub token values

When updating docs, keep these precedence rules aligned with the code instead of simplifying them into generic Pydantic guidance.

## Code Style Guidelines

### Imports

- Always use `from __future__ import annotations`
- Group imports as: stdlib, third-party, local
- Use blank lines between groups
- Prefer relative imports for internal modules

### Types

- Use Python 3.11+ type hints throughout
- Use `X | None` syntax
- Prefer explicit return types on functions and methods
- Use `@dataclass` for simple data containers
- Use `dict[str, Any]` for untyped dictionaries

### Naming

- Classes: PascalCase
- Functions and variables: snake_case
- Constants: SCREAMING_SNAKE_CASE
- Private helpers: leading underscore
- Module names: snake_case

### Error Handling

- Log expected operational failures instead of crashing clients
- In client-style integrations, prefer returning `None`, `False`, or an empty collection on failure
- Catch specific exceptions where practical
- Use `logger.exception()` when a traceback is useful

### Logging

- Use module-level loggers
- Use `debug`, `info`, `warning`, `error`, and `exception` appropriately
- Keep log messages concrete and operationally useful

### Thread Safety

- `SQLiteStore` uses `threading.Lock()` to protect shared DB access
- Preserve the locking behavior when changing store code

### Paths and Subprocesses

- Use `pathlib.Path` for file paths
- Keep subprocess calls bounded with explicit timeouts
- For AppleScript calls, use `capture_output=True` and `text=True`
- Handle `TimeoutExpired` and `FileNotFoundError` explicitly for subprocess-based integrations

## Testing Guidance

Tests already exist in `tests/`; do not describe the suite as missing or hypothetical.

When adding or changing tests:

- Mock AppleScript-backed integrations instead of depending on live Reminders or Notes access
- Mock GitHub and Anthropic integrations instead of requiring external network access
- Prefer focused unit tests around `AppleGit.process()`, config loading, store behavior, and tree generation
- Use in-memory or temporary-path SQLite setups where possible

Useful current test files:

- `tests/test_app.py`
- `tests/test_config.py`
- `tests/test_store.py`
- `tests/test_tree.py`

## Repo Guardrails For Agents

- This project is macOS-specific because Reminders and Notes integrations rely on AppleScript
- Keep repo documentation aligned with the actual code, not aspirational workflow ideas
- If `README.md` or `docs/REMINDERS_SETUP.md` contains deeper workflow/setup detail, reference it instead of duplicating large sections here
- Avoid introducing stale filenames, settings, or modules into agent-facing docs
- Do not assume live GitHub, Anthropic, or Apple app access during development or tests

## File Structure

```text
src/apple_git/
    __init__.py
    __main__.py
    apple_tools.py
    config.py
    connector.py
    github.py
    issue_analyzer.py
    notes.py
    reminders.py
    reviewer.py
    security_reviewer.py
    setup.py
    store.py
    tree.py
tests/
    test_app.py
    test_config.py
    test_store.py
    test_tree.py
config/
    config.yaml
    config.yaml.example
```
