from __future__ import annotations

from unittest.mock import MagicMock, patch

from apple_git.reminders import RemindersClient


def test_fetch_all_uses_json_output_and_preserves_special_chars():
    client = RemindersClient("dev-issue-ready")
    result = MagicMock()
    result.returncode = 0
    result.stdout = (
        '[{"id":"rem-1","name":"Title","body":"Line 1 | table\\n~~~ marker","url":"https://example.com",'
        '"list_name":"dev-issue-ready"}]'
    )

    with (
        patch.object(client, "_resolve_list_selector", return_value={"id": "list-123", "name": "dev-issue-ready"}),
        patch("apple_git.reminders.subprocess.run", return_value=result) as mock_run,
    ):
        reminders = client.fetch_all()

    assert len(reminders) == 1
    assert reminders[0].id == "rem-1"
    assert reminders[0].body == "Line 1 | table\n~~~ marker"
    assert reminders[0].url == "https://example.com"
    assert reminders[0].list_name == "dev-issue-ready"
    assert mock_run.call_args.args[0][:3] == ["osascript", "-l", "JavaScript"]


def test_fetch_all_returns_empty_list_on_invalid_json():
    client = RemindersClient("dev-issue-ready")
    result = MagicMock()
    result.returncode = 0
    result.stdout = "not json"

    with (
        patch.object(client, "_resolve_list_selector", return_value={"id": "list-123", "name": "dev-issue-ready"}),
        patch("apple_git.reminders.subprocess.run", return_value=result),
    ):
        reminders = client.fetch_all()

    assert reminders == []


def test_fetch_all_handles_null_body_and_url_without_failing():
    client = RemindersClient("issue-plan")
    result = MagicMock()
    result.returncode = 0
    result.stdout = (
        '[{"id":"rem-1","name":"Title","body":null,"url":"","list_name":"issue-plan"}]'
    )

    with (
        patch.object(client, "_resolve_list_selector", return_value={"id": "list-123", "name": "issue-plan"}),
        patch("apple_git.reminders.subprocess.run", return_value=result),
    ):
        reminders = client.fetch_all()

    assert len(reminders) == 1
    assert reminders[0].body == ""
    assert reminders[0].url == ""
