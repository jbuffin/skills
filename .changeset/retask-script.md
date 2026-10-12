---
"jasonbuffin-skills": minor
---

`agent-teammates` has a new `retask.sh <team-dir> <name> <message-file>` that gives a teammate its next job through the driver's `send` operation on harnesses that declare `SEND=script`, then records the re-task so the old `.done` marker stops counting. It refuses unregistered and closed teammates and a missing or empty message file, exits 5 when the driver has no `send`, and on a `SEND=tool` harness (Claude) sends nothing and says to use the harness's tool and then `retasked.sh`. The driver contract's `send` text now fits turn-based harnesses: it resumes the session if its process has exited and returns once the job has started. Claude re-tasking is unchanged.
