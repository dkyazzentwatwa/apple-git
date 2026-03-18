from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.apple_git.config import AppleGitSettings
from src.apple_git.__main__ import AppleGit


class MockReminder:
    def __init__(
        self,
        id: str,
        name: str,
        body: str,
        list_name: str,
        url: str = "",
        creation_date: str = "",
        due_date: str = "",
    ):
        self.id = id
        self.name = name
        self.body = body
        self.list_name = list_name
        self.url = url
        self.creation_date = creation_date
        self.due_date = due_date


class MockGitHubIssue:
    def __init__(self, number: int, url: str):
        self.number = number
        self.url = url


class MockGitHubPR:
    def __init__(self, number: int, url: str):
        self.number = number
        self.url = url


@pytest.fixture
def mock_settings():
    settings = AppleGitSettings(
        poll_interval_seconds=0.1,
        db_path=Path(":memory:"),
        repo_path=Path("/tmp/mock_repo"),
        anthropic_api_key="test_anthropic_key",
        enable_pr_review=True,
        enable_security_review=True,
        connector_backend="claude",
    )
    return settings


@pytest.fixture
def apple_git_instance(mock_settings):
    with (
        patch("src.apple_git.store.SQLiteStore") as MockStore,
        patch("src.apple_git.reminders.RemindersClient") as _MockRemindersClient,
        patch("src.apple_git.github.GitHubClient") as MockGitHubClient,
        patch("src.apple_git.notes.NotesClient") as MockNotesClient,
        patch("src.apple_git.connector.build_connector") as MockBuildConnector,
        patch("src.apple_git.issue_analyzer.IssueAnalyzer") as MockIssueAnalyzer,
        patch("src.apple_git.reviewer.PRReviewer") as MockPRReviewer,
        patch("src.apple_git.security_reviewer.SecurityReviewer") as MockSecurityReviewer,
        patch.object(mock_settings, 'repo_path', new_callable=MagicMock) as MockRepoPath,
        patch("src.apple_git.github.GitHubClient._format_comment") as MockFormatComment,
    ):
        instance = AppleGit(mock_settings)

        # Configure mocks
        instance.store = MockStore.return_value
        
        # Use separate mocks for each list to avoid cross-contamination
        instance.reminders_issue_ready = MagicMock()
        instance.reminders_review = MagicMock()
        instance.reminders_done = MagicMock()
        
        # Default fetch_all to empty
        instance.reminders_issue_ready.fetch_all.return_value = []
        instance.reminders_review.fetch_all.return_value = []
        instance.reminders_done.fetch_all.return_value = []

        instance.github_client = MockGitHubClient.return_value
        instance.notes_client = MockNotesClient.return_value
        instance.connector = MockBuildConnector.return_value
        instance.connector.backend_name = "claude"
        
        instance.issue_analyzer = MockIssueAnalyzer.return_value
        instance.pr_reviewer = MockPRReviewer.return_value
        instance.security_reviewer = MockSecurityReviewer.return_value

        # Set default mock return values
        instance.github_client.create_issue.return_value = MockGitHubIssue(1, "http://github.com/issue/1")
        instance.github_client.create_pr.return_value = MockGitHubPR(101, "http://github.com/pr/101")
        instance.github_client.get_pr.return_value = MockGitHubPR(101, "http://github.com/pr/101")
        instance.github_client.ensure_branch.return_value = True
        instance.github_client.branch_has_commits_ahead.return_value = True
        instance.github_client.merge_pr.return_value = True
        instance.github_client.close_issue.return_value = True
        instance.github_client.get_commits_on_branch.return_value = ["feat: add something"]
        instance.github_client.get_pr_diff_files.return_value = [
            {"filename": "file.py", "patch": "diff"}
        ]
        instance.issue_analyzer.analyze.return_value = "AI analysis"
        instance.pr_reviewer.review.return_value = "AI code review"
        instance.security_reviewer.review.return_value = "AI security review"
        instance.connector.is_available.return_value = True

        # Ensure MockRepoPath.exists() returns True by default
        MockRepoPath.exists.return_value = True
        MockRepoPath.name = "mock_repo_name" # Added this line
        MockFormatComment.side_effect = lambda heading, bullets, intro="", outro="": f"Formatted: {heading}"
        yield instance


