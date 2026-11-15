---
"jasonbuffin-skills": minor
---

When no registered mission fits what you point Commodore at, it now designs an ad hoc mission for the run instead of only asking which one you mean. It validates the mission with `mission.py validate`, shows its source of truth, task force, builder, checker, stop rule and delivery, and asks you to confirm it; under autopilot the proposal is a question item and the run stops. The Admiral report gains an optional `mission` field, `{name, ad_hoc}`, which Commodore writes when the run has a settled mission or stops with an ad hoc proposal pending, and leaves out otherwise.
