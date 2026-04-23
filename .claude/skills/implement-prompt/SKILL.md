---
name: implement-prompt
description: Read a prompt file from `scripts/prompts/` and produce an implementation plan for it. Use when the user asks to "implement a prompt", "plan a prompt", or passes a prompt file path and wants a plan.
---

# Implement Prompt Skill

Read the prompt file at the path the user provides and produce a focused implementation plan for just that prompt.

## Steps

1. Resolve the prompt path from the user's argument. Accept either an absolute path, a repo-relative path, or a bare slug (in which case look under `scripts/prompts/<slug>.md`).
2. Read the prompt file end to end.
3. Produce a plan to implement it. The plan must cover only this prompt — do not expand scope into adjacent prompts or the broader roadmap.
4. Present the plan to the user for review. Do not start implementing until they approve.
