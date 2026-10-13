---
"jasonbuffin-skills": patch
---

The Claude Code agent-teammates driver's `has-skill` and `list-skills` now find every installed plugin's skills: a project-scoped plugin no longer stops the search and drops the plugins listed after it. They also find the plugins and skills synced from claude.ai (`plugins/synced/`, `skills/synced/`), so Commodore role skills from those sources resolve instead of being dropped as missing.
