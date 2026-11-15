---
"jasonbuffin-skills": minor
---

Commodore's three built-in missions (build, review and PR feedback) are now mission files in `missions/`, each with frontmatter for its task force, builder, checker, stop rule and delivery. A new `mission.py list` reads them as text, and the skill's mission detection picks a mission by its `pick-me-when` instead of a fixed table. The procedures are unchanged.
