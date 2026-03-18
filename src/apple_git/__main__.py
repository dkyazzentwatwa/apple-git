from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
import subprocess
import sys
import uuid
from pathlib import Path

from . import (
    connector,
    github,
    issue_analyzer,
    notes,
    planner,
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
PLAN_COMMENT_MARKER = "<!-- apple-git:implementation-plan -->"


class AppleGit:
    def __init__(self, settings: AppleGitSettings):
        self.settings = settings
        self.store = store.SQLiteStore(settings.db_path)
        self.reminders_issue_plan = reminders.RemindersClient(settings.reminders.list_issue_plan)
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
        self.issue_planner = None
        self.issue_analyzer = None
        self.pr_reviewer = None
        self.security_reviewer = None
        if settings.anthropic_api_key:
            self.issue_planner = planner.IssuePlanner(settings.anthropic_api_key)
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
        self._connector_run_ids: dict[int, str] = {}

    def bootstrap(self) -> None:
        self.store.bootstrap()
        logger.info("apple-git initialized")

    def _resolve_base_branch(self) -> str:
        configured = self.settings.github.base_branch.strip()
        if configured:
            return configured
        if self.github_client:
            resolved = self.github_client.get_default_branch()
            if resolved:
                return resolved
        return "main"

    def _write_connector_note(self, log_path: Path, message: str) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")

    def _build_issue_plan_prompt(
        self,
        *,
        issue_number: int,
        title: str,
        body: str,
        repo_path: Path,
        operator_feedback: str = "",
    ) -> str:
        file_tree = tree.generate_tree(repo_path)
        sanitized_body = reminders.extract_operator_feedback(body)
        body_block = sanitized_body or body.strip() or "(no issue body provided)"
        feedback_block = (
            f"\nOperator feedback:\n{operator_feedback.strip()}\n"
            if operator_feedback.strip()
            else ""
        )
        return f"""You are preparing an implementation plan for GitHub issue #{issue_number}.

Issue title:
{title}

Issue body:
{body_block}
{feedback_block}

Repository context:
{file_tree}

Use only the issue title, issue body, operator feedback, and repository context provided above. Do not assume unstated product requirements. Do not invent scope. Prefer the smallest viable change set.

Return exactly these sections and nothing else:

## Problem
## Assumptions
## Proposed changes
## Likely modules/files to change
## Tests
## Risks / edge cases / confirmations needed
## Ready for implementation

Requirements:
- "Problem" must be exactly one sentence.
- "Assumptions" must be a bullet list.
- "Proposed changes" must contain 3-7 numbered steps.
- "Likely modules/files to change" must be a bullet list.
- "Tests" must be a bullet list.
- "Risks / edge cases / confirmations needed" must be a bullet list.
- "Ready for implementation" must be 1-2 sentences.
- If key details are missing, say so explicitly in "Risks / edge cases / confirmations needed".
- Keep the plan at planning level. Do not write code.
- Do not include any text before, after, or outside the required sections.
"""

    def _build_connector_prompt(
        self,
        *,
        issue_number: int,
        issue_url: str,
        title: str,
        body: str,
        approved_plan: str = "",
        branch: str,
        base_branch: str,
        repo_path: Path,
    ) -> str:
        file_tree = tree.generate_tree(repo_path)
        body_block = body.strip() or "(no issue body provided)"
        approved_plan_block = approved_plan.strip() or "- No approved plan comment was provided. Use the issue title, issue body, and repository context only."
        return f"""You are implementing the approved plan for GitHub issue #{issue_number}.

Issue title:
{title}

Issue URL: {issue_url or "(not available)"}

Issue body:
{body_block}

Approved plan:
{approved_plan_block}

Repository context:
{file_tree}

Branch:
{branch}

Base branch:
{base_branch}

Repository path:
{repo_path}

Follow the approved plan exactly and make the smallest correct change set.

Required workflow:
1. Checkout the target branch `{branch}`. Create it from the repository default branch `{base_branch}` if it does not already exist locally.
2. Implement only the approved plan.
3. Add or update tests for changed behavior.
4. Run the smallest relevant test subset.
5. Commit with a clear message referencing issue #{issue_number}.
6. Push the branch.

Hard rules:
- Do not redesign the feature unless the approved plan explicitly requires it.
- Do not expand scope.
- Do not touch unrelated files.
- If the approved plan conflicts with the repository state, follow the repository state and report the mismatch in "Summary".
- Do not fabricate work, file changes, test execution, or results.
- If tests cannot be run, say so explicitly in "Test results".
- If a required detail is missing or you are otherwise blocked, stop immediately.

If blocked, output exactly this format and nothing else:

BLOCKED:
- <reason 1>
- <reason 2>

If successful, after implementation is complete, output exactly these sections and nothing else:

## Summary
## Files changed
## Tests updated
## Test commands run
## Test results
## Commit message

Output requirements:
- "Summary" must be 1-3 short bullets.
- "Files changed" must be a bullet list of repo-relative paths.
- "Tests updated" must be a bullet list. If no tests were changed, write `- None`.
- "Test commands run" must be a bullet list of exact commands. If none were run, write `- None`.
- "Test results" must be a bullet list with concise, factual outcomes.
- "Commit message" must be exactly one line.
- Do not include any text before, after, or outside the required output format.
"""

    def _reap_claude_procs(self) -> None:
        """Reap any finished connector processes and log their exit codes."""
        backend = self.connector.backend_name
        for issue_number, (proc, branch, reminder_id) in list(self._claude_procs.items()):
            rc = proc.poll()
            if rc is not None:
                run_id = self._connector_run_ids.pop(issue_number, "")
                run = self.store.get_connector_run(run_id) if run_id else None
                stderr_log_path = run.get("stderr_log_path", "") if run else ""
                if rc != 0:
                    logger.warning("%s for issue #%d exited with code %d", backend, issue_number, rc)
                    if run_id:
                        self.store.update_connector_run(
                            run_id,
                            status="failed",
                            exit_code=rc,
                            failure_reason=f"connector exited with code {rc}",
                        )
                    if self.github_client:
                        comment = github.GitHubClient._format_comment(
                            f"{backend} Error",
                            [
                                f"Exited with code {rc} on `{branch}`",
                                f"Run ID: `{run_id}`" if run_id else "",
                                f"stderr log: `{stderr_log_path}`" if stderr_log_path else "",
                            ],
                        )
                        self.github_client.add_issue_comment(issue_number, comment)
                    status_suffix = f"see run {run_id}" if run_id else "check logs"
                    self.reminders_issue_ready.update_status_line(
                        reminder_id, f"⚠️ {backend} error (exit {rc}) — {status_suffix}"
                    )
                    if self.notes_client:
                        payload = {
                            "issue_number": str(issue_number),
                            "branch": branch,
                            "exit_code": str(rc),
                        }
                        if run_id:
                            payload["run_id"] = run_id
                        self.notes_client.log_event("claude_error", payload)
                else:
                    logger.info("%s for issue #%d finished successfully", backend, issue_number)
                    if run_id:
                        self.store.update_connector_run(run_id, status="succeeded", exit_code=0)
                    if self.github_client:
                        comment = github.GitHubClient._format_comment(
                            f"{backend} Success",
                            [
                                f"Finished on `{branch}` — ready for review",
                                f"Run ID: `{run_id}`" if run_id else "",
                            ],
                        )
                        self.github_client.add_issue_comment(issue_number, comment)
                    self.reminders_issue_ready.update_status_line(
                        reminder_id, "✅ Done — move to dev-review"
                    )
                    if self.notes_client:
                        payload = {
                            "issue_number": str(issue_number),
                            "branch": branch,
                        }
                        if run_id:
                            payload["run_id"] = run_id
                        self.notes_client.log_event("connector_finished", payload)
                del self._claude_procs[issue_number]

    def process(self) -> None:
        self._reap_claude_procs()
        # Process reminders in issue-plan list: create issues and structured plans
        for rem in self.reminders_issue_plan.fetch_all():
            mapping = self.store.get_mapping_by_reminder_id(rem.id)
            if mapping is None:
                self._create_issue_plan(rem)
            else:
                self.store.update_section(rem.id, self.settings.reminders.list_issue_plan)
                self._ensure_issue_plan(rem, mapping)

        # Process reminders in issue-ready list: start code generation from approved plans
        for rem in self.reminders_issue_ready.fetch_all():
            mapping = self.store.get_mapping_by_reminder_id(rem.id)
            if mapping:
                self.store.update_section(rem.id, self.settings.reminders.list_issue_ready)
                self._handle_issue_ready(rem, mapping)
            else:
                logger.warning("Reminder %s in issue-ready list but has no issue mapping — skipping", rem.id)
                self.reminders_issue_ready.update_status_line(
                    rem.id, "⚠️ no issue mapping — move back to issue-plan"
                )

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
                if self._handle_done(rem, mapping):
                    self.store.delete_mapping(rem.id)
                    self._completed_reminder_ids.add(rem.id)
                    self.reminders_done.complete_reminder(rem.id)
                # If _handle_done returned False (e.g. merge conflict), leave mapping + reminder intact
            else:
                # No mapping means already processed in a previous run — just complete it
                logger.debug("Reminder %s in done list with no mapping (already processed) — completing", rem.id)
                self._completed_reminder_ids.add(rem.id)
                self.reminders_done.complete_reminder(rem.id)

    def _format_plan_comment(self, plan_text: str) -> str:
        return (
            f"{PLAN_COMMENT_MARKER}\n"
            "## apple-git implementation plan\n\n"
            f"{plan_text.strip()}"
        )

    def _generate_issue_plan_comment(
        self,
        issue_number: int,
        rem: reminders.Reminder,
        *,
        operator_feedback: str = "",
    ) -> bool:
        if not self.issue_planner or not self.github_client:
            return False

        plan_prompt = self._build_issue_plan_prompt(
            issue_number=issue_number,
            title=rem.name,
            body=rem.body,
            repo_path=self.settings.repo_path,
            operator_feedback=operator_feedback,
        )
        plan_text = self.issue_planner.plan(prompt=plan_prompt)
        if not plan_text:
            return False
        return self.github_client.upsert_issue_comment(
            issue_number,
            self._format_plan_comment(plan_text),
            PLAN_COMMENT_MARKER,
        )

    def _create_issue_plan(self, rem: reminders.Reminder) -> None:
        if not self.github_client:
            logger.warning("GitHub client not configured")
            return

        issue = self.github_client.create_issue(rem.name, rem.body)
        if issue:
            self.store.upsert_issue_mapping(
                reminder_id=rem.id,
                github_issue_number=issue.number,
                section=self.settings.reminders.list_issue_plan,
                reminder_title=rem.name,
            )
            branch_name = f"issue-{issue.number}"
            self.reminders_issue_plan.update_body_tags(rem.id, "", f"#branch:{branch_name}")
            self.reminders_issue_plan.set_reminder_url(rem.id, issue.url)
            self.reminders_issue_plan.annotate_reminder(rem.id, f"Issue #{issue.number}")

            comment = github.GitHubClient._format_comment(
                "Issue Picked Up",
                [f"Branch: `{branch_name}`", f"Requested connector: `{self.connector.backend_name}`"],
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

            if not self.issue_planner:
                self.reminders_issue_plan.update_status_line(
                    rem.id, "⚠️ planning unavailable — issue created but plan not generated"
                )
            else:
                if self._generate_issue_plan_comment(issue.number, rem):
                    self.reminders_issue_plan.update_status_line(
                        rem.id, "📝 Plan ready — move to issue-ready to start coding"
                    )
                else:
                    self.reminders_issue_plan.update_status_line(
                        rem.id, "⚠️ planning failed — issue created but plan not generated"
                    )

            if self.notes_client:
                self.notes_client.log_event("issue_created", {
                    "reminder": rem.name,
                    "issue_number": str(issue.number),
                    "url": issue.url,
                    "branch": branch_name,
                })
            logger.info("Created issue #%d for reminder %s (branch: %s)", issue.number, rem.id, branch_name)

    def _ensure_issue_plan(self, rem: reminders.Reminder, mapping: dict) -> None:
        if not self.github_client:
            return
        issue_number = mapping.get("github_issue_number")
        if not issue_number:
            return
        if reminders.has_tag(rem.body, "#regen-plan"):
            operator_feedback = reminders.extract_operator_feedback(rem.body)
            if self._generate_issue_plan_comment(
                issue_number,
                rem,
                operator_feedback=operator_feedback,
            ):
                self.reminders_issue_plan.update_body_tags(rem.id, "#regen-plan", "")
                self.reminders_issue_plan.update_status_line(
                    rem.id, "📝 Plan regenerated — review and move to issue-ready when approved"
                )
            else:
                self.reminders_issue_plan.update_status_line(
                    rem.id, "⚠️ plan regeneration failed — fix feedback and try again"
                )
            return

        existing_plan = self.github_client.get_issue_comment_by_marker(issue_number, PLAN_COMMENT_MARKER)
        if existing_plan.strip():
            return

        if self._generate_issue_plan_comment(issue_number, rem):
            self.reminders_issue_plan.update_status_line(
                rem.id, "📝 Plan ready — move to issue-ready to start coding"
            )
        else:
            self.reminders_issue_plan.update_status_line(
                rem.id, "⚠️ planning failed — issue created but plan not generated"
            )

    def _handle_issue_ready(self, rem: reminders.Reminder, mapping: dict) -> None:
        if not self.github_client:
            logger.warning("GitHub client not configured")
            return

        issue_number = mapping.get("github_issue_number")
        if not issue_number:
            logger.warning("Reminder %s in issue-ready list but has no GitHub issue number", rem.id)
            return

        approved_plan = self.github_client.get_issue_comment_by_marker(issue_number, PLAN_COMMENT_MARKER)
        if not approved_plan.strip():
            self.reminders_issue_ready.update_status_line(
                rem.id, "⚠️ no approved plan found — move back to issue-plan"
            )
            return

        branch_name = reminders.extract_branch_tag(rem.body) or f"issue-{issue_number}"
        if reminders.extract_branch_tag(rem.body) is None:
            self.reminders_issue_ready.update_body_tags(rem.id, "", f"#branch:{branch_name}")

        self._spawn_connector(
            issue_number,
            rem.name,
            rem.body,
            branch_name,
            rem.id,
            rem.url,
            approved_plan=approved_plan,
        )

    def _spawn_connector(
        self,
        issue_number: int,
        title: str,
        body: str,
        branch: str,
        reminder_id: str = "",
        issue_url: str = "",
        approved_plan: str = "",
    ) -> None:
        repo_path = self.settings.repo_path
        logs_dir = self.settings.connector_logs_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex[:12]
        stdout_path = logs_dir / f"{run_id}.stdout.log"
        stderr_path = logs_dir / f"{run_id}.stderr.log"
        base_branch = self._resolve_base_branch()
        prompt = self._build_connector_prompt(
            issue_number=issue_number,
            issue_url=issue_url,
            title=title,
            body=body,
            approved_plan=approved_plan,
            branch=branch,
            base_branch=base_branch,
            repo_path=repo_path,
        )
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        self.store.create_connector_run(
            run_id=run_id,
            reminder_id=reminder_id,
            github_issue_number=issue_number,
            backend=self.connector.backend_name,
            branch=branch,
            status="pending",
            prompt_hash=prompt_hash,
            stdout_log_path=str(stdout_path),
            stderr_log_path=str(stderr_path),
        )
        if not repo_path.exists():
            logger.warning("repo_path %s does not exist — skipping connector spawn", repo_path)
            self.store.update_connector_run(
                run_id,
                status="skipped",
                failure_reason=f"repo_path does not exist: {repo_path}",
            )
            self._write_connector_note(stderr_path, f"repo_path does not exist: {repo_path}")
            self.reminders_issue_ready.update_status_line(
                reminder_id, "⚠️ repo path missing — issue created but worker not started"
            )
            return

        if not self.connector.is_available():
            logger.error("Connector '%s' is not available — is the CLI installed and on PATH?", self.connector.backend_name)
            self.store.update_connector_run(
                run_id,
                status="failed",
                failure_reason=f"Connector '{self.connector.backend_name}' is not available",
            )
            self._write_connector_note(
                stderr_path,
                f"Connector '{self.connector.backend_name}' is not available — issue #{issue_number} was not started.",
            )
            self.reminders_issue_ready.update_status_line(
                reminder_id,
                f"⚠️ {self.connector.backend_name} unavailable — issue created but worker not started",
            )
            return

        # Don't spawn a second process if one is already running for this issue
        existing = self._claude_procs.get(issue_number)
        if existing is not None and existing[0].poll() is None:
            logger.info("Connector already running for issue #%d (pid %d)", issue_number, existing[0].pid)
            self.store.update_connector_run(
                run_id,
                status="skipped",
                failure_reason=f"connector already running for issue #{issue_number}",
            )
            return

        try:
            self.store.update_connector_run(run_id, status="running")
            with stdout_path.open("ab") as stdout_handle, stderr_path.open("ab") as stderr_handle:
                proc = self.connector.spawn(
                    prompt,
                    repo_path,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                )
            self._claude_procs[issue_number] = (proc, branch, reminder_id)
            self._connector_run_ids[issue_number] = run_id
            self.store.update_connector_run(run_id, status="running", pid=proc.pid)
            self.reminders_issue_ready.update_status_line(
                reminder_id, f"🔄 {self.connector.backend_name} working on issue #{issue_number}"
            )
            logger.info(
                "Spawned %s connector for issue #%d on branch %s in %s (pid %d)",
                self.connector.backend_name, issue_number, branch, repo_path, proc.pid,
            )
        except FileNotFoundError:
            logger.error("%s CLI not found — is it installed and on PATH?", self.connector.backend_name)
            self.store.update_connector_run(
                run_id,
                status="failed",
                failure_reason=f"{self.connector.backend_name} CLI not found",
            )
            self._write_connector_note(stderr_path, f"{self.connector.backend_name} CLI not found.")
            self.reminders_issue_ready.update_status_line(
                reminder_id,
                f"⚠️ {self.connector.backend_name} unavailable — issue created but worker not started",
            )
        except Exception as exc:
            logger.warning("Failed to spawn connector: %s", exc)
            self.store.update_connector_run(
                run_id,
                status="failed",
                failure_reason=str(exc),
            )
            self._write_connector_note(stderr_path, f"Failed to spawn connector: {exc}")
            self.reminders_issue_ready.update_status_line(
                reminder_id,
                f"⚠️ {self.connector.backend_name} failed to start — see run {run_id}",
            )

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
            base_branch = self._resolve_base_branch()
            self.github_client.ensure_branch(branch, base=base_branch)
            if not self.github_client.branch_has_commits_ahead(branch, base=base_branch):
                logger.info("Branch %s has no commits ahead of main yet — skipping PR creation", branch)
                return
            pr = self.github_client.create_pr(
                title=rem.name,
                body=rem.body,
                head=branch,
                base=base_branch,
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
                commits = self.github_client.get_commits_on_branch(branch, base=base_branch)
                if commits:
                    summary = "## Changes\n\n" + "\n".join(f"- {msg}" for msg in commits)
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
        merge_requested = reminders.has_merge_tag(rem.body)

        merge_successful = False
        if pr_number and self.github_client:
            pr = self.github_client.get_pr(pr_number)
            if not merge_requested:
                if pr and pr.merged:
                    merge_successful = True
                else:
                    self.reminders_done.update_status_line(
                        rem.id, "⏸️ PR open — merge manually or add #merge"
                    )
                    if self.notes_client:
                        self.notes_client.log_event("merge_pending", {
                            "reminder": rem.name,
                            "pr_number": str(pr_number),
                        })
                    return False
            elif self.github_client.merge_pr(pr_number):
                pr = self.github_client.get_pr(pr_number)
                if pr:
                    note = f"Merged PR #{pr.number}: {pr.url}"
                    self.reminders_done.annotate_reminder(rem.id, note)
                if issue_number:
                    comment = github.GitHubClient._format_comment(
                        "PR Merged",
                        [f"PR #{pr_number} merged"],
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
                    proc.wait()
                run_id = self._connector_run_ids.get(issue_number, "")
                if run_id:
                    self.store.update_connector_run(
                        run_id,
                        status="terminated",
                        exit_code=proc.returncode,
                        failure_reason="shutdown requested",
                    )
        self._claude_procs.clear()
        self._connector_run_ids.clear()
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
