# Glossary

**Review round**: one pass of review over a unit. Round 1 reviews the unit's diff; round 2, the last, checks only the fixes. _Avoid_: review cycle, iteration.

**Security reviewer**: a read-only teammate, launched once per unit in review round 1, that reviews the unit's diff only for security vulnerabilities, alongside the reviewer. _Avoid_: security auditor, security checker.

**Blocking finding**: a review finding at or above the profile's severity threshold in round 1, or a HIGH finding in round 2, which must be fixed (or handed to a human at the round cap) before the unit ships. _Avoid_: must-fix, critical finding.

**Non-blocking finding**: a review finding below the threshold. It's recorded for the run's final summary, and the implementer may fix it if the fix is trivial. _Avoid_: nit, minor finding.

**Mission**: what a commodore run is for, worked out from what the engineer points it at: build, review or PR feedback. It decides the run's task force. _Avoid_: job, task type.

**Task force**: the set of roles a mission assembles for a run. _Avoid_: team composition, cast.

**Triager**: a read-only teammate on a PR-feedback mission that sorts each review comment and failing check on the engineer's own PR into fix, push back, needs the engineer's call, or already done. _Avoid_: comment reviewer.

**Harness**: the agent CLI a run is started from (Claude Code, Codex or Copilot CLI). The coordinator and every teammate in the run use it, and it decides how teammates are launched, messaged, watched and stopped. _Avoid_: runtime, backend, agent CLI.

**Advisor**: a stronger model built into the harness and paired with a teammate's session, which sees the teammate's own transcript when the teammate consults it. A sub-agent the teammate has to brief or fork through its prompt is not an advisor, so a harness without one reports the advisor as not available. _Avoid_: second opinion, rubber duck, consultant.

**Role skill**: a skill a teammate in a role runs within its role contract. A role can have several, run in order, or none. With none, the role follows its fallback procedure, except the security reviewer, which isn't launched. _Avoid_: role tool, persona skill.

**Role contract**: the part of a role that always applies, whatever role skill runs: its inputs, launch flags, scope, report, done signal, proofs and safety rules. A role skill or its instructions can't override it. _Avoid_: role rules, base prompt.

**Override layer**: one of the places a role skill is set, in precedence order: built-in (empty), user-global, repo, then the run, which only the engineer's prompt or the profile can set. _Avoid_: config level, scope, tier.
