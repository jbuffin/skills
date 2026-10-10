# Glossary

**Security reviewer**: a read-only teammate, fresh every review round, that reviews a unit's diff only for security vulnerabilities, alongside the reviewer. _Avoid_: security auditor, security checker.

**Blocking finding**: a review finding at or above the profile's severity threshold, which must be fixed (or handed to a human at the round cap) before the unit ships. _Avoid_: must-fix, critical finding.

**Non-blocking finding**: a review finding below the threshold. It's recorded for the run's final summary, and the implementer may fix it if the fix is trivial. _Avoid_: nit, minor finding.
