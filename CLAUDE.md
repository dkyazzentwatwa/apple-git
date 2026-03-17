# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

See AGENTS.md for detailed build, test, and linting commands. Key commands:

```bash
# Install in development mode
pip install -e ".[dev]"

# Run the application
python -m apple_git

# Run tests
pytest

# Lint and fix
ruff check --fix .
```

## Project Overview

**apple-git** is a macOS automation tool that bridges Apple Reminders to GitHub Issues and Pull Requests. It enables a kanban-style workflow where:

- Reminders in a configured list are synced to GitHub issues
- Reminders in a "review" section are linked to pull requests
- Completed reminders can trigger PR merges and issue closures
- All mappings and state are persisted in SQLite

**Entry Point**: `src/apple_git/__main__.py` → `AppleGit.run_forever()` polling loop

## Architecture

### Core Components

The system is built around three main clients that communicate through a central orchestrator:

```
AppleGit (orchestrator)
├── RemindersClient (macOS Reminders via AppleScript)
├── GitHubClient (GitHub API via PyGithub)
├── SQLiteStore (state persistence)
└── NotesClient (Apple Notes, optional logging)
```

### Data Flow

1. **Polling Loop** (`AppleGit.run_forever()`):
   - Runs every N seconds (configurable via `poll_interval_seconds`)
   - Calls `process()` to sync state
   - Handles graceful shutdown via signal handlers

2. **State Synchronization** (`AppleGit.process()`):
   - Fetches all reminders from the configured Reminders list
   - For each reminder, checks its section and body tags:
     - **`#issue-ready`** or **issue-ready section**: Create GitHub issue if not mapped
     - **`#review`** or **review section**: Link a PR number if reminder body contains `#<pr_number>`
     - **`#issue-done`** or **issue-done section**: Close GitHub issue and optionally merge PR
   - Updates SQLite mappings as state changes

3. **Mapping Storage**:
   - `SQLiteStore.upsert_issue_mapping()` tracks: reminder ID → GitHub issue number → PR number
   - Sections are stored to detect user-initiated moves in Reminders
   - All operations are thread-safe (uses `threading.Lock()`)

### Key Classes

**`AppleGit`** (`__main__.py`):
- Orchestrates the sync loop
- Initializes all clients based on configuration
- Implements three state transitions: `_create_issue()`, `_handle_review()`, `_handle_done()`
- Logs events to Notes for debugging (optional)

**`RemindersClient`** (`reminders.py`):
- Interfaces with macOS Reminders via AppleScript subprocess calls
- Parses reminder data (ID, name, body, section, due date)
- Can annotate reminders with notes and update body tags
- Returns empty list on AppleScript errors (never raises)

**`GitHubClient`** (`github.py`):
- Wraps PyGithub API
- Creates issues, adds comments, closes issues, merges PRs
- Returns `None` on API errors (never raises)

**`SQLiteStore`** (`store.py`):
- Single table: `issue_mappings` (reminder_id PK → GitHub issue/PR numbers + section)
- Bootstraps schema on first run
- All DB access is protected by `threading.Lock()` for async safety
- Tracks created_at / updated_at timestamps

### Configuration

**Sources** (in priority order):
1. Environment variables: `APPLE_GIT_*` prefix
2. `.env` file in project root
3. `config/config.yaml` (for nested settings like GitHub)
4. Hardcoded defaults in `config.py`

**Structure** (Pydantic BaseSettings):
- `GitHubSettings`: token, repo
- `RemindersSettings`: list_name, three section names (issue-ready, review, issue-done)
- `NotesSettings`: folder_name, log_enabled
- Root: poll_interval_seconds, db_path, log_file

See AGENTS.md for code style and configuration details.

## Common Development Tasks

### Adding a New Feature

1. **Modify state machine** (`AppleGit.process()`):
   - Add new section or body tag handling
   - Implement corresponding `_handle_*` method

2. **Update GitHub integration** (`github.py`):
   - Add new client method (e.g., `add_label()`)
   - Update `AppleGit._create_issue()` or `_handle_*()` to call it

3. **Store new state** (`store.py`):
   - Add columns to `issue_mappings` table
   - Add accessor methods (`get_*`, `update_*`)
   - Update bootstrap schema

4. **Update config** (`config.py`):
   - Add new settings class or fields
   - Document in `.env.example`

### Testing Strategy

- Currently no unit tests (empty `tests/` directory)
- To add tests:
  - Mock `RemindersClient` to avoid AppleScript dependency
  - Use in-memory SQLite (`:memory:`) for store tests
  - Mock `GitHubClient` to avoid API calls
  - Focus on `AppleGit.process()` state transitions

### Debugging

1. **Enable verbose logging**:
   ```python
   logging.basicConfig(level=logging.DEBUG)
   ```

2. **Check state in SQLite**:
   ```bash
   sqlite3 ~/.apple-git/apple_git.sqlite "SELECT * FROM issue_mappings;"
   ```

3. **Test RemindersClient in isolation**:
   ```python
   from apple_git.reminders import RemindersClient
   client = RemindersClient("kanban")
   reminders = client.fetch_all()
   ```

4. **Inspect AppleScript errors**:
   - `RemindersClient.fetch_all()` logs warnings but doesn't crash
   - Check logs for "Unable to resolve Reminders selector" or AppleScript timeouts

## macOS Considerations

- **AppleScript dependency**: Only works on macOS. Requires System Events automation permission.
- **Reminders app**: Must be running or accessible via AppleScript
- **List resolution**: Supports both list name and list ID (ID is more reliable if list is renamed)
- **Timeout**: AppleScript calls have 30-second timeout; large lists may exceed this
- **Notes logging** (optional): Requires Notes app access via AppleScript

## Integration Points for Future Work

- **Custom automation**: Extend `_handle_*` methods in `AppleGit`
- **New sources**: Add new clients (similar to `RemindersClient`) for other macOS apps
- **Webhooks**: Replace polling with GitHub webhooks (would require HTTP server)
- **Slack/Discord**: Add messaging client alongside `NotesClient`
- **Advanced filtering**: Extend body tag parsing or section-based logic

## Key Dependencies

- **PyGithub**: GitHub API client (handles auth, rate limiting)
- **Pydantic**: Configuration validation and type safety
- **PyYAML**: Config file parsing
- **AppleScript**: Via subprocess (no Python library, direct execution)

See AGENTS.md for:
- Code style (imports, types, naming, dataclasses, error handling, logging, thread safety, file paths, constants, subprocess handling)
- Complete build, test, and lint commands
- Environment setup (.env.example, GITHUB_TOKEN requirement)
