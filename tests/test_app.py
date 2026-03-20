from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apple_git.config import AppleGitSettings
from apple_git.__main__ import AppleGit


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
    def __init__(self, number: int, url: str, merged: bool = False):
        self.number = number
        self.url = url
        self.merged = merged


@pytest.fixture
def mock_settings():
    settings = AppleGitSettings(
        poll_interval_seconds=0.1,
        db_path=Path(":memory:"),
        connector_logs_dir=Path("/tmp/connector-runs"),
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
        patch("apple_git.store.SQLiteStore") as MockStore,
        patch("apple_git.reminders.RemindersClient") as _MockRemindersClient,
        patch("apple_git.github.GitHubClient") as MockGitHubClient,
        patch("apple_git.notes.NotesClient") as MockNotesClient,
        patch("apple_git.connector.build_connector") as MockBuildConnector,
        patch("apple_git.planner.build_issue_planner") as MockBuildIssuePlanner,
        patch("apple_git.issue_analyzer.IssueAnalyzer") as MockIssueAnalyzer,
        patch("apple_git.reviewer.PRReviewer") as MockPRReviewer,
        patch("apple_git.security_reviewer.SecurityReviewer") as MockSecurityReviewer,
        patch.object(mock_settings, 'repo_path', new_callable=MagicMock) as MockRepoPath,
        patch("apple_git.github.GitHubClient._format_comment") as MockFormatComment,
    ):
        instance = AppleGit(mock_settings)

        # Configure mocks
        instance.store = MockStore.return_value
        
        # Use separate mocks for each list to avoid cross-contamination
        instance.reminders_issue_plan = MagicMock()
        instance.reminders_issue_ready = MagicMock()
        instance.reminders_review = MagicMock()
        instance.reminders_done = MagicMock()
        
        # Default fetch_all to empty
        instance.reminders_issue_plan.fetch_all.return_value = []
        instance.reminders_issue_ready.fetch_all.return_value = []
        instance.reminders_review.fetch_all.return_value = []
        instance.reminders_done.fetch_all.return_value = []

        instance.github_client = MockGitHubClient.return_value
        instance.notes_client = MockNotesClient.return_value
        instance.connector = MockBuildConnector.return_value
        instance.connector.backend_name = "claude"
        
        instance.issue_planner = MockBuildIssuePlanner.return_value
        instance.issue_analyzer = MockIssueAnalyzer.return_value
        instance.pr_reviewer = MockPRReviewer.return_value
        instance.security_reviewer = MockSecurityReviewer.return_value

        # Set default mock return values
        instance.github_client.create_issue.return_value = MockGitHubIssue(1, "http://github.com/issue/1")
        instance.github_client.create_pr.return_value = MockGitHubPR(101, "http://github.com/pr/101")
        instance.github_client.get_pr.return_value = MockGitHubPR(101, "http://github.com/pr/101")
        instance.github_client.get_default_branch.return_value = None
        instance.github_client.upsert_issue_comment.return_value = True
        instance.github_client.get_issue_comment_by_marker.return_value = "## Problem\nA plan"
        instance.github_client.ensure_branch.return_value = True
        instance.github_client.branch_has_commits_ahead.return_value = True
        instance.github_client.merge_pr.return_value = True
        instance.github_client.close_issue.return_value = True
        instance.github_client.get_commits_on_branch.return_value = ["feat: add something"]
        instance.github_client.get_pr_diff_files.return_value = [
            {"filename": "file.py", "patch": "diff"}
        ]
        instance.issue_planner.plan.return_value = "## Problem\nA plan"
        instance.issue_analyzer.analyze.return_value = "AI analysis"
        instance.pr_reviewer.review.return_value = "AI code review"
        instance.security_reviewer.review.return_value = "AI security review"
        instance.connector.is_available.return_value = True

        # Ensure MockRepoPath.exists() returns True by default
        MockRepoPath.exists.return_value = True
        MockRepoPath.name = "mock_repo_name" # Added this line
        MockFormatComment.side_effect = lambda heading, bullets, intro="", outro="": f"Formatted: {heading}"
        yield instance


