---
"jasonbuffin-skills": minor
---

Commodore's build mission marks a clean PR ready in autopilot mode. At the end of the run, the new `pr-ready.sh` checks each unit's PR (open, on the base branch, CI green, at the branch head, no `human` rows in the findings table) and prints the `gh pr ready` and, when `ADMIRAL_AUTO_MERGE` is set, `gh pr merge --auto --<method>` commands. Commodore runs each as its own tool call so Admiral's guard sees it, and a refusal is reported, not retried. A PR that isn't clean stays draft, and the Admiral report's `why` names it and the reason.
