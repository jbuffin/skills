---
"jasonbuffin-skills": minor
---

Commodore's Admiral report is version 2. `prs` lists objects with each PR's `url` and the issues it `closes`, an optional `cast` lists the crew members the run used, and `resume` is also written whenever a listed PR is open, because Admiral uses it as the wake prompt of a moored ship. Inside Admiral, a launch that names two or more issues is a slice, always built as one gh stack where exactly one PR closes each child issue; a child no PR closes fails the completion gate and the run ends `partial`.
