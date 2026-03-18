from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
import sys

from . import (
    connector,
    github,
    issue_analyzer,
    notes,
    reminders,
    reviewer,
    security_reviewer,
    store,
    tree,
)
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
        self.connector = connector.build_connector(
            settings.connector_backend,
            model=settings.connector_model,
            command=settings.connector_command,
        )
        logger.info("Using connector backend: %s", self.connector.backend_name)

        # Initialize AI reviewers if API key and flags are set
        self.issue_analyzer = None
        self.pr_reviewer = None
        self.security_reviewer = None
        if settings.anthropic_api_key:
            self.issue_analyzer = issue_analyzer.IssueAnalyzer(settings.anthropic_api_key)
            if settings.enable_pr_review:
                self.pr_reviewer = reviewer.PRReviewer(settings.anthropic_api_key)
                logger.info("Enabled PR code review")
            if settings.enable_security_review:
                self.security_reviewer = security_reviewer.SecurityReviewer(
                    settings.anthropic_api_key
                )
                logger.info("Enabled security review")

        self._shutdown_requested = False
        self._completed_reminder_ids: set[str] = set()
        self._claude_procs: dict[int, tuple[subprocess.Popen, str, str]] = {}  # issue_number → (proc, branch, reminder_id)

    def bootstrap(self) -> None:
        self.store.bootstrap()
        logger.info("apple-git initialized")

    def _reap_claude_procs(self) -> None:
        """Reap any finished connector processes and log their exit codes."""
        backend = self.connector.backend_name
        for issue_number, (proc, branch, reminder_id) in list(self._claude_procs.items()):
            rc = proc.poll()
            if rc is not None:
                if rc != 0:
                    logger.warning("%s for issue #%d exited with code %d", backend, issue_number, rc)
                    if self.github_client:
                        comment = github.GitHubClient._format_comment(
                            f"{backend} Error",
                            [f"Exited with code {rc} on `{branch}`"],
                        )
                        self.github_client.add_issue_comment(issue_number, comment)
                    self.reminders_issue_ready.update_status_line(
                        reminder_id, f"⚠️ {backend} error (exit {rc}) — check logs"
                    )
                    if self.notes_client:
                        self.notes_client.log_event("claude_error", {
                            "issue_number": str(issue_number),
                            "branch": branch,
                            "exit_code": str(rc),
                        })
                else:
                    logger.info("%s for issue #%d finished successfully", backend, issue_number)
                    if self.github_client:
                        comment = github.GitHubClient._format_comment(
                            f"{backend} Success",
                            [f"Finished on `{branch}` — ready for review"],
                        )
                        self.github_client.add_issue_comment(issue_number, comment)
                    self.reminders_issue_ready.update_status_line(
                        reminder_id, "✅ Done — move to dev-review"
                    )
                    if self.notes_client:
                        self.notes_client.log_event("connector_finished", {
                            "issue_number": str(issue_number),
                            "branch": branch,
                        })
                del self._claude_procs[issue_number]

    def process(self) -> None:
        self._reap_claude_procs()
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
            if rem.id in self._completed_reminder_ids:
                self.reminders_done.complete_reminder(rem.id)
                continue
            mapping = self.store.get_mapping_by_reminder_id(rem.id)
            if mapping:
                if self._handle_done(rem, mapping): # Check return value
                    self.store.delete_mapping(rem.id)
            else:
                # No mapping means already processed in a previous run — just complete it
                logger.debug("Reminder %s in done list with no mapping (already processed) — completing", rem.id)
            self._completed_reminder_ids.add(rem.id)
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

            comment = github.GitHubClient._format_comment(
                "Issue Picked Up",
                [f"Branch: `{branch_name}`", f"`{self.connector.backend_name}` is working on this"],
                intro=f"apple-git picked up this issue: _{rem.name}_",
            )
            self.github_client.add_issue_comment(issue.number, comment)

            # Add brief AI analysis of the issue
            if self.issue_analyzer:
                analysis = self.issue_analyzer.analyze(
                    issue_title=rem.name,
                    issue_body=rem.body,
                )
                if analysis:
                    self.github_client.add_issue_comment(issue.number, analysis)

            self.reminders_issue_ready.update_status_line(
                rem.id, f"🔄 {self.connector.backend_name} working on issue #{issue.number}"
            )
            if self.notes_client:
                self.notes_client.log_event("issue_created", {
                    "reminder": rem.name,
                    "issue_number": str(issue.number),
                    "url": issue.url,
                    "branch": branch_name,
                })
            logger.info("Created issue #%d for reminder %s (branch: %s)", issue.number, rem.id, branch_name)
            self._spawn_connector(issue.number, rem.name, rem.body, branch_name, rem.id)

    def _spawn_connector(self, issue_number: int, title: str, body: str, branch: str, reminder_id: str = "") -> None:
        repo_path = self.settings.repo_path
        if not repo_path.exists():
            logger.warning("repo_path %s does not exist — skipping connector spawn", repo_path)
            return

        if not self.connector.is_available():
            logger.error("Connector '%s' is not available — is the CLI installed and on PATH?", self.connector.backend_name)
            return

        # Generate a concise file tree to give the agent context
        file_tree = tree.generate_tree(repo_path)
        
        prompt = f"""Work on GitHub issue #{issue_number}: {title}

{body}

Repository Structure:
{file_tree}

Steps:
1. git checkout {branch} (or git checkout -b {branch} main if it doesn't exist locally)
2. Implement the changes required by the issue
3. git add and git commit with a message referencing issue #{issue_number}
4. git push origin {branch}"""

        # Don't spawn a second process if one is already running for this issue
        existing = self._claude_procs.get(issue_number)
        if existing is not None and existing[0].poll() is None:
            logger.info("Connector already running for issue #%d (pid %d)", issue_number, existing[0].pid)
            return

        try:
            proc = self.connector.spawn(prompt, repo_path)
            self._claude_procs[issue_number] = (proc, branch, reminder_id)
            logger.info(
                "Spawned %s connector for issue #%d on branch %s in %s (pid %d)",
                self.connector.backend_name, issue_number, branch, repo_path, proc.pid,
            )
        except FileNotFoundError:
            logger.error("%s CLI not found — is it installed and on PATH?", self.connector.backend_name)
        except Exception as exc:
            logger.warning("Failed to spawn connector: %s", exc)

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
                if issue_number:
                    comment = github.GitHubClient._format_comment(
                        "PR Opened",
                        [f"PR #{pr.number} opened: {pr.url}"],
                    )
                    self.github_client.add_issue_comment(issue_number, comment)
                # Add summary of commits to PR
                commits = self.github_client.get_commits_on_branch(branch)
                if commits:
                    summary = "## Changes