@pytest.mark.asyncio
async def test_process_create_issue(apple_git_instance):
    """Test processing a reminder to create a new issue."""
    reminder = MockReminder("rem1", "Test Issue", "Issue Body", "dev-issue-ready")
    apple_git_instance.reminders_issue_ready.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = None  # No existing mapping

    apple_git_instance.process()

    apple_git_instance.github_client.create_issue.assert_called_once_with(
        reminder.name, reminder.body
    )
    apple_git_instance.store.upsert_issue_mapping.assert_called_once()
    apple_git_instance.reminders_issue_ready.update_body_tags.assert_called_once()
    apple_git_instance.reminders_issue_ready.set_reminder_url.assert_called_once()
    apple_git_instance.reminders_issue_ready.annotate_reminder.assert_called_once()
    apple_git_instance.github_client.add_issue_comment.assert_called()  # Two comments: Picked Up, AI Analysis
    apple_git_instance.reminders_issue_ready.update_status_line.assert_called_once()
    apple_git_instance.notes_client.log_event.assert_called_once_with(
        "issue_created",
        {
            "reminder": reminder.name,
            "issue_number": "1",
            "url": "http://github.com/issue/1",
            "branch": "issue-1",
        },
    )


@pytest.mark.asyncio
async def test_process_handle_review_create_pr(apple_git_instance):
    """Test processing a reminder to create a new PR."""
    branch_name = "issue-1"
    reminder = MockReminder("rem1", "Test PR", f"#branch:{branch_name}", "dev-review")
    apple_git_instance.reminders_review.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "dev-review",
        "reminder_title": "Test PR",
        "github_pr_number": None,  # No existing PR
    }

    apple_git_instance.process()

    apple_git_instance.github_client.create_pr.assert_called_once_with(
        title=reminder.name, body=reminder.body, head=branch_name
    )
    apple_git_instance.store.update_pr_number.assert_called_once_with("rem1", 101)
    apple_git_instance.github_client.add_pr_comment.assert_called()  # For summary, code review, security review
    apple_git_instance.reminders_review.update_status_line.assert_called_once()
    apple_git_instance.notes_client.log_event.assert_called_once_with(
        "pr_created",
        {
            "reminder": reminder.name,
            "issue_number": "1",
            "pr_number": "101",
            "url": "http://github.com/pr/101",
        },
    )


@pytest.mark.asyncio
async def test_process_handle_review_link_pr(apple_git_instance):
    """Test processing a reminder to link an existing PR."""
    pr_url = "https://github.com/owner/repo/pull/123"
    reminder = MockReminder("rem1", "Test PR Link", pr_url, "dev-review")
    apple_git_instance.reminders_review.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "dev-review",
        "reminder_title": "Test PR Link",
        "github_pr_number": None,
    }

    apple_git_instance.process()

    apple_git_instance.store.update_pr_number.assert_called_once_with("rem1", 123)
    apple_git_instance.reminders_review.update_status_line.assert_called_once()
    apple_git_instance.notes_client.log_event.assert_called_once_with(
        "pr_linked",
        {
            "reminder": reminder.name,
            "issue_number": "1",
            "pr_number": "123",
        },
    )
    apple_git_instance.github_client.create_pr.assert_not_called()  # Should not create PR


@pytest.mark.asyncio
async def test_process_handle_done(apple_git_instance):
    """Test processing a reminder to merge PR and close issue."""
    reminder = MockReminder("rem1", "Test Done", "#merge", "dev-done")
    apple_git_instance.reminders_done.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "dev-done",
        "reminder_title": "Test Done",
        "github_pr_number": 101,  # Has an associated PR
    }

    apple_git_instance.process()

    apple_git_instance.github_client.merge_pr.assert_called_once_with(101)
    apple_git_instance.github_client.close_issue.assert_called_once_with(1)
    apple_git_instance.store.delete_mapping.assert_called_once_with("rem1")
    apple_git_instance.reminders_done.complete_reminder.assert_called_once_with("rem1")
    assert apple_git_instance.notes_client.log_event.call_count == 2  # pr_merged and issue_closed


@pytest.mark.asyncio
async def test_process_done_no_pr(apple_git_instance):
    """Test processing a reminder in done list with no associated PR."""
    reminder = MockReminder("rem1", "Test Done No PR", "", "dev-done")
    apple_git_instance.reminders_done.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "dev-done",
        "reminder_title": "Test Done No PR",
        "github_pr_number": None,  # No associated PR
    }

    apple_git_instance.process()

    apple_git_instance.github_client.merge_pr.assert_not_called()
    apple_git_instance.github_client.close_issue.assert_called_once_with(1)
    apple_git_instance.store.delete_mapping.assert_called_once_with("rem1")
    apple_git_instance.reminders_done.complete_reminder.assert_called_once_with("rem1")
    apple_git_instance.notes_client.log_event.assert_called_once_with(
        "issue_closed", {"reminder": reminder.name, "issue_number": "1"}
    )