def test_init_builds_planner_from_connector_settings_without_anthropic_key():
    settings = AppleGitSettings(
        poll_interval_seconds=0.1,
        db_path=Path(":memory:"),
        connector_logs_dir=Path("/tmp/connector-runs"),
        repo_path=Path("/tmp/mock_repo"),
        anthropic_api_key="",
        connector_backend="codex",
        connector_model="gpt-5.4-mini",
        connector_command="codex",
    )

    with (
        patch("apple_git.store.SQLiteStore"),
        patch("apple_git.reminders.RemindersClient"),
        patch("apple_git.github.GitHubClient"),
        patch("apple_git.notes.NotesClient"),
        patch("apple_git.connector.build_connector") as mock_build_connector,
        patch("apple_git.planner.build_issue_planner") as mock_build_issue_planner,
    ):
        mock_build_connector.return_value.backend_name = "codex"
        planner_instance = MagicMock()
        mock_build_issue_planner.return_value = planner_instance

        instance = AppleGit(settings)

    mock_build_issue_planner.assert_called_once_with(
        backend="codex",
        model="gpt-5.4-mini",
        command="codex",
    )
    assert instance.issue_planner is planner_instance


@pytest.mark.asyncio
async def test_process_issue_plan_creates_issue_and_posts_plan(apple_git_instance):
    """Test processing a reminder in issue-plan creates an issue and canonical plan comment."""
    reminder = MockReminder("rem1", "Test Issue", "Issue Body", "issue-plan")
    apple_git_instance.reminders_issue_plan.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = None  # No existing mapping

    apple_git_instance.process()

    apple_git_instance.github_client.create_issue.assert_called_once_with(
        reminder.name, reminder.body
    )
    apple_git_instance.issue_planner.plan.assert_called_once()
    apple_git_instance.github_client.upsert_issue_comment.assert_called_once()
    apple_git_instance.store.upsert_issue_mapping.assert_called_once()
    apple_git_instance.connector.spawn.assert_not_called()
    apple_git_instance.reminders_issue_plan.update_body_tags.assert_called_once()
    apple_git_instance.reminders_issue_plan.set_reminder_url.assert_not_called()
    apple_git_instance.reminders_issue_plan.annotate_reminder.assert_called_once_with(
        "rem1",
        "Issue #1\nIssue: http://github.com/issue/1",
    )
    apple_git_instance.github_client.add_issue_comment.assert_called()  # Picked Up, AI Analysis
    apple_git_instance.reminders_issue_plan.update_status_line.assert_called_once_with(
        "rem1", "📝 Plan ready — move to issue-ready to start coding"
    )
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
async def test_process_issue_plan_reports_planner_unavailable(apple_git_instance):
    """Test that issue-plan does not start coding and reports when planning is unavailable."""
    reminder = MockReminder("rem1", "Test Issue", "Issue Body", "issue-plan")
    apple_git_instance.reminders_issue_plan.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = None
    apple_git_instance.issue_planner = None

    apple_git_instance.process()

    apple_git_instance.connector.spawn.assert_not_called()
    apple_git_instance.reminders_issue_plan.update_status_line.assert_called_once_with(
        "rem1", "⚠️ planning unavailable — issue created but plan not generated"
    )
    apple_git_instance.github_client.upsert_issue_comment.assert_not_called()


@pytest.mark.asyncio
async def test_process_issue_plan_regenerates_missing_plan_for_existing_mapping(apple_git_instance):
    """Test that returning a mapped reminder to issue-plan regenerates the canonical plan if missing."""
    reminder = MockReminder("rem1", "Test Issue", "Issue Body", "issue-plan")
    apple_git_instance.reminders_issue_plan.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "issue-plan",
        "reminder_title": "Test Issue",
        "github_pr_number": None,
    }
    apple_git_instance.github_client.get_issue_comment_by_marker.return_value = ""

    apple_git_instance.process()

    apple_git_instance.issue_planner.plan.assert_called_once()
    apple_git_instance.github_client.upsert_issue_comment.assert_called_once()
    apple_git_instance.connector.spawn.assert_not_called()


@pytest.mark.asyncio
async def test_process_issue_plan_regenerates_when_regen_tag_present(apple_git_instance):
    """Test that #regen-plan forces a plan refresh for an existing mapped issue."""
    reminder = MockReminder(
        "rem1",
        "Test Issue",
        "Please tighten scope\n#regen-plan #branch:issue-1",
        "issue-plan",
    )
    apple_git_instance.reminders_issue_plan.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "issue-plan",
        "reminder_title": "Test Issue",
        "github_pr_number": None,
    }

    apple_git_instance.process()

    apple_git_instance.issue_planner.plan.assert_called_once()
    prompt = apple_git_instance.issue_planner.plan.call_args.kwargs["prompt"]
    assert "Operator feedback:\nPlease tighten scope" in prompt
    assert "#regen-plan" not in prompt
    assert "#branch:issue-1" not in prompt
    apple_git_instance.github_client.upsert_issue_comment.assert_called_once()
    apple_git_instance.reminders_issue_plan.update_body_tags.assert_called_once_with(
        "rem1", "#regen-plan", ""
    )
    apple_git_instance.reminders_issue_plan.update_status_line.assert_called_once_with(
        "rem1", "📝 Plan regenerated — review and move to issue-ready when approved"
    )


