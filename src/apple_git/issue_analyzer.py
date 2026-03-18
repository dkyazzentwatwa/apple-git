"""AI issue analysis via Claude API."""
from __future__ import annotations

import logging

from anthropic import Anthropic

logger = logging.getLogger("apple_git.issue_analyzer")


class IssueAnalyzer:
    """Brief AI analysis of GitHub issues."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        self.api_key = api_key
        self.model = model
        self.client = Anthropic(api_key=api_key)

    def analyze(self, *, issue_title: str, issue_body: str) -> str:
        """Returns a very brief one-line analysis, or empty string on failure."""
        prompt = (
            "Analyze this GitHub issue in one brief sentence (under 15 words). "
            "Provide a quick assessment: what type of issue is this? "
            "Examples: 'Bug report in X subsystem', 'Feature request for Y', 'Documentation clarification'.\n\n"
            f"Title: {issue_title}\n"
            f"Body: {issue_body[:500]}"
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text if response.content else ""
        except Exception as exc:
            logger.warning("Failed to analyze issue: %s", exc)
            return ""
