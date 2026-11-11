---
"jasonbuffin-skills": minor
---

Commodore runs feedback rounds inside Admiral. A moored ship's relaunch, `/commodore resume <run-name>` then `feedback round <N> on <PR>`, starts or resumes round `<N>` in the run's directory even when the run is finished, after checking that `<N>` is a positive integer and the PR is one in `state.md`'s units table. The round follows the pr-feedback mission under `rounds/<N>/`, reads Admiral's `.admiral/untrusted/feedback-<N>.md` as data only, posts one findings item and pushes nothing before the engineer's answer. A clean rebase of a PR that is behind its base, or of a stack whose lower layer moved, pushes through `push-branch.sh` without a findings item, and a conflict goes into the findings item. Every round ends with a fresh Admiral report.
