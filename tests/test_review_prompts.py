from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from apple_git.reviewer import PRReviewer
from apple_git.security_reviewer import SecurityReviewer


def _mock_anthropic_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


@patch("apple_git.reviewer.Anthropic")
def test_pr_reviewer_uses_structured_prompt(mock_anthropic):
    client = MagicMock()
    client.messages.create.return_value = _mock_anthropic_response("## Verdict")
    mock_anthropic.return_value = client

    reviewer = PRReviewer("test-key")
    result = reviewer.review(
        issue_number=12,
        issue_title="Tighten PR review output",
        issue_body="Need deterministic review sections.",
        diff_files=[{"filename": "src/app.py", "patch": "+print('hi')"}],
    )

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Return exactly these sections and nothing else:" in prompt
    assert "## Verdict" in prompt
    assert "## What changed" in prompt
    assert "## Findings" in prompt
    assert "## Missing tests" in prompt
    assert "## Approval" in prompt
    assert "`APPROVE` or `CHANGES_REQUESTED`" in prompt
    assert result == "## Verdict"


@patch("apple_git.security_reviewer.Anthropic")
def test_security_reviewer_uses_structured_prompt(mock_anthropic):
    client = MagicMock()
    client.messages.create.return_value = _mock_anthropic_response("## Verdict")
    mock_anthropic.return_value = client

    reviewer = SecurityReviewer("test-key")
    result = reviewer.review(
        issue_number=34,
        issue_title="Tighten security review output",
        diff_files=[{"filename": "src/app.py", "patch": "+subprocess.run(user_input)"}],
    )

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Return exactly these sections and nothing else:" in prompt
    assert "## Verdict" in prompt
    assert "## Findings" in prompt
    assert "## Required follow-up" in prompt
    assert "`NO_SECURITY_FINDINGS`" in prompt
    assert "`SECURITY_FINDINGS: <count>`" in prompt
    assert "unsafe subprocess usage" in prompt
    assert result == "## Verdict"
