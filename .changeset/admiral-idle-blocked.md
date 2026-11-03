---
"jasonbuffin-skills": patch
---

The admiral driver's `status` maps the crew state `idle` to `blocked`, so the watchdog still raises BLOCKED for an idle boat that never wrote its marker. A test now covers `stop` closing an idle boat with exit 0 (it already did). The Codex and Copilot references say an idle writer boat shows `idle`, not `needs_you`.
