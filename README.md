# apple-git 🍎

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

**apple-git** is a macOS automation tool that transforms Apple Reminders into a powerful, agentic Kanban board for software development. It synchronizes your Reminders with GitHub Issues and Pull Requests, and orchestrates AI coding agents to work on tasks automatically.

## ✨ Features

- **Kanban Sync:** Seamless two-way synchronization between Apple Reminders lists and GitHub.
- **Agentic Workflow:**
  - **Plan First:** Moving a reminder to "Issue Plan" creates a GitHub issue and posts a structured implementation plan comment.
  - **AI Workers:** Moving a reminder to "Issue Ready" starts background AI agents (Claude, Codex, Kilo) on the approved plan in a dedicated branch.
  - **Automated PRs:** Moving a reminder to "Review" triggers PR creation.
- **AI Reviews:** Automatically analyzes issues and reviews Pull Requests using Anthropic's Claude (Code Review & Security Audit).
- **Status Updates:** Real-time updates in Reminders (e.g., "🔄 Claude working on issue #42", "✅ PR Merged").
- **Persistence:** Uses SQLite to maintain robust mappings between Reminders and GitHub entities.

## 🚀 Getting Started

### Prerequisites

- **macOS:** Required for AppleScript automation of the Reminders app.
- **Python 3.11+**
- **GitHub Account & Token:** A classic Personal Access Token (PAT) with `repo` scope.
- **Anthropic API Key:** For AI analysis and code reviews.
- **AI CLI Tools:** Ensure your preferred agent CLI (e.g., `claude`, `codex`) is installed and in your PATH.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/apple-git.git
    cd apple-git
    ```

2.  **Install dependencies:**
    ```bash
    pip install -e ".[dev]"
    ```

### Configuration

1.  **Environment Setup:**
    Copy the example environment file and configure your credentials.
    ```bash
    cp .env.example .env
    ```
    Edit `.env` with your details:
    ```ini
    GITHUB_TOKEN=your_github_pat
    APPLE_GIT_GITHUB_REPO=owner/repo_name
    ANTHROPIC_API_KEY=your_anthropic_key
    ```

2.  **Reminders App Setup:**
    Create the necessary lists in Apple Reminders (e.g., `dev-backlog`, `issue-plan`, `dev-issue-ready`, `dev-review`, `dev-done`).
    *See [REMINDERS_SETUP.md](REMINDERS_SETUP.md) for a detailed walkthrough of the workflow and list setup.*

3.  **Application Config (Optional):**
    Customize list names and polling intervals in `config/config.yaml`.

## 🖥️ Usage

### Running the Daemon

Start the synchronization loop:

```bash
apple-git
# or
python -m apple_git
```

The tool will begin polling your Reminders lists. Check the console output or `~/.apple-git/apple-git.log` for activity.

### The Workflow

1.  **Backlog:** Add tasks to your **Backlog** list in Reminders.
2.  **Plan:** Move a task to **Issue Plan**.
    - `apple-git` creates a GitHub Issue.
    - Posts a structured implementation plan comment.
3.  **Activate:** Move the task to **Issue Ready**.
    - `apple-git` starts an AI agent to work on a new branch (e.g., `issue-123`).
4.  **Review:** Move the task to **Review**.
    - `apple-git` creates a Pull Request.
    - Triggers AI code and security reviews.
5.  **Complete:** Move the task to **Done**.
    - Merges the PR (if `#merge` tag is present).
    - Closes the GitHub Issue.
    - Marks the Reminder as completed.

## 🏗️ Architecture

- **Orchestrator (`src/apple_git/`):** Central Python application managing state transitions.
- **Connectors:** Pluggable interface for different AI CLIs (`claude`, `codex`, `kilo`).
- **Storage:** SQLite database (`~/.apple-git/apple_git.sqlite`) tracks state and mappings.
- **Logs:** Activity is logged to standard output, file, and optionally Apple Notes.

## 🛠️ Development

### Testing
Run the test suite:
```bash
pytest
```

### Linting
Check for code style issues:
```bash
ruff check .
```

### Clean Up
Utility script to delete all issue branches from the repo:
```bash
python cleanup_branches.py
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
