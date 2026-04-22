---
name: complete-prompts
description: Reconcile `scripts/prompts/` with merged feature branches on `main`. For each `feature/<slug>:` commit on `main`, move the matching `scripts/prompts/<slug>.md` into `scripts/prompts/completed/` via `git mv`. Use when the user asks to "complete prompts", "reconcile completed prompts", or "move merged prompts to completed".
---

# Complete Prompts Skill

Scan `main` for merged feature branches and move their corresponding prompt files from `scripts/prompts/` into `scripts/prompts/completed/`.

Naming convention this skill relies on:

- Feature branch: `feature/<slug>`
- Squash-merge commit on `main`: subject starts with `feature/<slug>:`
- Prompt file before shipping: `scripts/prompts/<slug>.md`
- Prompt file after shipping: `scripts/prompts/completed/<slug>.md`

Only `feature/` commits are considered. `fix/`, `chore/`, `hotfix/` branches are not tracked as prompts and are ignored.

## Steps

### 1. Verify repo layout

Confirm we're in the repo and both directories exist:

```bash
git rev-parse --show-toplevel
ls -d scripts/prompts scripts/prompts/completed
```

If either is missing, stop and tell the user.

### 2. Warn if local `main` is behind `origin/main`

Don't auto-fetch. Just surface staleness so the user can decide:

```bash
git rev-list --count main..origin/main 2>/dev/null || echo 0
```

If the count is > 0, print a one-line warning: `local main is N commits behind origin/main — results may be stale. Run 'git fetch origin main' to update.` Continue anyway.

### 3. Collect merged feature slugs from `main`

```bash
git log main --pretty=%s | grep -oE '^feature/[a-z0-9][a-z0-9-]*' | sed 's|^feature/||' | sort -u
```

This yields the deduped slug set. Keep it in memory for the next step.

### 4. Classify each slug

For each slug, check (in order):

- `scripts/prompts/<slug>.md` exists AND `scripts/prompts/completed/<slug>.md` exists → **conflict**, skip
- `scripts/prompts/completed/<slug>.md` exists → **already completed**, skip silently
- `scripts/prompts/<slug>.md` exists → **to move**
- neither exists → **no prompt found**, report but take no action

Do not look inside `scripts/prompts/maybe/` — those are not yet promoted.

### 5. Preview the plan

Before touching any file, print a summary:

```
To move (N):
  <slug>  scripts/prompts/<slug>.md  →  scripts/prompts/completed/<slug>.md
  ...

Already in completed/ (N):
  <slug>, <slug>, ...

Merged features with no prompt file (N):
  <slug>, <slug>, ...

Conflicts — exists in both locations (N):
  <slug>  (skipped — resolve manually)
```

If **To move** is empty, print "Nothing to move." and stop.

### 6. Move the files

For each "to move" slug, prefer `git mv` so history follows:

```bash
git mv scripts/prompts/<slug>.md scripts/prompts/completed/<slug>.md
```

If `git mv` fails because the file is untracked, fall back to:

```bash
mv scripts/prompts/<slug>.md scripts/prompts/completed/<slug>.md
```

### 7. Final report

Print:
- Count and list of files actually moved
- Reminder: `git mv` staged these changes, but the skill does not commit. The user reviews and commits on their own.

Do **not** run `git add`, `git commit`, or `git push`. This repo's convention is that the user handles all staging and committing.

## Error handling

- Missing `scripts/prompts/completed/` directory: stop, ask the user to create it.
- Slug matches a directory (e.g., `completed`, `maybe`): the regex `[a-z0-9][a-z0-9-]*` combined with the explicit `.md` suffix check filters these out. Still, skip any slug whose candidate path is a directory.
- `git log main` fails because `main` doesn't exist locally: tell the user and stop — they need a local `main` ref.
- Dirty working tree: fine. `git mv` works on top of existing changes. Mention that the moves land alongside the user's current edits so they can review together.
