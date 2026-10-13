---
"jasonbuffin-skills": minor
---

agent-teammates drivers gain an optional `list-skills <team-dir>` operation. It prints one `<name><TAB><file>` line for each skill the harness can load for the run's repo. Each driver's `has-skill` and `list-skills` now share one search in `skills.zsh`, so the two always agree. A new incubator skill, `setup-commodore`, uses it to write Commodore role-override files interactively.
