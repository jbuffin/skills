# Glossary

**Security reviewer**: a read-only teammate, fresh every review round, that reviews a unit's diff only for security vulnerabilities, alongside the reviewer. _Avoid_: security auditor, security checker.

**Blocking finding**: a review finding at or above the profile's severity threshold, which must be fixed (or handed to a human at the round cap) before the unit ships. _Avoid_: must-fix, critical finding.

**Non-blocking finding**: a review finding below the threshold. It's recorded for the run's final summary, and the implementer may fix it if the fix is trivial. _Avoid_: nit, minor finding.

**Mission**: what a commodore run is for, worked out from what the engineer points it at: build, review or PR feedback. It decides the run's task force. _Avoid_: job, task type.

**Task force**: the set of roles a mission assembles for a run. _Avoid_: team composition, cast.

**Triager**: a read-only teammate on a PR-feedback mission that sorts each review comment and failing check on the engineer's own PR into fix, push back, needs the engineer's call, or already done. _Avoid_: comment reviewer.
