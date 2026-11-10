---
"jasonbuffin-skills": major
---

Commodore casts its crew from member files, and `roles.json` is no longer read. `scripts/crew.py cast` replaces `role-skills.sh`: it picks one member per role (a run-layer member is a pin, then `--pick`, then the latest layer's member), drops skills the harness can't load, prints the table for the profile, and with `--save` writes `cast.json` and the `MODEL_<ROLE>` lines in `team.env`. `team-preflight.sh` runs it, `team-init.sh` keeps the Admiral crew layers in `team.env`, and `setup-commodore` now drafts member files with `crew-draft.sh` in place of `roles-draft.sh`. To migrate, run `setup-commodore/scripts/convert-roles.py <roles.json> <crew-dir>` once for each `roles.json` (user-global, repo and run), then delete it. `cast` warns while one is left behind.
