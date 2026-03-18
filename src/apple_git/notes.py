from __future__ import annotations

import logging
import subprocess
from datetime import datetime

logger = logging.getLogger("apple_git.notes")


class NotesClient:
    def __init__(self, folder_name: str = "apple-git-logs"):
        self.folder_name = folder_name

    def _format_html(self, event_type: str, details: dict, timestamp: str) -> str:
        colors = {
            "issue_created": "#0075ca",
            "pr_created": "#6f42c1",
            "pr_merged": "#1a7f37",
            "issue_closed": "#1a7f37",
            "pr_linked": "#6f42c1",
            "claude_finished": "#1a7f37",
            "claude_error": "#cf222e",
        }
        color = colors.get(event_type, "#555555")
        label = event_type.replace("_", " ").title()

        rows = ""
        for key, value in details.items():
            display = f'<a href="{value}">{value}</a>' if str(value).startswith("http") else value
            rows += f'<tr><td style="color:#666;padding-right:12px"><b>{key}</b></td><td>{display}</td></tr>'

        return (
            f'<h2 style="color:{color};margin-bottom:4px">{label}</h2>'
            f'<p style="color:#999;font-size:12px;margin-top:0">{timestamp}</p>'
            f'<table style="border-collapse:collapse;font-size:14px">{rows}</table>'
        )

    def create_note(self, title: str, body: str) -> bool:
        def _esc(text: str) -> str:
            return (
                text.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\r", "")
            )

        ef = _esc(self.folder_name)
        et = _esc(title)
        eb = _esc(body)

        script = f'''
        tell application "Notes"
            try
                if not (exists folder "{ef}") then
                    set targetFolder to make new folder with properties {{name:"{ef}"}}
                else
                    set targetFolder to folder "{ef}"
                end if
                make new note at targetFolder with properties {{name:"{et}", body:"{eb}"}}
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
                timeout=45,
            )
            if result.returncode != 0 or "error" in result.stdout.lower():
                logger.warning("Failed to create note: %s", result.stderr)
                return False
            logger.info("Created note: %s", title[:50])
            return True
        except subprocess.TimeoutExpired:
            logger.warning("Timed out creating note")
            return False
        except FileNotFoundError:
            logger.error("osascript not found - requires macOS")
            return False
        except Exception as exc:
            logger.warning("Error creating note: %s", exc)
            return False

    def log_event(self, event_type: str, details: dict) -> bool:
        if not self.folder_name:
            return False

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = f"[{event_type}] {now_str}"
        body = self._format_html(event_type, details, now_str)
        return self.create_note(title, body)
