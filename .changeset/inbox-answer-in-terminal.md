---
"jasonbuffin-skills": patch
---

Commodore and retro now write a question item's answer file when the engineer answers it in the session (the terminal, or a resume without `--autopilot`) instead of in Admiral's inbox, so Admiral stops showing the item. `admiral-io.sh answer-write <inbox-dir> <id> <draft>` writes `<id>.answer.json` in ADR 0016's question shape through a temp file and a link, after checking it against `references/admiral-answer.schema.json` and, with the new `answer-check.py`, against the item: every question answered, only the item's question ids, and option labels only (a list only on a `multi` question). It never replaces an existing answer (exit 4). `schema-check.py` gains `--new <file>`, which publishes to an exact path and never replaces it.
