from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass

from github import Github

logger = logging.getLogger("apple_git.github")


@dataclass
class GitHubIssue:
    number: int
    title: str
    body: str
    url: str
    state: str


@dataclass
class GitHubPR:
    number: int
    title: str
    body: str
    url: str
    state: str
    merged: bool


class GitHubClient:
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo_name = repo
        self._client = Github(token) if token else None
        self._repo = None
        self._default_branch: str | None = None

    @property
    def repo(self):
        if self._repo is None and self._client:
            try:
                self._repo = self._client.get_repo(self.repo_name)
            except Exception as exc:
                logger.error("Failed to get repo %s: %s", self.repo_name, exc)
        return self._repo

    def get_default_branch(self) -> str | None:
        if self._default_branch:
            return self._default_branch
        repo = self.repo
        if not repo:
            return None
        try:
            self._default_branch = str(repo.default_branch or "").strip() or None
            return self._default_branch
        except Exception as exc:
            logger.warning("Failed to get default branch for %s: %s", self.repo_name, exc)
            return None

    @staticmethod
    def _format_comment(heading: str, bullets: list[str], intro: str = "", outro: str = "") -> str:
        """Format a structured comment with heading, bullets, and footer."""
        lines = [f"### {heading}", ""]
        if intro:
            lines += [intro.strip(), ""]
        lines += [f"- {b}" for b in bullets if b.strip()]
        if outro:
            lines += ["", outro.strip()]
        lines += ["", "— apple-git 🤖"]
        return "\n".join(lines)

    def create_issue(self, title: str, body: str = "") -> GitHubIssue | None:
        if not self.repo:
            logger.error("GitHub repo not available")
            return None

        try:
            issue = self.repo.create_issue(title=title, body=body)
            logger.info("Created issue #%d: %s", issue.number, title)
            return GitHubIssue(
                number=issue.number,
                title=issue.title,
                body=issue.body or "",
                url=issue.html_url,
                state=issue.state,
            )
        except Exception as exc:
            logger.error("Failed to create issue: %s", exc)
            return None

    def close_issue(self, issue_number: int) -> bool:
        if not self.repo:
            return False

        try:
            issue = self.repo.get_issue(issue_number)
            issue.edit(state="closed")
            logger.info("Closed issue #%d", issue_number)
            return True
        except Exception as exc:
            logger.error("Failed to close issue #%d: %s", issue_number, exc)
            return False

    def get_issue(self, issue_number: int) -> GitHubIssue | None:
        if not self.repo:
            return None

        try:
            issue = self.repo.get_issue(issue_number)
            return GitHubIssue(
                number=issue.number,
                title=issue.title,
                body=issue.body or "",
                url=issue.html_url,
                state=issue.state,
            )
        except Exception as exc:
            logger.error("Failed to get issue #%d: %s", issue_number, exc)
            return None

    def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> GitHubPR | None:
        if not self.repo:
            return None

        try:
            pr = self.repo.create_pull(
                title=title,
                body=body,
                head=head,
                base=base,
            )
            logger.info("Created PR #%d: %s", pr.number, title)
            return GitHubPR(
                number=pr.number,
                title=pr.title,
                body=pr.body or "",
                url=pr.html_url,
                state=pr.state,
                merged=pr.merged,
            )
        except Exception as exc:
            logger.error("Failed to create PR: %s", exc)
            return None

    def merge_pr(self, pr_number: int) -> bool:
        if not self.repo:
            return False

        try:
            pr = self.repo.get_pull(pr_number)
            pr.merge()
            logger.info("Merged PR #%d", pr_number)
            return True
        except Exception as exc:
            logger.error("Failed to merge PR #%d: %s", pr_number, exc)
            return False

    def branch_has_commits_ahead(self, branch_name: str, base: str = "main") -> bool:
        """Return True if branch has at least one commit not in base."""
        if not self.repo:
            return False
        try:
            comparison = self.repo.compare(base, branch_name)
            return comparison.ahead_by > 0
        except Exception as exc:
            logger.warning("Could not compare %s..%s: %s", base, branch_name, exc)
            return False

    def ensure_branch(self, branch_name: str, base: str = "main") -> bool:
        """Create branch from base if it doesn't exist. Returns True if ready."""
        if not self.repo:
            return False
        try:
            self.repo.get_branch(branch_name)
            return True  # already exists
        except Exception:
            try:
                ref = self.repo.get_branch(base)
                self.repo.create_git_ref(
                    ref=f"refs/heads/{branch_name}",
                    sha=ref.commit.sha,
                )
                logger.info("Created branch %s from %s", branch_name, base)
                return True
            except Exception as exc:
                logger.error("Failed to create branch %s: %s", branch_name, exc)
                return False

    def get_pr(self, pr_number: int) -> GitHubPR | None:
        if not self.repo:
            return None

        try:
            pr = self.repo.get_pull(pr_number)
            return GitHubPR(
                number=pr.number,
                title=pr.title,
                body=pr.body or "",
                url=pr.html_url,
                state=pr.state,
                merged=pr.merged,
            )
        except Exception as exc:
            logger.error("Failed to get PR #%d: %s", pr_number, exc)
            return None


    def add_issue_comment(self, issue_number: int, body: str) -> bool:
        if not self.repo:
            return False
        try:
            self.repo.get_issue(issue_number).create_comment(body)
            return True
        except Exception as exc:
            logger.warning("Failed to comment on issue #%d: %s", issue_number, exc)
            return False

    def get_issue_comment_by_marker(self, issue_number: int, marker: str) -> str:
        if not self.repo:
            return ""
        try:
            issue = self.repo.get_issue(issue_number)
            for comment in issue.get_comments():
                body = comment.body or ""
                if marker in body:
                    return body
        except Exception as exc:
            logger.warning(
                "Failed to get issue comment for issue #%d with marker %r: %s",
                issue_number,
                marker,
                exc,
            )
        return ""

    def upsert_issue_comment(self, issue_number: int, body: str, marker: str) -> bool:
        if not self.repo:
            return False
        try:
            issue = self.repo.get_issue(issue_number)
            for comment in issue.get_comments():
                existing_body = comment.body or ""
                if marker in existing_body:
                    comment.edit(body)
                    return True
            issue.create_comment(body)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to upsert issue comment for issue #%d with marker %r: %s",
                issue_number,
                marker,
                exc,
            )
            return False

    def add_pr_comment(self, pr_number: int, body: str) -> bool:
        if not self.repo:
            return False
        try:
            self.repo.get_issue(pr_number).create_comment(body)
            return True
        except Exception as exc:
            logger.warning("Failed to comment on PR #%d: %s", pr_number, exc)
            return False

    def delete_branch(self, branch_name: str) -> bool:
        if not self.repo:
            return False

        try:
            self.repo.get_git_ref(f"heads/{branch_name}").delete()
            logger.info("Deleted branch %s", branch_name)
            return True
        except Exception as exc:
            logger.warning("Failed to delete branch %s: %s", branch_name, exc)
            return False

    def get_commits_on_branch(self, branch_name: str, base: str = "main") -> list[str]:
        """Get commit messages on branch that aren't in base. Returns list of commit messages."""
        if not self.repo:
            return []
        try:
            comparison = self.repo.compare(base, branch_name)
            return [commit.commit.message.split("\n")[0] for commit in comparison.commits]
        except Exception as exc:
            logger.warning("Failed to get commits for %s: %s", branch_name, exc)
            return []

    def get_pr_diff_files(self, pr_number: int) -> list[dict]:
        """Return list of {filename, patch} dicts for all changed files in the PR."""
        if not self.repo:
            return []
        try:
            pr = self.repo.get_pull(pr_number)
            return [
                {"filename": f.filename, "patch": f.patch or ""}
                for f in pr.get_files()
            ]
        except Exception as exc:
            logger.warning("Failed to get PR diff files for #%d: %s", pr_number, exc)
            return []

    def delete_branches_matching(self, pattern: str) -> int:
        """Delete all branches matching pattern (e.g., 'issue-*'). Returns count deleted."""
        if not self.repo:
            return 0

        count = 0
        try:
            for branch in self.repo.get_branches():
                if fnmatch.fnmatch(branch.name, pattern):
                    try:
                        self.repo.get_git_ref(f"heads/{branch.name}").delete()
                        logger.info("Deleted branch %s", branch.name)
                        count += 1
                    except Exception as exc:
                        logger.warning("Failed to delete branch %s: %s", branch.name, exc)
            logger.info("Deleted %d branches matching %s", count, pattern)
            return count
        except Exception as exc:
            logger.error("Failed to list branches: %s", exc)
            return 0


def extract_pr_number(text: str) -> int | None:
    pattern = r"github\.com/[\w-]+/[\w-]+/pull/(\d+)"
    match = re.search(pattern, text)
    if match:
        return int(match.group(1))
    return None
