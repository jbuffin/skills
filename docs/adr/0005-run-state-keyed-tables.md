# Run state keeps its structured fields as keyed tables in state.md

A commodore coordinator spent many calls hand-editing the free-form `state.md` (#127). We gave it a fixed format that `state-set.sh` edits: `key: value` lines under `## Mode, phase, current unit`, and Markdown tables for units, the acceptance trace and non-blocking findings, each row addressed by its first column. Everything stays in one file, because the coordinator reads `state.md` first after every start or compaction, and one read has to tell it where the run is. Only fields the coordinator decides or records are settable: branch heads, PR and CI state are re-read live from `git` and `gh`, so the units table's head column is a snapshot, never the source of truth.

## Considered options

- **Separate TSV files per table (`units.tsv`, `trace.tsv`)**, like `worktrees.tsv` and `teammates.tsv`: rejected. A resume would have to read several files, and the trace is read by people as well as scripts.
- **Fixed format only for the mode lines**: rejected. The unit and trace rows were where the costliest hand-edits happened.

## Consequences

`rounds.tsv` stays a separate file, because `review-round.sh` owns it and enforces the round cap from it. A `state.md` from before this change isn't migrated: `state-set.sh` refuses a section that isn't in table format, and the coordinator edits it by hand.
