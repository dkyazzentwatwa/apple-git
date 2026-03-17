from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from github import Github
from github.Issue import Issue
from github.PullRequest import PullRequest

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

    @property
    def repo(self):
        if self._repo is None and self._client:
            try:
                self._repo = self._client.get_repo(self.repo_name)
            except Exception as exc:
                logger.error("Failed to get repo %s: %s", self.repo_name, exc)
        return self._repo

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


def extract_pr_number(text: str) -> int | None:
    pattern = r"github\.com/[\w-]+/[\w-]+/pull/(\d+)"
    match = re.search(pattern, text)
    if match:
        return int(match.group(1))
    return None
