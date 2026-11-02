# Glossary

**Review round**: one pass of review over a unit. Round 1 reviews the unit's diff; round 2, the last, is a fix check, which confirms the fixes landed without reviewing the unit again. _Avoid_: review cycle, iteration.

**Fix check**: review round 2. A fresh fix checker looks only at the range since round 1, `<reviewed SHA>..HEAD`, and the fix job. It reports each fix-job item as `fixed`, `partly` or `not fixed`, what the fixes themselves broke, and up to five notes on anything else. It isn't a second review. _Avoid_: second review, re-review.

**Fix checker**: the read-only teammate that runs the fix check, launched once per unit as `u<unit>-fix-checker`. It runs no role skills and no sub-agents and makes no advisor calls, and it has no fallback procedure. _Avoid_: round-2 reviewer.

**Security reviewer**: a read-only teammate, launched once per unit in review round 1, that reviews the unit's diff only for security vulnerabilities, alongside the reviewer. _Avoid_: security auditor, security checker.

**Blocking finding**: a review finding at or above the profile's severity threshold in round 1, or, in the fix check, a HIGH finding the fixes introduced, which must be fixed (or handed to a human at the round cap) before the unit ships. A MEDIUM or LOW the fixes introduced isn't blocking, but it goes to a human. _Avoid_: must-fix, critical finding.

**Non-blocking finding**: a review finding below the threshold. It's recorded for the run's final summary, and the implementer may fix it if the fix is trivial. A note from the fix check is recorded the same way but never goes to the implementer, whatever its severity. _Avoid_: nit, minor finding.

**Mission**: what a commodore run is for, worked out from what the engineer points it at: build, review or PR feedback. It decides the run's task force. _Avoid_: job, task type.

**Task force**: the set of roles a mission assembles for a run. _Avoid_: team composition, cast.

**Triager**: a read-only teammate on a PR-feedback mission that sorts each review comment and failing check on the engineer's own PR into fix, push back, needs the engineer's call, or already done. _Avoid_: comment reviewer.

**Harness**: the agent CLI a run is started from (Claude Code, Codex or Copilot CLI). The coordinator and every teammate in the run use it, and it decides how teammates are launched, messaged, watched and stopped, unless a host driver decides instead. _Avoid_: runtime, backend, agent CLI.

**Host driver**: a driver chosen by where the run lives, such as an Admiral ship, not by its harness. Inside a host, the host decides how teammates are launched, messaged, watched and stopped, and the run's harness is the one the host's teammates run. Inside Admiral, read-only Codex and Copilot teammates are still run by their harness driver. _Avoid_: platform driver, environment driver.

**Advisor**: a stronger model built into the harness and paired with a teammate's session, which sees the teammate's own transcript when the teammate consults it. A sub-agent the teammate has to brief or fork through its prompt is not an advisor, so a harness without one reports the advisor as not available. A teammate whose model is in the same family as the advisor has none by design: that is a third state, neither off (should have one and doesn't) nor not available. _Avoid_: second opinion, rubber duck, consultant.

**Role skill**: a skill a teammate in a role runs within its role contract. A role can have several, run in order, or none. With none, the role follows its fallback procedure, except the security reviewer, which isn't launched, and the fix checker, which never has role skills and has no fallback. _Avoid_: role tool, persona skill.

**Role contract**: the part of a role that always applies, whatever role skill runs: its inputs, launch flags, scope, report, done signal, proofs and safety rules. A role skill or its instructions can't override it. _Avoid_: role rules, base prompt.

**Override layer**: one of the places a role skill is set, in precedence order: built-in (empty), user-global, repo, then the run, which only the engineer's prompt or the profile can set. _Avoid_: config level, scope, tier.

**Unit**: one slice of a run's work that ships as its own branch and PR, reviewed in its own review rounds. _Avoid_: task, chunk, slice.

**Acceptance trace**: the run's table mapping each acceptance criterion in the source of truth to the unit that owns it, the test or scenario that will show it, its status, and the evidence. _Avoid_: requirements matrix, checklist.
