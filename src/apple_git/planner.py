"""AI issue planning via Claude API."""
from __future__ import annotations

import logging

from anthropic import Anthropic

logger = logging.getLogger("apple_git.planner")


class IssuePlanner:
    """Generate a structured implementation plan for a GitHub issue."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        self.api_key = api_key
        self.model = model
        self.client = Anthropic(api_key=api_key)

    def plan(self, *, prompt: str) -> str:
        """Return a structured implementation plan or an empty string on failure."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text if response.content else ""
        except Exception as exc:
            logger.warning("Failed to generate implementation plan: %s", exc)
            return ""
