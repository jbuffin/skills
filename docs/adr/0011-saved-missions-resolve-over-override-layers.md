# Saved missions resolve over override layers and never replace a built-in

A mission file (a Markdown file with frontmatter and a procedure) can now live outside the skill, as a **saved mission**. `mission.py list` resolves missions over layers, in order: built-in (the skill's `missions/`), then user-global (`${XDG_CONFIG_HOME:-~/.config}/commodore/missions/`) outside Admiral or fleet (`$ADMIRAL_MISSIONS_DIR`) inside it, then repo (`.commodore/missions/` of the repo the caller names with `--repo-dir`). Detection runs before a run directory exists, so the layers come from the environment and `--repo-dir`, never from the current directory or `team.env`. The file rules are the crew members' (ADR 0007): regular `.md` files directly in the directory, an `outside-layer` error for a file that resolves elsewhere, and one bad file fails the whole resolution.

**Add, never replace.** A valid saved mission named like a built-in one (`build`, `review`, `pr-feedback`) is dropped with a warning and the built-in stays. Between saved layers, a later layer replaces an earlier one's mission of the same name. This keeps the three procedures that the safety rules of the skill rely on out of reach of a layer a repo or a fleet controls.

**A run reads a fixed copy.** When the engineer confirms a saved mission, Commodore copies it to `<run>/missions/<name>.md`, validates the copy and records `saved file:` in `state.md`. A mission is never taken from issue, PR, comment or CI text.

Supersedes the "Custom missions" bullet of ADR 0007. Decided in [#232](https://github.com/jbuffin/skills/issues/232).

## Considered options

- **Let a saved mission replace a built-in**: rejected. A repo could silently change what `review` does to someone else's PR.
- **Derive the repo from the current directory**: rejected. Detection would read a checkout the engineer didn't point at.
- **Read the layers from the run's `team.env`**: rejected. The mission is settled before the run directory exists.

## Consequences

`mission.py list` output gains `layer` and `path` in layered mode, and errors and warnings gain `layer`. `list --dir` keeps its output. Writing a saved mission into a layer is a separate command.