@pytest.mark.asyncio
async def test_process_handle_done_merge_conflict(apple_git_instance):
    """Test processing a reminder in done list where PR merge fails."""
    reminder = MockReminder("rem1", "Test Merge Conflict", "#merge", "dev-done")
    apple_git_instance.reminders_done.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "dev-done",
        "reminder_title": "Test Merge Conflict",
        "github_pr_number": 101,  # Has an associated PR
    }
    apple_git_instance.github_client.merge_pr.return_value = False  # Simulate merge failure

    apple_git_instance.process()

    apple_git_instance.github_client.merge_pr.assert_called_once_with(101)
    apple_git_instance.github_client.add_issue_comment.assert_called_once_with(
        1,
        "Formatted: Merge Failed",
    )
    apple_git_instance.reminders_done.update_status_line.assert_called_once_with(
        "rem1", "⚠️ Merge Conflict — Fix manually"
    )
    apple_git_instance.notes_client.log_event.assert_called_once_with(
        "merge_failed",
        {"reminder": reminder.name, "pr_number": "101", "reason": "conflict"},
    )
    apple_git_instance.github_client.close_issue.assert_not_called()
    apple_git_instance.store.delete_mapping.assert_not_called()
    apple_git_instance.reminders_done.complete_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_run_forever_shutdown(apple_git_instance):
    """Test that run_forever can be shut down gracefully."""
    # Simulate shutdown request after one loop
    async def shutdown_after_loop():
        await asyncio.sleep(0.05)  # Let one loop iteration run
        apple_git_instance._shutdown_requested = True

    await asyncio.gather(apple_git_instance.run_forever(), shutdown_after_loop())

    assert apple_git_instance._shutdown_requested is True


@pytest.mark.asyncio
async def test_spawn_connector_not_available(apple_git_instance):
    """Test that connector is not spawned if not available."""
    apple_git_instance.connector.is_available.return_value = False
    apple_git_instance._spawn_connector(1, "title", "body", "branch", "rem1")
    apple_git_instance.connector.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_spawn_connector_already_running(apple_git_instance):
    """Test that connector is not spawned if already running for the issue."""
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None  # Still running
    mock_proc.pid = 1234
    apple_git_instance._claude_procs[1] = (mock_proc, "branch", "rem1")

    apple_git_instance._spawn_connector(1, "title", "body", "branch", "rem1")
    apple_git_instance.connector.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_reap_connector_procs_success(apple_git_instance):
    """Test reaping a successfully finished connector process."""
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = 0  # Success
    apple_git_instance._claude_procs[1] = (mock_proc, "issue-1", "rem1")

    apple_git_instance._reap_claude_procs()

    apple_git_instance.github_client.add_issue_comment.assert_called_once_with(
        1,
        "Formatted: claude Success",
    )
    apple_git_instance.reminders_issue_ready.update_status_line.assert_called_once_with(
        "rem1", "✅ Done — move to dev-review"
    )
    apple_git_instance.notes_client.log_event.assert_called_once_with(
        "connector_finished", {"issue_number": "1", "branch": "issue-1"}
    )
    assert 1 not in apple_git_instance._claude_procs


@pytest.mark.asyncio
async def test_reap_connector_procs_error(apple_git_instance):
    """Test reaping a connector process that exited with an error."""
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = 1  # Error
    apple_git_instance._claude_procs[1] = (mock_proc, "issue-1", "rem1")

    apple_git_instance._reap_claude_procs()

    apple_git_instance.github_client.add_issue_comment.assert_called_once_with(
        1,
        "Formatted: claude Error",
    )
    apple_git_instance.reminders_issue_ready.update_status_line.assert_called_once_with(
        "rem1", "⚠️ claude error (exit 1) — check logs"
    )
    apple_git_instance.notes_client.log_event.assert_called_once_with(
        "claude_error", {"issue_number": "1", "branch": "issue-1", "exit_code": "1"}
    )
    assert 1 not in apple_git_instance._claude_procs
