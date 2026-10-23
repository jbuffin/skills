---
"jasonbuffin-skills": minor
---

Commodore's `state.md` gets a fixed format: `key: value` lines under the mode heading, and tables for units, the acceptance trace and non-blocking findings, each row keyed by its first column. The new `state-set.sh` edits one field per call and prints nothing, and refuses an unknown row or column or a status outside the table's set. The coordinator now changes those parts only through it, and edits the prose sections with its file-editing tool, never `python3` heredocs or `sed -i`, which took hundreds of calls in a 13-unit run. A `state.md` from before this change isn't migrated: `state-set.sh` refuses its old sections.
