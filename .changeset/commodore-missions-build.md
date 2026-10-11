---
"jasonbuffin-skills": minor
---

`commodore` now works out the run's mission (`build`, `review` or `pr-feedback`) from what you point it at, confirms it with you before launching any teammate, and records it in `state.md`. Explicit wording such as "build #17" overrides detection. The existing flow is now the build mission, unchanged, and lives in `references/mission-build.md`. Your own PR still runs as a build mission in existing-PR mode, and someone else's PR stops with a message that the review mission is not available yet.
