---
name: changelog-writer
description: Draft a CHANGELOG.md entry from the commits since the last git tag. Use when the user asks for release notes.
allowed-tools: Bash(git log:*), Bash(git describe:*), Read, Edit
---

# Changelog writer

1. Find the last tag with `git describe --tags --abbrev=0`.
2. List commits since that tag with `git log <tag>..HEAD --oneline --no-merges`.
3. Group them under Added, Changed, Fixed and Removed. Drop chore and CI commits.
4. Insert the new section at the top of `CHANGELOG.md` and show the diff to the user.

Never invent entries. If a commit message is unclear, list it under Changed and say so.
