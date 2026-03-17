from __future__ import annotations

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

        if resolved_list.get("id"):
            escaped_list_id = resolved_list["id"].replace('"', '\\"')
            list_selector = f'first list whose id is "{escaped_list_id}"'
        else:
            escaped_list_name = self.list_name.replace('"', '\\"')
            list_selector = f'list "{escaped_list_name}"'

        script = f'''
        set text item delimiters to linefeed
        tell {REMINDERS_APP_TARGET}
            set taskList to {list_selector}
            set rIds to id of every reminder of taskList
            set rNames to name of every reminder of taskList
            set rBodies to ""
            repeat with r in (every reminder of taskList)
                try
                    set b to body of r
                    if b is missing value then set b to ""
                    set rBodies to rBodies & b & linefeed
                on error
                    set rBodies to rBodies & linefeed
                end try
            end repeat
            set rListName to name of taskList as text
            return (rIds as text) & "|" & (rNames as text) & "|" & rBodies & "|" & rListName
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
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
        parts = output.strip().split("|")
        if len(parts) < 3:
            return []

        ids = parts[0].splitlines()
        names = parts[1].splitlines()
        bodies = parts[2].splitlines() if len(parts) > 2 else []
        list_name = parts[3].strip() if len(parts) > 3 else ""

        reminders = []
        for i in range(len(ids)):
            reminders.append(Reminder(
                id=ids[i].strip(),
                name=names[i].strip() if i < len(names) else "",
                body=bodies[i].strip() if i < len(bodies) else "",
                list_name=list_name,
                creation_date="",
                due_date="",
            ))
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