@pytest.mark.asyncio
async def test_process_issue_plan_preserves_regen_tag_when_regeneration_fails(apple_git_instance):
    """Test that #regen-plan remains until a regeneration succeeds."""
    reminder = MockReminder("rem1", "Test Issue", "#regen-plan", "issue-plan")
    apple_git_instance.reminders_issue_plan.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "issue-plan",
        "reminder_title": "Test Issue",
        "github_pr_number": None,
    }
    apple_git_instance.issue_planner.plan.return_value = ""

    apple_git_instance.process()

    apple_git_instance.github_client.upsert_issue_comment.assert_not_called()
    apple_git_instance.reminders_issue_plan.update_body_tags.assert_not_called()
    apple_git_instance.reminders_issue_plan.update_status_line.assert_called_once_with(
        "rem1", "⚠️ plan regeneration failed — fix feedback and try again"
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
        title=reminder.name, body=reminder.body, head=branch_name, base="main"
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
async def test_process_issue_ready_starts_connector_from_existing_plan(apple_git_instance):
    """Test that issue-ready starts code generation only when a mapping and plan already exist."""
    reminder = MockReminder("rem1", "Test Issue", "Issue Body #branch:issue-1", "dev-issue-ready")
    apple_git_instance.reminders_issue_ready.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "issue-plan",
        "reminder_title": "Test Issue",
        "github_pr_number": None,
    }
    apple_git_instance.store.get_latest_connector_run_for_issue.return_value = None

    apple_git_instance.process()

    apple_git_instance.github_client.create_issue.assert_not_called()
    apple_git_instance.github_client.get_issue_comment_by_marker.assert_called_once()
    apple_git_instance.store.update_section.assert_called_once_with("rem1", "dev-issue-ready")
    apple_git_instance.store.create_connector_run.assert_called_once()


@pytest.mark.asyncio
async def test_process_issue_ready_does_not_respawn_after_successful_run(apple_git_instance):
    """Test that issue-ready does not respawn work after a successful connector run."""
    reminder = MockReminder("rem1", "Test Issue", "Issue Body #branch:issue-1", "dev-issue-ready")
    apple_git_instance.reminders_issue_ready.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "issue-plan",
        "reminder_title": "Test Issue",
        "github_pr_number": None,
    }
    apple_git_instance.store.get_latest_connector_run_for_issue.return_value = {
        "run_id": "run-1",
        "status": "succeeded",
        "backend": "codex",
        "branch": "issue-1",
    }

    apple_git_instance.process()

    apple_git_instance.connector.spawn.assert_not_called()
    apple_git_instance.store.create_connector_run.assert_not_called()
    apple_git_instance.reminders_issue_ready.move_reminder_to_list.assert_called_once_with(
        "rem1", apple_git_instance.settings.reminders.list_review
    )


@pytest.mark.asyncio
async def test_process_issue_ready_requires_existing_plan_comment(apple_git_instance):
    """Test that issue-ready blocks when the canonical plan comment is missing."""
    reminder = MockReminder("rem1", "Test Issue", "Issue Body #branch:issue-1", "dev-issue-ready")
    apple_git_instance.reminders_issue_ready.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "issue-plan",
        "reminder_title": "Test Issue",
        "github_pr_number": None,
    }
    apple_git_instance.github_client.get_issue_comment_by_marker.return_value = ""
    apple_git_instance.store.get_latest_connector_run_for_issue.return_value = None

    apple_git_instance.process()

    apple_git_instance.connector.spawn.assert_not_called()
    apple_git_instance.reminders_issue_ready.update_status_line.assert_called_once_with(
        "rem1", "⚠️ no approved plan found — move back to issue-plan"
    )
    apple_git_instance.store.create_connector_run.assert_not_called()


