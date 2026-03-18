# GEMINI.md - apple-git Instructional Context

This file provides a comprehensive overview of the `apple-git` project, its architecture, development conventions, and operational procedures to serve as a guide for future interactions.

## Project Overview

**apple-git** is a macOS automation tool that bridges Apple Reminders to GitHub Issues and Pull Requests. it implements an agentic software development workflow where Apple Reminders act as a Kanban board.

### Core Workflow
1.  **Backlog/Ready:** Reminders in the "issue-ready" list trigger the creation of a GitHub issue.
2.  **In Progress:** The system spawns an AI coding agent (e.g., Claude CLI, Codex, or Kilo) to work on the issue in a dedicated branch.
3.  **Review:** Moving a reminder to the "review" list triggers PR creation and AI-powered code/security reviews using the Anthropic API.
4.  **Done:** Moving a reminder to the "done" list triggers PR merging, branch deletion, and GitHub issue closure.

### Key Technologies
- **Language:** Python 3.11+
- **Integrations:**
    - **Apple Reminders:** Controlled via AppleScript (`osascript`).
    - **GitHub:** Managed via the `PyGithub` library.
    - **AI Agents:** Spawns external CLIs like `claude`, `codex`, or `kilo`.
    - **AI Reviews:** Uses the `anthropic` Python SDK for analysis and PR reviews.
- **Persistence:** SQLite for mapping Reminders to GitHub entities.
- **Configuration:** Pydantic Settings for type-safe configuration via `.env` or YAML.

---

## Architecture

The project follows a modular architecture with specialized clients orchestrated by a central application loop.

### Core Components
- **`AppleGit` (Orchestrator):** The main polling loop in `src/apple_git/__main__.py` that manages state transitions.
- **`RemindersClient`:** Interfaces with macOS Reminders via AppleScript.
- **`GitHubClient`:** Interfaces with the GitHub API.
- **`Connector`:** An abstraction for spawning background AI coding processes.
- **`SQLiteStore`:** Persists mappings between reminder IDs and GitHub issue/PR numbers.
- **AI Reviewers:** Specialized classes for issue analysis, code review, and security audits.

---

## Building and Running

### Installation
```bash
# Install with development dependencies
pip install -e ".[dev]"
```

### Configuration
1.  Copy `.env.example` to `.env` and fill in:
    - `GITHUB_TOKEN`: Your GitHub personal access token.
    - `APPLE_GIT_GITHUB_REPO`: The `owner/repo` string.
    - `ANTHROPIC_API_KEY`: Required for AI analysis and reviews.
2.  Adjust `config/config.yaml` for specific list names or polling intervals.

### Running
```bash
# Run as a module
python3 -m apple_git

# Or use the installed script
apple-git
```

### macOS Daemon
A `launchd` plist is provided in `scripts/local.apple-git.plist` to run the tool as a background daemon on macOS.

---

## Development Conventions

### Coding Style
- **Type Hints:** Required for all functions (Python 3.11+ syntax, e.g., `str | None`).
- **Imports:** Always use `from __future__ import annotations`. Use relative imports for internal modules.
- **Linting:** Use `ruff` for formatting and linting.
- **Error Handling:** Clients should return `None` or `False` rather than raising exceptions for expected failures (e.g., API errors).

### Key Commands
- **Linting:** `ruff check .` (use `--fix` for auto-fixing).
- **Testing:** `pytest` (Tests are located in `tests/`, though currently minimal).

### File Structure
- `src/apple_git/__main__.py`: Entry point and orchestration logic.
- `src/apple_git/reminders.py`: AppleScript-based Reminders integration.
- `src/apple_git/github.py`: GitHub API wrapper.
- `src/apple_git/connector.py`: Logic for spawning AI coding agents.
- `src/apple_git/config.py`: Configuration management.
- `src/apple_git/store.py`: SQLite persistence layer.

---

## Operational Notes
- **macOS Only:** The tool relies on AppleScript and specifically targets the macOS Reminders app.
- **Permissions:** Requires "Automation" permissions for Reminders and potentially "Full Disk Access" or terminal permissions depending on the AI connector used.
- **AI Connectors:** Ensure the chosen CLI (e.g., `claude`) is installed and available in your `PATH`.
