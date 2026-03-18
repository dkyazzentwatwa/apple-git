from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("apple_git.reminders")
REMINDERS_APP_TARGET = 'application id "com.apple.reminders"'


@dataclass
class Reminder:
    id: str
    name: str
    body: str
    url: str
    list_name: str
    creation_date: str
    due_date: str


class RemindersClient:
    def __init__(self, list_name: str = "kanban"):
        self.list_name = list_name
        self._resolved_list_cache: dict | None = None

    def _resolve_list_selector(self) -> dict | None:
        from . import apple_tools
        resolved = apple_tools.reminders_resolve_list_selector(self.list_name)
        if resolved is None:
            logger.warning("Unable to resolve Reminders selector %r", self.list_name)
            return None
        return {
            "id": str(resolved.get("id", "")),
            "name": str(resolved.get("name", "")),
            "path": str(resolved.get("path", "")),
            "source": str(resolved.get("source", "")),
        }

    def fetch_all(self) -> list[Reminder]:
        resolved_list = self._resolve_list_selector()
        if resolved_list is None:
            return []

        escaped_list_id = json.dumps(str(resolved_list.get("id", "")))
        escaped_list_name = json.dumps(str(resolved_list.get("name", self.list_name)))

        script = f"""
        const app = Application("Reminders");
        let taskList = null;
        const listId = {escaped_list_id};
        const listName = {escaped_list_name};

        if (listId) {{
            const matches = app.lists.whose({{ id: listId }})();
            if (matches.length > 0) {{
                taskList = matches[0];
            }}
        }}

        if (!taskList) {{
            taskList = app.lists.byName(listName);
        }}

        const reminderListName = taskList.name();
        const rows = taskList.reminders().map((r) => ({{
            id: r.id(),
            name: r.name(),
            body: r.body() || "",
            url: r.url() || "",
            list_name: reminderListName,
        }}));

        JSON.stringify(rows);
        """

        try:
            result = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", script],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.warning("Failed to fetch reminders: %s", result.stderr)
                return []
            return self._parse_output(result.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("Timed out fetching reminders")
            return []
        except FileNotFoundError:
            logger.error("osascript not found - requires macOS")
            return []
        except Exception as exc:
            logger.warning("Error fetching reminders: %s", exc)
            return []

    def _parse_output(self, output: str) -> list[Reminder]:
        try:
            rows = json.loads(output.strip() or "[]")
        except json.JSONDecodeError:
            logger.warning("Failed to parse reminders JSON output")
            return []
        if not isinstance(rows, list):
            return []

        reminders: list[Reminder] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            reminders.append(
                Reminder(
                    id=str(row.get("id", "")).strip(),
                    name=str(row.get("name", "")).strip(),
                    body=str(row.get("body", "")),
                    url=str(row.get("url", "")),
                    list_name=str(row.get("list_name", "")).strip(),
                    creation_date="",
                    due_date="",
                )
            )
        return reminders

    def complete_reminder(self, reminder_id: str) -> bool:
        resolved_list = self._resolve_list_selector()
        if resolved_list is None:
            return False

        if resolved_list.get("id"):
            escaped_list_id = resolved_list["id"].replace('"', '\\"')
            target_list_clause = f'set taskList to first list whose id is "{escaped_list_id}"'
        else:
            escaped_list_name = resolved_list["name"].replace('"', '\\"')
            target_list_clause = f'set taskList to list "{escaped_list_name}"'

        escaped_id = reminder_id.replace('"', '\\"')
        script = f'''
        tell {REMINDERS_APP_TARGET}
            try
                {target_list_clause}
                set matchedReminder to (first reminder of taskList whose id is "{escaped_id}")
                set completed of matchedReminder to true
                return "ok"
            on error errMsg
                return "error: " & errMsg
            end try
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0 and "ok" in result.stdout
        except Exception as exc:
            logger.warning("Error completing reminder: %s", exc)
            return False

    def annotate_reminder(self, reminder_id: str, note: str) -> bool:
        resolved_list = self._resolve_list_selector()
        if resolved_list is None:
            return False

        if resolved_list.get("id"):
            escaped_list_id = resolved_list["id"].replace('"', '\\"')
            target_list_clause = f'set taskList to first list whose id is "{escaped_list_id}"'
        else:
            escaped_list_name = resolved_list["name"].replace('"', '\\"')
            target_list_clause = f'set taskList to list "{escaped_list_name}"'

        escaped_note = note.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        escaped_id = reminder_id.replace('"', '\\"')

        script = f'''
        tell {REMINDERS_APP_TARGET}
            try
                {target_list_clause}
                set matchedReminder to (first reminder of taskList whose id is "{escaped_id}")
                set existingBody to body of matchedReminder
                if existingBody is missing value then
                    set body of matchedReminder to "{escaped_note}"
                else
                    set body of matchedReminder to existingBody & "\\n\\n" & "{escaped_note}"
                end if
                return "ok"
            on error errMsg
                return "error: " & errMsg
            end try
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0 and "ok" in result.stdout
        except Exception as exc:
            logger.warning("Error annotating reminder: %s", exc)
            return False

    def update_body_tags(self, reminder_id: str, tag_to_remove: str, tag_to_add: str) -> bool:
        resolved_list = self._resolve_list_selector()
        if resolved_list is None:
            return False

        if resolved_list.get("id"):
            escaped_list_id = resolved_list["id"].replace('"', '\\"')
            target_list_clause = f'set taskList to first list whose id is "{escaped_list_id}"'
        else:
            escaped_list_name = resolved_list["name"].replace('"', '\\"')
            target_list_clause = f'set taskList to list "{escaped_list_name}"'

        escaped_id = reminder_id.replace('"', '\\"')
        escaped_remove = tag_to_remove.replace("\\", "\\\\").replace('"', '\\"')
        escaped_add = tag_to_add.replace("\\", "\\\\").replace('"', '\\"') if tag_to_add else ""

        script = f'''
        tell {REMINDERS_APP_TARGET}
            try
                {target_list_clause}
                set matchedReminder to (first reminder of taskList whose id is "{escaped_id}")
                set existingBody to body of matchedReminder
                if existingBody is missing value then set existingBody to ""
                set newBody to existingBody
                if "{escaped_remove}" is not "" then
                    set astid to AppleScript's text item delimiters
                    set AppleScript's text item delimiters to "{escaped_remove}"
                    set bodyParts to every text item of existingBody
                    set AppleScript's text item delimiters to astid
                    set newBody to bodyParts as string
                end if
                if "{escaped_add}" is not "" then
                    if newBody is "" then
                        set newBody to "{escaped_add}"
                    else
                        set newBody to newBody & " {escaped_add}"
                    end if
                end if
                set body of matchedReminder to newBody
                return "ok"
            on error errMsg
                return "error: " & errMsg
            end try
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0 and "ok" in result.stdout
        except Exception as exc:
            logger.warning("Error updating body tags: %s", exc)
            return False


    def update_status_line(self, reminder_id: str, status: str) -> bool:
        resolved_list = self._resolve_list_selector()
        if resolved_list is None:
            return False

        if resolved_list.get("id"):
            escaped_list_id = resolved_list["id"].replace('"', '\\"')
            target_list_clause = f'set taskList to first list whose id is "{escaped_list_id}"'
        else:
            escaped_list_name = resolved_list["name"].replace('"', '\\"')
            target_list_clause = f'set taskList to list "{escaped_list_name}"'

        escaped_id = reminder_id.replace('"', '\\"')
        escaped_status = status.replace("\\", "\\\\").replace('"', '\\"')

        script = f'''
        tell {REMINDERS_APP_TARGET}
            try
                {target_list_clause}
                set matchedReminder to (first reminder of taskList whose id is "{escaped_id}")
                set existingBody to body of matchedReminder
                if existingBody is missing value then set existingBody to ""
                set newLines to {{}}
                set oldLines to paragraphs of existingBody
                repeat with aLine in oldLines
                    if aLine does not start with "Status:" then
                        set end of newLines to aLine as text
                    end if
                end repeat
                set AppleScript's text item delimiters to linefeed
                set filteredBody to newLines as text
                set AppleScript's text item delimiters to ""
                if filteredBody is "" then
                    set body of matchedReminder to "Status: {escaped_status}"
                else
                    set body of matchedReminder to "Status: {escaped_status}" & linefeed & filteredBody
                end if
                return "ok"
            on error errMsg
                return "error: " & errMsg
            end try
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0 and "ok" in result.stdout
        except Exception as exc:
            logger.warning("Error updating status line: %s", exc)
            return False

    def set_reminder_url(self, reminder_id: str, url: str) -> bool:
        resolved_list = self._resolve_list_selector()
        if resolved_list is None:
            return False

        if resolved_list.get("id"):
            escaped_list_id = resolved_list["id"].replace('"', '\\"')
            target_list_clause = f'set taskList to first list whose id is "{escaped_list_id}"'
        else:
            escaped_list_name = resolved_list["name"].replace('"', '\\"')
            target_list_clause = f'set taskList to list "{escaped_list_name}"'

        escaped_id = reminder_id.replace('"', '\\"')
        escaped_url = url.replace("\\", "\\\\").replace('"', '\\"')

        script = f'''
        tell {REMINDERS_APP_TARGET}
            try
                {target_list_clause}
                set matchedReminder to (first reminder of taskList whose id is "{escaped_id}")
                set url of matchedReminder to "{escaped_url}"
                return "ok"
            on error errMsg
                return "error: " & errMsg
            end try
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0 and "ok" in result.stdout
        except Exception as exc:
            logger.warning("Error setting reminder URL: %s", exc)
            return False


def extract_branch_tag(text: str) -> str | None:
    """Extract branch name from a #branch:name tag in reminder body."""
    match = re.search(r'#branch:([\w/._-]+)', text)
    return match.group(1) if match else None


def extract_pr_url(text: str) -> str | None:
    pattern = r"https?://github\.com/[\w-]+/[\w-]+/pull/(\d+)"
    match = re.search(pattern, text)
    if match:
        return match.group(0)  # Returns the full URL
    return None


def extract_pr_number(text: str) -> int | None:
    pattern = r"https?://github\.com/[\w-]+/[\w-]+/pull/(\d+)"
    match = re.search(pattern, text)
    if match:
        return int(match.group(1))
    return None


def has_merge_tag(text: str) -> bool:
    return "#merge" in text.lower()
