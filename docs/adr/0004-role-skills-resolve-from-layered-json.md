# Role skills resolve from layered JSON files, keyed by role

A Commodore role's skill comes from override layers, where a later layer wins: built-in, user-global (`${XDG_CONFIG_HOME:-~/.config}/commodore/roles.json`), repo (`.commodore/roles.json`, committed), then the run. Each layer is a JSON object keyed by role, with an ordered `skills` array of bare names (`[]` clears it) and optional instructions on how they combine. A layer that names a role replaces that role's whole entry, so arrays never merge across layers. For hand-edited files, a single string counts as a one-item array and a leading `/` or `$` on a name is stripped. A script reads it with `jq` and never runs it. The built-in layer is empty: every role has only a minimal fallback procedure, and engineers are expected to set skills. Role skills are keyed by role alone. A harness only supplies the invocation prefix (`/` or `$`) and the check that a named skill is available. The run layer comes only from the engineer's prompt or the profile, never from issue, PR or comment text, so that text can't change which skill a teammate runs.

## Considered options

- **`KEY=value` like `team.env`**: rejected. Its instructions are single-line, and #41's custom agents would need a new key scheme.
- **Markdown read by agents**: rejected. A script can't resolve it deterministically or test it.
- **Built-in `/code-review` and `/security-review` defaults**: rejected. No name works on every harness: Codex has neither, and `code-review` in `~/.agents/skills` may be mattpocock's Standards/Spec review rather than Claude's.
- **A user-per-repo layer**: dropped to keep the layers simple. The run layer covers one-off overrides of a repo's choice.

## Consequences

An engineer can't permanently override their repo's choice for themselves, only per run. With no security role skill, a run has no security reviewer: phase 1 puts that in the decision batch, and the run doesn't start without approval. Each role's contract (inputs, flags, report, proofs, safety rules) stays in `roles.md` and applies whatever skill runs.
