---
name: ship-prompt
description: Ship an implemented prompt — commit scoped changes on the feature branch, push to GitHub, and open a PR so Copilot starts reviewing. The post-implement step that pairs with `implement-prompt` (before) and `complete-prompts` (after merge). Use when the user asks to ship, commit, push, or raise a PR for the current prompt's work.
---

# Ship Prompt Skill

Post-implementation step for a prompt: commit the scoped changes, push the
branch to GitHub, and open a pull request so GitHub Copilot can begin review.

Fits in the prompt workflow:
1. `implement-prompt` — plan and implement the prompt
2. **`ship-prompt` (this skill)** — commit, push, open PR for review
3. `complete-prompts` — after merge, move the prompt to `scripts/prompts/completed/`

## Authority note

This skill is the **sanctioned exception** to the general "never run
`git add` / `git commit` / `git push`" rule. When the user invokes
`/ship-prompt`, they are explicitly authorizing the git staging, commit,
push, and PR-creation operations described below — for this invocation
only, scoped to the files this skill identifies. Do not extend that
authorization to unrelated commits or to later turns.

## Steps

### 1. Verify you are on a feature branch

```bash
git branch --show-current
```

If the branch is `main` or `master`, **stop and ask the user** which branch to use.
Never commit directly to `main` or `master`.

### 2. Check what has changed

```bash
git --no-pager status
git --no-pager diff --stat
```

Review what files are modified. If there is nothing to commit, tell the user and stop.

### 3. Identify which files belong to this work

Only commit files that were **changed or added as part of the current work**.
Do NOT blindly `git add -A` — unrelated local edits, scratch files, or stray
artifacts must not ride along.

To decide what belongs:
- Re-read the relevant prompt file (see step 7) and the conversation context.
- Cross-check each modified/untracked path against that scope.
- When in doubt about a specific file, ask the user rather than including it.
- Exclude: `tmp/`, ad-hoc `.report.html` files, unrelated `.org` notes,
  anything under a directory the current task did not touch.

**Always include the prompt file itself** in this commit. The branch is
being shipped as the implementation of a specific prompt, and the PR
reviewer needs the prompt alongside the diff to judge whether the
implementation matches the spec. Resolve the path the same way step 7
does (`scripts/prompts/<slug>.md`) and stage it with the other files.
If the prompt file is already in `scripts/prompts/completed/` (rare at
ship time — `complete-prompts` usually runs after merge), leave it
where it is and still include it in the commit from that path.

If the user has already staged specific files (`git diff --cached` is non-empty),
trust their staging — commit only what is staged and skip re-staging.

### 4. Derive the commit message prefix from the branch name

Branch name format → commit prefix:
- `feature/add-fancy-thing`  → `feature/add-fancy-thing: `
- `fix/broken-query`         → `fix/broken-query: `
- `chore/update-deps`        → `chore/update-deps: `
- `hotfix/crash-on-start`    → `hotfix/crash-on-start: `
- Any other branch name      → use the full branch name as prefix

### 5. Write the commit message

Single-line commit message:
```
<branch-name>: <brief imperative summary of what changed>
```

Rules:
- Imperative mood ("add X", "fix Y", "remove Z"), max 72 chars
- Do NOT include "WIP", "misc", or vague words like "updates" or "changes"
- **Single line only** — no body, no Co-Authored-By trailer

### 6. Run linters and unit tests — HARD GATE

**Do not commit, push, or open a PR until the full unit-test suite is
green.** This applies even when failing tests look unrelated to the diff
— a pre-existing failure on `main` still blocks shipping. Either fix the
test, or stop and tell the user the PR cannot be shipped until it is fixed.

Run the same command locally that CI would run, and verify zero failures:

```bash
poetry run ruff check $(git diff --name-only HEAD | grep '\.py$')
poetry run ruff format --check $(git diff --name-only HEAD | grep '\.py$')
poetry run pytest tests/ -q --ignore=tests/integration
```

Rules:
- **Tests:** the suite must end with `N passed, 0 failed`. Use
  `--deselect` only to skip tests that genuinely cannot run in this
  environment (e.g. integration tests that need a live DB) — never to
  paper over a real failure.
- **Lint errors that this PR introduced:** fix them.
- **Lint errors that pre-date this PR (untouched lines):** acceptable to
  leave; do not chase repo-wide lint debt in a shipping PR.
