# Apple Reminders Setup Guide

This guide walks you through setting up the macOS Reminders app for use with apple-git.

## Step 1: Create the Five Lists

In the Reminders app, create these five lists (all with `dev-` prefix):

1. **dev-backlog** — Planning/backlog items (no GitHub action)
2. **dev-started** — Items in progress (no GitHub action)
3. **dev-issue-ready** — Ready to create a GitHub issue
4. **dev-review** — Ready for PR review or creation
5. **dev-done** — Merge PR and close issue

## Step 2: Configure apple-git

Update `config/config.yaml` to match your list names (they should already be set):

```yaml
reminders:
  list_inactive: "dev-backlog"
  list_started: "dev-started"
  list_issue_ready: "dev-issue-ready"
  list_review: "dev-review"
  list_done: "dev-done"
```

## Step 3: Understanding the Workflow

### Creating a New Issue

1. Add a reminder to **dev-backlog** or **dev-started** (planning phase)
2. When ready, move to **dev-issue-ready**
3. apple-git automatically:
   - Creates a GitHub issue from the reminder name/body
   - Annotates the reminder with the issue link
   - Stores the mapping in SQLite

Example:
```
Reminder: "Fix login redirect bug"
Body: "User gets redirected to wrong URL after login.
       Happens in Chrome and Safari."
→ Moved to dev-issue-ready
→ Creates GitHub Issue #42
```

### Creating or Linking a PR

**Automated workflow:**
1. When you move reminder to **dev-issue-ready**, apple-git creates GitHub issue
2. GitHub Action automatically creates branch: `issue-{number}`
3. Reminder annotated with branch name for reference
4. When you move to **dev-review**, add:
   - **`#branch:issue-123`** tag (from reminder annotation) → apple-git creates PR

**Steps:**

```
1. Move reminder to dev-issue-ready
   → ✓ Issue #123 created
   → ✓ Branch issue-123 auto-created by GitHub
   → Reminder shows: "Issue #123\nBranch: issue-123"

2. Do your work on the branch:
   git checkout issue-123
   git commit...
   git push

3. Add tag to reminder body:
   #branch:issue-123

4. Move reminder to dev-review
   → ✓ PR created automatically
```

Example:

**Auto-branch workflow:**
```
Reminder: "Fix login redirect bug"
Body: "User gets redirected to wrong URL after login.
       Happens in Chrome and Safari."

→ Moved to dev-issue-ready
→ ✓ Issue #123 created
→ ✓ Branch issue-123 created by GitHub Action
→ Reminder annotation: "Issue #123: https://github.com/...
                       Branch: issue-123"

→ Do work: git checkout issue-123 && git commit...

→ Add to body: #branch:issue-123
→ Move to dev-review
→ ✓ PR created from issue-123 branch
```

**Link existing PR (manual):**
```
Reminder: "Fix login redirect bug"
Body: "Already have a PR open for this.
       https://github.com/dkyazzentwatwa/flow-healer/pull/123"
→ Moved to dev-review
→ Links PR #123
```

Or simply add the PR URL in the body when moving to dev-review.

### Merging and Closing

1. When the PR is merged (on GitHub), move the reminder to **dev-done**
2. Add **`#merge`** tag in the body if you want apple-git to automatically merge the PR
3. apple-git automatically:
   - Merges the PR (if `#merge` tag present)
   - Closes the GitHub issue
   - Completes the reminder
   - Logs everything to Apple Notes

Example:
```
Reminder: "Fix login redirect bug"
Body: "Ready to merge and close.
       #merge"
→ Moved to dev-done
→ Merges PR #123
→ Closes Issue #42
→ ✓ Completes reminder
```

## Step 4: Running apple-git

```bash
cd /Users/cypher/Documents/GitHub/apple-git
python -m apple_git
```

Watch the logs and Apple Notes for activity.

## Quick Reference

### List Routing

| List | Action | Tag Required? |
|------|--------|---------------|
| dev-backlog | None (planning) | — |
| dev-started | None (in progress) | — |
| dev-issue-ready | Create GitHub issue | — |
| dev-review | Link/create PR | `#branch:name` or PR URL |
| dev-done | Close issue, merge PR | `#merge` (optional, for merge) |

### Tag Syntax

- **`#branch:my-feature-name`** — Create PR from this branch
  - Supports: alphanumeric, `-`, `/`, `.`, `_`
  - Example: `#branch:fix/user-auth` or `#branch:feature.new-ui`

- **GitHub PR URL** — Link existing PR
  - Automatically detected in body
  - Example: `https://github.com/dkyazzentwatwa/flow-healer/pull/123`

- **`#merge`** — Merge the PR when moving to issue-done
  - Only used in issue-done list
  - Optional; reminder is completed regardless

### Apple Notes Logging

Every action is logged to Apple Notes for audit trail:
- Issue created
- PR created from branch
- PR linked from URL
- PR merged
- Issue closed
- Any skips/errors (reminders without mappings, missing branch/URL, etc.)

## Troubleshooting

### Reminder not creating issue?
- Make sure the reminder is in **issue-ready** list
- Check logs: `~/.apple-git/apple-git.log`
- Verify GitHub token in `config/config.yaml`

### PR not being created/linked?
- For branch creation: reminder must have `#branch:name` tag
- For URL linking: PR URL must be in reminder body
- Reminder must be in **review** list
- If neither tag nor URL present, check Apple Notes log for `pr_review_skipped`

### Issue not closing?
- Reminder must be in **issue-done** list
- Reminder must have a mapping (must have been in issue-ready first)
- Check GitHub permissions

### Lists not found?
- Verify list names match `config/config.yaml` exactly
- Check macOS System Preferences → Privacy & Security → Automation for System Events permission
- Reminders app should be running or accessible

## Example Workflow

```
1. Create reminder: "Implement dark mode"
   → Add to dev-backlog
   → Discuss with team

2. Ready to work:
   → Move to dev-started
   → No GitHub action

3. Ready for issue tracking:
   → Move to dev-issue-ready
   → ✓ GitHub Issue #45 created automatically

4. Code ready:
   → Move to dev-review
   → Add body: "#branch:feat/dark-mode"
   → ✓ PR #47 created automatically

5. PR merged:
   → Move to dev-done
   → Add body: "#merge"
   → ✓ PR #47 merged
   → ✓ Issue #45 closed
   → ✓ Reminder marked complete
```
