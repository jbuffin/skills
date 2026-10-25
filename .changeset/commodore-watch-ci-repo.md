---
"jasonbuffin-skills": patch
---

Commodore's `watch-ci.sh` now runs `gh` from the run's target repo (`REPO`, or `WORKTREE`, in `team.env`). Before, `gh` picked the repo from the coordinator's working directory, so a coordinator started in a different repo from the one it was building found no CI run and exited 1 with "could not find any workflows named CI".
