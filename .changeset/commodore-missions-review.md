---
"jasonbuffin-skills": minor
---

`commodore` now runs a review mission when you point it at someone else's open PR, including one from a fork. It creates a detached read-only worktree on the PR's head, stops for your go-ahead when the PR changes agent config such as `CLAUDE.md` or `.claude/`, launches a fresh reviewer and security reviewer for one round on the PR's full range, and adds the target steward only when the PR changes something a user would touch. Phase 1 skips Keychain secrets, push allow rules and the implementer probe. You get merged findings and a recommended verdict first, and nothing is posted until you approve. It then posts one GitHub review with inline comments, as `COMMENT` unless you choose `APPROVE` or `REQUEST_CHANGES`. The run never commits or pushes to the PR's branch.
