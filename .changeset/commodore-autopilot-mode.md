---
"jasonbuffin-skills": minor
---

Add autopilot mode to Commodore for unattended Admiral runs. With `ADMIRAL_AUTOPILOT=1` or a launch text starting with `--autopilot`, Commodore takes the recommended default on low-stakes calls, puts each high-stakes call in one inbox question item and stops `partial`, and leaves a review PENDING for the inbox. It resumes from `/commodore resume <run-name>` once the answers land. When `ADMIRAL_REPORT` is set, every run now publishes an Admiral report.
