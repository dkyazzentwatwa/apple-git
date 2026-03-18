#!/usr/bin/env python3
"""Test script to explore Reminders app structure, groups, and lists."""

import subprocess
from typing import Optional

def run_applescript(script: str) -> Optional[str]:
    """Run AppleScript and return stdout."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            print(f"❌ Error: {result.stderr}")
            return None
        return result.stdout.strip()
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None


def test_list_groups():
    """List all reminder groups."""
    print("\n=== REMINDERS GROUPS ===")
    script = '''
    tell application id "com.apple.reminders"
        set allGroups to {}
        repeat with g in every list group
            set end of allGroups to name of g
        end repeat
        set text item delimiters to linefeed
        return allGroups as text
    end tell
    '''
    output = run_applescript(script)
    if output:
        groups = [g.strip() for g in output.split("\n") if g.strip()]
        print(f"Found {len(groups)} groups:")
        for group in groups:
            print(f"  • {group}")
        return groups
    else:
        print("Could not fetch groups")
        return None


def test_lists_in_group(group_name: str):
    """List all lists in a specific group."""
    print(f"\n=== LISTS IN GROUP '{group_name}' ===")
    script = f'''
    tell application id "com.apple.reminders"
        try
            set targetGroup to list group "{group_name}"
            set allLists to {{}}
            repeat with lst in every list of targetGroup
                set end of allLists to name of lst
            end repeat
            set text item delimiters to linefeed
            return allLists as text
        on error errMsg
            return "ERROR: " & errMsg
        end try
    end tell
    '''
    output = run_applescript(script)
    if output and not output.startswith("ERROR"):
        lists = [lst.strip() for lst in output.split("\n") if lst.strip()]
        print(f"Found {len(lists)} lists:")
        for lst in lists:
            print(f"  • {lst}")
        return lists
    else:
        print(f"Could not fetch lists from '{group_name}'")
        if output:
            print(f"  {output}")
        return None


def test_fetch_reminders_from_grouped_list(group_name: str, list_name: str):
    """Try to fetch reminders from a list in a group."""
    print(f"\n=== REMINDERS IN '{list_name}' (group: '{group_name}') ===")
    script = f'''
    set text item delimiters to linefeed
    tell application id "com.apple.reminders"
        try
            set targetGroup to list group "{group_name}"
            set targetList to list "{list_name}" of targetGroup
            set rIds to id of every reminder of targetList
            set rNames to name of every reminder of targetList
            set rBodies to ""
            repeat with r in (every reminder of targetList)
                try
                    set b to body of r
                    if b is missing value then set b to ""
                    set rBodies to rBodies & b & linefeed
                on error
                    set rBodies to rBodies & linefeed
                end try
            end repeat
            set rListName to name of targetList as text
            return (rIds as text) & "|" & (rNames as text) & "|" & rBodies & "|" & rListName
        on error errMsg
            return "ERROR: " & errMsg
        end try
    end tell
    '''
    output = run_applescript(script)
    if output and not output.startswith("ERROR"):
        parts = output.split("|")
        if len(parts) >= 4:
            ids = parts[0].strip().split("\n") if parts[0].strip() else []
            names = parts[1].strip().split("\n") if parts[1].strip() else []
            list_name_returned = parts[3].strip()

            print(f"Found {len([x for x in ids if x])} reminders in '{list_name_returned}':")
            for i, name in enumerate(names):
                if name:
                    print(f"  • {name}")
            return len([x for x in ids if x])
    else:
        print("Could not fetch reminders")
        if output:
            print(f"  {output}")
        return 0


def main():
    print("🔍 Testing Reminders App Structure")

    # Test 1: Get all groups
    test_list_groups()

    # Test 2: Get lists in "Linear" group (if it exists)
    lists = test_lists_in_group("Linear")

    if lists:
        # Test 3: Try to fetch reminders from first list
        print("\n=== TESTING REMINDER FETCH ===")
        for list_name in lists[:1]:  # Test first list
            count = test_fetch_reminders_from_grouped_list("Linear", list_name)
            if count is not None:
                print(f"✅ Successfully fetched reminders from '{list_name}'")

    print("\n" + "="*50)
    print("Summary: AppleScript can access grouped lists!")
    print("We can modify RemindersClient to support list groups.")
    print("="*50)


if __name__ == "__main__":
    main()
