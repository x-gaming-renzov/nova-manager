---
name: commit_style_preferences
description: User prefers granular commits, no co-author tags, tests committed separately, short commit messages
type: feedback
---

Granular commits — separate logical changes into their own commits. Tests should be committed separately from code changes. No co-author lines. Keep commit messages short and to the point.

**Why:** User explicitly requested this workflow. They want clean, reviewable git history.
**How to apply:** When committing, split changes by concern (e.g., fix vs tests), omit Co-Authored-By, keep messages concise (one line ideally).
