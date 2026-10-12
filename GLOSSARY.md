# Glossary

**Security reviewer**: a read-only teammate, fresh every review round, that reviews a unit's diff only for security vulnerabilities, alongside the reviewer. _Avoid_: security auditor, security checker.

**Blocking finding**: a review finding at or above the profile's severity threshold, which must be fixed (or handed to a human at the round cap) before the unit ships. _Avoid_: must-fix, critical finding.

**Non-blocking finding**: a review finding below the threshold. It's recorded for the run's final summary, and the implementer may fix it if the fix is trivial. _Avoid_: nit, minor finding.

**Mission**: what a commodore run is for, worked out from what the engineer points it at: build, review or PR feedback. It decides the run's task force. _Avoid_: job, task type.

**Task force**: the set of roles a mission assembles for a run. _Avoid_: team composition, cast.

**Triager**: a read-only teammate on a PR-feedback mission that sorts each review comment and failing check on the engineer's own PR into fix, push back, needs the engineer's call, or already done. _Avoid_: comment reviewer.

**Harness**: the agent CLI a run is started from (Claude Code, Codex or Copilot CLI). The coordinator and every teammate in the run use it, and it decides how teammates are launched, messaged, watched and stopped. _Avoid_: runtime, backend, agent CLI.

**Advisor**: a stronger model built into the harness and paired with a teammate's session, which sees the teammate's own transcript when the teammate consults it. A sub-agent the teammate has to brief or fork through its prompt is not an advisor, so a harness without one reports the advisor as not available. _Avoid_: second opinion, rubber duck, consultant.