- **Format diffs on files this PR touched:** auto-fix with
  `poetry run ruff format <files>` and re-run tests.
- **Frontend changes:** also run `cd frontend && npm run lint`.

If you find broken tests that are unrelated to the work — for example a
field that became required on `main` while you were branched off — the
right move is to fix them in this PR and call them out in the PR
description as drive-by fixes. Do not commit with red tests and do not
open a PR with red tests.

### 7. Stage and commit

Stage only the files identified in step 3, by name:

```bash
git add <file1> <file2> ...
git commit -m "<message>"
```

Never use `git add -A` or `git add .` — they pick up unrelated files.

### 8. Locate the prompt file

This repo tracks work-to-prompt mapping under `scripts/prompts/`. For a branch
like `feature/<slug>` or `fix/<slug>`, the prompt file is typically
`scripts/prompts/<slug>.md` (or `scripts/prompts/completed/<slug>.md` if already
reconciled).

Resolve the prompt path by:
1. Stripping the branch prefix (`feature/`, `fix/`, `chore/`, etc.) to get `<slug>`.
2. Checking `scripts/prompts/<slug>.md`, then `scripts/prompts/completed/<slug>.md`.
3. If neither exists, ask the user which prompt file this work implements.

Remember the resolved `<PROMPT_FILE>` path (repo-relative) for the PR body.

### 9. Push the branch

```bash
git push -u origin <branch-name>
```

If the push is rejected (non-fast-forward), check with the user before force-pushing.
Never `git push --force` without explicit user confirmation.

### 10. Create the pull request

First, check whether a PR already exists for this branch:

```bash
gh pr list --head <branch-name> --json url,number
```

If one exists, print its URL and stop. Otherwise create a new PR.

**PR title:** `<branch-name>: <same summary as commit>`

**PR body** (use exactly this structure — fill in the bracketed sections):

```markdown
Carefully check this PR!!  It implements promt at: <PROMPT_FILE>.  <SPECIFIC THINGS TO CHECK>
```

Where `<SPECIFIC THINGS TO CHECK>` is a concrete, task-specific checklist derived
from the actual diff and prompt. Examples of things to call out when relevant:
- Schema/migration changes — verify column types, nullability, indexes, backfill plan
- New env vars, secrets, or IAM permissions — confirm they are wired in all envs
- External API calls — check rate limits, error handling, retries, timeouts
- Cost-sensitive paths (LLM calls, batch jobs) — confirm cadence and per-row cost
- Cron/EventBridge schedules — confirm gated on `config.is_production`
- Destructive DB operations (DELETE, DROP, TRUNCATE) — confirm scope and safety
- Frontend state changes — check loading/error states and edge cases
- New dependencies — confirm `poetry lock` was re-run for all affected packages
- Currency/revenue math — verify units, rounding, and conversion correctness
- Tests — confirm they hit `steampulse_test`, not live dev DB

Only include items that actually apply to this diff. Do not pad the list.

Create the PR:

```bash
gh pr create \
  --title "<branch-name>: <summary>" \
  --body "<PR body>" \
  --base main
```

### 11. Print the result

Output the PR URL so the user can open it.

## Conventions for This Repo

- Default base branch: `main`
- **Tests must be 100% green before committing.** Run
  `poetry run pytest tests/ -q --ignore=tests/integration` and verify
  zero failures (see step 6). Pre-existing failures still block; fix
  them in this PR or stop and surface to the user.
- Run `poetry run ruff check` and `poetry run ruff format` on the
  Python files this PR touches; do not chase repo-wide lint debt
- Run `cd frontend && npm run lint` before committing frontend changes
- If linting on touched files fails, fix the issues before committing

## Error Handling

- **Nothing to commit**: tell the user, stop
- **On main/master**: ask which branch to use, stop
- **Push rejected**: show the error, ask before force-pushing
- **`gh` not installed**: fall back to printing the `git push` URL and a link to
  `https://github.com/new/pull` with the branch pre-filled
- **Failing tests (any reason, including pre-existing)**: do not commit;
  fix the test in this PR (and call it out in the PR body as a drive-by
  fix), or stop and tell the user the PR cannot ship until the suite is
  green
- **Lint errors on lines this PR touched**: fix them, then proceed
- **Lint errors on untouched lines (pre-existing debt)**: leave alone
- **Prompt file not found**: ask the user for the path instead of guessing