" + "
".join(f"- {msg}" for msg in commits)
                    self.github_client.add_pr_comment(pr.number, summary)

                # Add AI-generated reviews if configured
                diff_files = self.github_client.get_pr_diff_files(pr.number)
                if self.pr_reviewer and diff_files:
                    code_review = self.pr_reviewer.review(
                        issue_number=issue_number,
                        issue_title=rem.name,
                        issue_body=rem.body,
                        diff_files=diff_files,
                    )
                    if code_review:
                        self.github_client.add_pr_comment(pr.number, code_review)

                if self.security_reviewer and diff_files:
                    security_review = self.security_reviewer.review(
                        issue_number=issue_number,
                        issue_title=rem.name,
                        diff_files=diff_files,
                    )
                    if security_review:
                        self.github_client.add_pr_comment(pr.number, security_review)

                self.reminders_review.update_status_line(rem.id, f"👀 PR #{pr.number} in review")
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
            self.reminders_review.update_status_line(rem.id, f"👀 PR #{pr_number} in review")
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

    def _handle_done(self, rem: reminders.Reminder, mapping: dict) -> bool:
        pr_number = mapping.get("github_pr_number")
        issue_number = mapping.get("github_issue_number")

        merge_successful = False
        if pr_number and self.github_client:
            if self.github_client.merge_pr(pr_number):
                pr = self.github_client.get_pr(pr_number)
                if pr:
                    note = f"Merged PR #{pr.number}: {pr.url}"
                    self.reminders_done.annotate_reminder(rem.id, note)
                if issue_number:
                    comment = github.GitHubClient._format_comment(
                        "PR Merged",
                        [f"PR #{pr.number} merged"],
                    )
                    self.github_client.add_issue_comment(issue_number, comment)
                    branch_name = f"issue-{issue_number}"
                    self.github_client.delete_branch(branch_name)
                if self.notes_client:
                    self.notes_client.log_event("pr_merged", {
                        "reminder": rem.name,
                        "pr_number": str(pr_number),
                    })
                logger.info("Merged PR #%d", pr_number)
                merge_successful = True
            else:
                logger.warning("Failed to merge PR #%d — moving back to review", pr_number)
                if issue_number:
                    comment = github.GitHubClient._format_comment(
                        "Merge Failed",
                        ["Automatic merge failed — likely conflicts", "Please resolve manually"],
                    )
                    self.github_client.add_issue_comment(issue_number, comment)
                
                self.reminders_done.update_status_line(rem.id, "⚠️ Merge Conflict — Fix manually")
                if self.notes_client:
                    self.notes_client.log_event("merge_failed", {
                        "reminder": rem.name,
                        "pr_number": str(pr_number),
                        "reason": "conflict",
                    })
                return False # Merge failed, do not mark as fully handled
        else: # No PR, but potentially an issue to close
            merge_successful = True # Nothing to merge, so 'merge' part is successful in its absence.

        if issue_number and self.github_client:
            self.github_client.close_issue(issue_number)
            if self.notes_client:
                self.notes_client.log_event("issue_closed", {
                    "reminder": rem.name,
                    "issue_number": str(issue_number),
                })
            logger.info("Closed issue #%d", issue_number)
            return True # Fully handled
        
        return merge_successful # Return if merge was successful, or if there was no PR to merge.

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
        for issue_number, (proc, branch, reminder_id) in self._claude_procs.items():
            if proc.poll() is None:
                logger.info("Terminating Claude Code for issue #%d (pid %d)", issue_number, proc.pid)
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._claude_procs.clear()
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
