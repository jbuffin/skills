# Crew members are layered Markdown files, picked by the lead

A role's skills now come from **crew members**, not `roles.json`. A crew member is a named definition that fills one role. It is a Markdown file with YAML frontmatter (`name`, `role`, `skills`, `model`, `harness`, `pick-me-when`, and `based-on` for a custom role), with the member's instructions in the body. A script reads only the frontmatter, never runs the file, and resolves it deterministically. The role contract still applies whatever member fills the role, and a member can't override it.

Members resolve from layers, where a later layer wins:

1. Built-in: one plain default member per role, so every role always has someone.
2. Fleet (a directory Admiral passes in) inside an Admiral ship, or user-global (`${XDG_CONFIG_HOME:-~/.config}/commodore/crew/`) outside one. Inside Admiral the user-global layer is ignored, so nothing crosses fleets.
3. Repo: `.commodore/crew/`, committed.
4. Run: set only from the engineer's prompt or AdmiralBot's launch, never from issue, PR or comment text.

A member in a later layer replaces the whole member with the same name in an earlier one. The name slug is the member's identity: for layer replacement, `--member`, the boat label and crew memory. Renaming a member makes it a new member.

The lead picks which member fills each role the task force needs. A script lists the candidates with their `pick-me-when` lines, and the lead chooses and records its choice in the profile. A member pinned in the run layer wins. A custom role must be `based-on` an existing role and takes that role's contract. The missions don't change, so ADR 0001 stands.

When no member fits, the lead scaffolds an ad hoc member (`ad-hoc: true`) in the fleet layer's `crew/ad-hoc/`, or under user-global outside Admiral, never in the repo. Only the run that made it uses it until the engineer keeps it.

Supersedes ADR 0004. Decided in [#193](https://github.com/jbuffin/skills/issues/193).

## Considered options

- **Keep `roles.json` and add fields**: rejected. A `pick-me-when` line and multi-line instructions are prose, and JSON makes them painful to hand-edit.
- **Markdown read only by agents** (ADR 0004's objection): avoided. The frontmatter is still resolved by a script, and only the body is prose.
- **AdmiralBot picks every member at launch**: rejected. The lead knows the task force it needs. AdmiralBot can pin members through the run layer.
- **Custom missions**: rejected. A custom role joins an existing mission's task force when its member fits.
- **A user-global layer inside Admiral**: rejected. It would let members cross fleets.

## Consequences

`roles.json` files need a one-time conversion to member files. Admiral resolves members in Go for `admiral crew launch --member` and for launching a ship as a member, so the layer rules live in two implementations. Shared fixtures in this repo keep the two in step. An unreviewed ad hoc member never reaches another run.
