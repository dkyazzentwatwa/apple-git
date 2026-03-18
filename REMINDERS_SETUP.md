# Apple Reminders Setup Guide

This guide walks through the current `apple-git` Reminders workflow.

## Step 1: Create the Lists

Create these five lists in Apple Reminders:

1. **dev-backlog** — backlog/planning, no GitHub action
2. **issue-plan** — create the GitHub issue and generate the implementation plan
3. **dev-issue-ready** — approved plan; start code generation
4. **dev-review** — create or link a pull request
5. **dev-done** — merge PR and close issue

## Step 2: Configure apple-git

`config/config.yaml` should include:

```yaml
reminders:
  list_inactive: "dev-backlog"
  list_issue_plan: "issue-plan"
  list_issue_ready: "dev-issue-ready"
  list_review: "dev-review"
  list_done: "dev-done"
```

## Step 3: Workflow

### Issue Planning

1. Create a reminder in **dev-backlog**.
2. Move it to **issue-plan**.
3. `apple-git` will:
   - create the GitHub issue
   - add `#branch:issue-{number}` to the reminder body
   - attach the issue URL to the reminder
   - post a canonical implementation plan comment on the issue

The reminder stays in `issue-plan` until you approve the plan.

### Code Generation

1. Review the generated plan on the GitHub issue.
2. Move the reminder to **dev-issue-ready**.
3. `apple-git` will:
   - look up the existing issue mapping
   - load the canonical plan comment
   - start the configured connector on the issue branch

If the reminder reaches `dev-issue-ready` without a mapping or without the canonical plan comment, `apple-git` blocks and updates the reminder status instead of starting code generation.

### Review

Move the reminder to **dev-review** when the branch is ready.

If the reminder body contains `#branch:issue-123`, `apple-git` creates the PR automatically. If the body contains a GitHub PR URL instead, `apple-git` links that PR.

### Done

Move the reminder to **dev-done** after the PR is merged, or add `#merge` if you want `apple-git` to attempt the merge first. `apple-git` then closes the issue and completes the reminder.

## Quick Reference

| List | Action |
|------|--------|
| `dev-backlog` | No GitHub action |
| `issue-plan` | Create issue and implementation plan |
| `dev-issue-ready` | Start code generation from approved plan |
| `dev-review` | Create or link PR |
| `dev-done` | Merge PR optionally, close issue, complete reminder |

## Troubleshooting

### Reminder not creating an issue?

- Make sure it is in `issue-plan`
- Check `~/.apple-git/apple-git.log`
- Verify GitHub configuration and token

### Reminder not starting code generation?

- Make sure it was previously processed in `issue-plan`
- Make sure the GitHub issue still has the canonical apple-git implementation plan comment
- Make sure the connector CLI is installed and available on `PATH`

### PR not being created?

- Ensure the reminder body contains `#branch:<name>` or a GitHub PR URL
- Make sure the reminder is in `dev-review`

## Run the Daemon

```bash
cd /Users/cypher/Documents/GitHub/apple-git
python -m apple_git
```