@pytest.mark.asyncio
async def test_process_handle_review_uses_configured_base_branch(apple_git_instance):
    """Test that review flow uses the configured base branch consistently."""
    apple_git_instance.settings.github.base_branch = "develop"
    branch_name = "issue-1"
    reminder = MockReminder("rem1", "Test PR", f"#branch:{branch_name}", "dev-review")
    apple_git_instance.reminders_review.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "dev-review",
        "reminder_title": "Test PR",
        "github_pr_number": None,
    }

    apple_git_instance.process()

    apple_git_instance.github_client.ensure_branch.assert_called_once_with(branch_name, base="develop")
    apple_git_instance.github_client.branch_has_commits_ahead.assert_called_once_with(
        branch_name, base="develop"
    )
    apple_git_instance.github_client.create_pr.assert_called_once_with(
        title=reminder.name, body=reminder.body, head=branch_name, base="develop"
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
async def test_process_handle_done_requires_merge_tag_for_open_pr(apple_git_instance):
    """Test that done state does not auto-merge or close when #merge is absent."""
    reminder = MockReminder("rem1", "Manual Merge Needed", "", "dev-done")
    apple_git_instance.reminders_done.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "dev-done",
        "reminder_title": "Manual Merge Needed",
        "github_pr_number": 101,
    }
    apple_git_instance.github_client.get_pr.return_value = MockGitHubPR(
        101, "http://github.com/pr/101", merged=False
    )

    apple_git_instance.process()

    apple_git_instance.github_client.merge_pr.assert_not_called()
    apple_git_instance.github_client.close_issue.assert_not_called()
    apple_git_instance.store.delete_mapping.assert_not_called()
    apple_git_instance.reminders_done.complete_reminder.assert_not_called()
    apple_git_instance.reminders_done.update_status_line.assert_called_once_with(
        "rem1", "⏸️ PR open — merge manually or add #merge"
    )


@pytest.mark.asyncio
async def test_process_handle_done_closes_issue_when_pr_already_merged(apple_git_instance):
    """Test that done state closes the issue when the PR is already merged."""
    reminder = MockReminder("rem1", "Already Merged", "", "dev-done")
    apple_git_instance.reminders_done.fetch_all.return_value = [reminder]
    apple_git_instance.store.get_mapping_by_reminder_id.return_value = {
        "reminder_id": "rem1",
        "github_issue_number": 1,
        "section": "dev-done",
        "reminder_title": "Already Merged",
        "github_pr_number": 101,
    }
    apple_git_instance.github_client.get_pr.return_value = MockGitHubPR(
        101, "http://github.com/pr/101", merged=True
    )

    apple_git_instance.process()

    apple_git_instance.github_client.merge_pr.assert_not_called()
    apple_git_instance.github_client.close_issue.assert_called_once_with(1)
    apple_git_instance.store.delete_mapping.assert_called_once_with("rem1")
    apple_git_instance.reminders_done.complete_reminder.assert_called_once_with("rem1")


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
    apple_git_instance.store.create_connector_run.assert_called_once()
    apple_git_instance.reminders_issue_ready.update_status_line.assert_called_once_with(
        "rem1", "⚠️ claude unavailable — issue created but worker not started"
    )


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
async def test_spawn_connector_prompt_uses_structured_codegen_template(apple_git_instance):
    """Test that connector prompt uses the stricter structured codegen template."""
    apple_git_instance.settings.github.base_branch = "develop"
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.pid = 4321
    apple_git_instance.connector.spawn.return_value = mock_proc

    apple_git_instance._spawn_connector(1, "title", "body", "issue-1", "rem1")

    prompt = apple_git_instance.connector.spawn.call_args.args[0]
    assert "You are implementing the approved plan for GitHub issue #1." in prompt
    assert "Branch:\nissue-1" in prompt
    assert "Base branch:\ndevelop" in prompt
    assert "If blocked, output exactly this format and nothing else:" in prompt
    assert "## Commit message" in prompt


def test_build_issue_plan_prompt_uses_structured_planning_template(apple_git_instance):
    """Test that the issue planning prompt uses the stricter structured template."""
    with patch("apple_git.__main__.tree.generate_tree", return_value="src/\n  app.py"):
        prompt = apple_git_instance._build_issue_plan_prompt(
            issue_number=7,
            title="Add issue planning",
            body="Need a planning phase before coding starts.",
            repo_path=Path("/tmp/mock_repo"),
        )

    assert "You are preparing an implementation plan for GitHub issue #7." in prompt
    assert "## Problem" in prompt
    assert "## Ready for implementation" in prompt
    assert '"Proposed changes" must contain 3-7 numbered steps.' in prompt


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
    apple_git_instance.reminders_issue_ready.move_reminder_to_list.assert_called_once_with(
        "rem1", apple_git_instance.settings.reminders.list_review
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
