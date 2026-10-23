---
"jasonbuffin-skills": minor
---

Commodore caps review at two rounds per unit. Round 1 is the full review, with the unit's only security review. Round 2 is one fresh reviewer on the fix range: it checks that each fix-job item was fixed, and only HIGH findings block. Whatever is left goes to a human in the round-cap PR comment, HIGH first. The new `review-round.sh` counts each unit's rounds in `rounds.tsv` and refuses a third, so the cap holds. Over 91 reviewed units, 43% had gone three or more rounds and five went past the old cap of 3, mostly on MEDIUM findings that the previous fix had introduced.
