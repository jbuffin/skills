---
"jasonbuffin-skills": minor
---

Choose each teammate's model by role. `launch-teammate.sh` takes `--model` and `--role` in any order, reads `MODEL_<ROLE>` from `team.env`, and refuses a launch with no model for its role. `REQUIRE_ROLE=1` makes a forgotten flag fail. `agent-team-build` records a model per role in the profile and writes the defaults into `team.env`.
