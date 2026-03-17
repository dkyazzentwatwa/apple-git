from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import config, github, notes, reminders, store
from .config import AppleGitSettings, get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("apple_git")


class AppleGit:
    def __init__(self, settings: AppleGitSettings):
        self.settings = settings
        self.store = store.SQLiteStore(settings.db_path)
        self.reminders_issue_ready = reminders.RemindersClient(settings.reminders.list_issue_ready)
        self.reminders_review = reminders.RemindersClient(settings.reminders.list_review)
        self.reminders_done = reminders.RemindersClient(settings.reminders.list_done)
        self.github_client = (
            github.GitHubClient(settings.github.token, settings.github.repo)
            if settings.github.token and settings.github.repo
            else None
        )
        self.notes_client = (
            notes.NotesClient(settings.notes.folder_name)
            if settings.notes.log_enabled
            else None
        )
        self._shutdown_requested = False

    def bootstrap(self) -> None:
        self.store.bootstrap()
        logger.info("apple-git initialized")

    def process(self) -> None:
        # Process reminders in issue-ready list: create issues for unmapped reminders
        for rem in self.reminders_issue_ready.fetch_all():
            if self.store.get_mapping_by_reminder_id(rem.id) is None:
                self._create_issue(rem)

        # Process reminders in review list: handle PR linking and creation
        for rem in self.reminders_review.fetch_all():
            mapping = self.store.get_mapping_by_reminder_id(rem.id)
            if mapping:
                self._handle_review(rem, mapping)
            else:
                logger.warning("Reminder %s in review list but has no issue mapping — skipping", rem.id)
                if self.notes_client:
                    self.notes_client.log_event("review_skipped_no_mapping", {
                        "reminder": rem.name,
                    })

        # Process reminders in done list: merge PRs, close issues, complete reminders
        for rem in self.reminders_done.fetch_all():
            mapping = self.store.get_mapping_by_reminder_id(rem.id)
            if mapping:
                self._handle_done(rem, mapping)
                self.store.delete_mapping(rem.id)
            else:
                logger.warning("Reminder %s in done list but has no issue mapping — completing anyway", rem.id)
                if self.notes_client:
                    self.notes_client.log_event("done_completed_no_mapping", {
                        "reminder": rem.name,
                    })
            self.reminders_done.complete_reminder(rem.id)

    def _create_issue(self, rem: reminders.Reminder) -> None:
        if not self.github_client:
            logger.warning("GitHub client not configured")
            return

        issue = self.github_client.create_issue(rem.name, rem.body)
        if issue:
            self.store.upsert_issue_mapping(
                reminder_id=rem.id,
                github_issue_number=issue.number,
                section=self.settings.reminders.list_issue_ready,
                reminder_title=rem.name,
            )
            branch_name = f"issue-{issue.number}"
            self.reminders_issue_ready.update_body_tags(rem.id, "", f"#branch:{branch_name}")
            self.reminders_issue_ready.set_reminder_url(rem.id, issue.url)
            self.reminders_issue_ready.annotate_reminder(rem.id, f"Issue #{issue.number}")

            if self.notes_client:
                self.notes_client.log_event("issue_created", {
                    "reminder": rem.name,
                    "issue_number": str(issue.number),
                    "url": issue.url,
                    "branch": branch_name,
                })
            logger.info("Created issue #%d for reminder %s (branch: %s)", issue.number, rem.id, branch_name)
            self._spawn_claude_code(issue.number, rem.name, rem.body, branch_name)

    def _spawn_claude_code(self, issue_number: int, title: str, body: str, branch: str) -> None:
        repo_path = self.settings.repo_path
        if not repo_path.exists():
            logger.warning("repo_path %s does not exist — skipping Claude Code spawn", repo_path)
            return

        prompt = (
            f"Work on GitHub issue #{issue_number}: {title}\n\n"
            f"{body}\n\n"
            f"Steps:\n"
            f"1. git checkout {branch} (or git checkout -b {branch} main if it doesn't exist locally)\n"
            f"2. Implement the changes required by the issue\n"
            f"3. git add and git commit with a message referencing issue #{issue_number}\n"
            f"4. git push origin {branch}"
        )

        try:
            subprocess.Popen(
                [
                    "claude",
                    "--model", "claude-haiku-4-5-20251001",
                    "--dangerously-skip-permissions",
                    "-p", prompt,
                ],
                cwd=str(repo_path),
                start_new_session=True,
            )
            logger.info("Spawned Claude Code for issue #%d on branch %s in %s", issue_number, branch, repo_path)
        except FileNotFoundError:
            logger.error("claude CLI not found — is Claude Code installed and on PATH?")
        except Exception as exc:
            logger.warning("Failed to spawn Claude Code: %s", exc)

    def _handle_review(self, rem: reminders.Reminder, mapping: dict) -> None:
        # Skip if PR already linked (idempotency guard)
        if mapping.get("github_pr_number"):
            return

        # Try to create PR from #branch:name tag
        branch = reminders.extract_branch_tag(rem.body)
        if branch:
            if not self.github_client:
                logger.warning("GitHub client not configured")
                return
            issue_number = mapping.get("github_issue_number")
            self.github_client.ensure_branch(branch)
            if not self.github_client.branch_has_commits_ahead(branch):
                logger.info("Branch %s has no commits ahead of main yet — skipping PR creation", branch)
                return
            pr = self.github_client.create_pr(
                title=rem.name,
                body=rem.body,
                head=branch,
            )
            if pr:
                self.store.update_pr_number(rem.id, pr.number)
                note = f"Created PR #{pr.number}: {pr.url}"
                self.reminders_review.annotate_reminder(rem.id, note)
                if self.notes_client:
                    self.notes_client.log_event("pr_created", {
                        "reminder": rem.name,
                        "issue_number": str(issue_number),
                        "pr_number": str(pr.number),
                        "url": pr.url,
                    })
                logger.info("Created PR #%d for reminder %s", pr.number, rem.id)
            return

        # Try to link existing PR from GitHub URL
        pr_number = reminders.extract_pr_number(rem.body)
        if pr_number:
            self.store.update_pr_number(rem.id, pr_number)
            if self.notes_client:
                self.notes_client.log_event("pr_linked", {
                    "reminder": rem.name,
                    "issue_number": str(mapping.get("github_issue_number")),
                    "pr_number": str(pr_number),
                })
            logger.info("Linked PR #%d to reminder %s", pr_number, rem.id)
            return

        # Neither branch tag nor PR URL found
        logger.warning(
            "No #branch: tag and no PR URL in reminder %s body — skipping",
            rem.id
        )
        if self.notes_client:
            self.notes_client.log_event("pr_review_skipped", {
                "reminder": rem.name,
                "reason": "no #branch: tag and no PR URL",
            })

    def _handle_done(self, rem: reminders.Reminder, mapping: dict) -> None:
        pr_number = mapping.get("github_pr_number")
        issue_number = mapping.get("github_issue_number")

        has_merge = reminders.has_merge_tag(rem.body)
        if has_merge and pr_number and self.github_client:
            if self.github_client.merge_pr(pr_number):
                pr = self.github_client.get_pr(pr_number)
                if pr:
                    note = f"Merged PR #{pr.number}: {pr.url}"
                    self.reminders_done.annotate_reminder(rem.id, note)
                if self.notes_client:
                    self.notes_client.log_event("pr_merged", {
                        "reminder": rem.name,
                        "pr_number": str(pr_number),
                    })
                logger.info("Merged PR #%d", pr_number)

        if issue_number and self.github_client:
            self.github_client.close_issue(issue_number)
            if self.notes_client:
                self.notes_client.log_event("issue_closed", {
                    "reminder": rem.name,
                    "issue_number": str(issue_number),
                })
            logger.info("Closed issue #%d", issue_number)

    async def run_forever(self) -> None:
        logger.info("Starting apple-git polling loop (interval=%.1fs)", self.settings.poll_interval_seconds)
        while not self._shutdown_requested:
            try:
                self.process()
            except Exception as exc:
                logger.exception("Error in process loop: %s", exc)

            for _ in range(int(self.settings.poll_interval_seconds * 10)):
                if self._shutdown_requested:
                    break
                await asyncio.sleep(0.1)

    def shutdown(self) -> None:
        logger.info("Shutting down apple-git...")
        self._shutdown_requested = True
        self.store.close()


def main():
    settings = get_settings()
    app = AppleGit(settings)
    app.bootstrap()

    def signal_handler(sig, frame):
        app.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    asyncio.run(app.run_forever())


if __name__ == "__main__":
    main()
