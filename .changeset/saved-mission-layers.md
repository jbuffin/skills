---
"jasonbuffin-skills": minor
---

Commodore now finds saved missions beside the built-in ones. `mission.py list` resolves missions over the built-in, user-global (or fleet, inside Admiral) and repo (`--repo-dir`) layers, tags each with its `layer` and `path`, and drops a saved mission named like a built-in one with a warning. When you confirm a saved mission, the run works from a validated copy recorded as `saved file:` in `state.md`.
