---
"jasonbuffin-skills": minor
---

agent-teammates' `launch-teammate.sh` takes `--member <member>` and launches the teammate as that Admiral crew member through `admiral crew launch --member`. The member's model applies when no `--model` is given, `--member` satisfies `REQUIRE_ROLE=1`, and the admiral driver shows Admiral's warnings after a launch. Outside an Admiral ship, and for codex or copilot teammates under autopilot or read-only, it exits 5.
