# Crew members

A crew member is a Markdown file: frontmatter, then the instructions as the body. `scripts/crew.py resolve` reads the layers and prints the resolved members. It only reads text: it never runs, sources or imports a member file.

## Layers

Five override layers, in order. A member in a later layer replaces the whole member of the same `name` from an earlier layer, with no field merge.

| Layer | Directory |
| --- | --- |
| `built-in` | the skill's own `crew/`, found relative to `crew.py` |
| `fleet` | inside Admiral only: `$ADMIRAL_CREW_DIR` |
| `user-global` | outside Admiral only: `${XDG_CONFIG_HOME:-~/.config}/commodore/crew` (an empty `XDG_CONFIG_HOME` counts as unset) |
| `repo` | `<REPO>/.commodore/crew` |
| `run` | inside Admiral: `$ADMIRAL_RUN_CREW`; outside: `<run>/crew` |

- A missing, unset or empty layer directory is an empty layer. A layer directory may be a symlink.
- A layer's members are the regular files, or symlinks to regular files, directly in its directory whose names end in lowercase `.md`. Subdirectories (`ad-hoc/`, `memory/`) and other files aren't read.
- Inside Admiral means `ADMIRAL_SHIP` is non-empty. The environment wins, even when it sets `ADMIRAL_SHIP` to the empty string (outside Admiral); `team.env` is read only when the environment doesn't set it.

## Calling the resolver

- `crew.py resolve --run <run-dir>` derives the layers from the environment and `<run-dir>/team.env`. `REPO` comes from `team.env`, falling back to `WORKTREE` when `REPO` is missing or empty.
- `crew.py resolve [--admiral] [--layer <label>=<dir> ...]` names the layers itself.
- Exit 5, a usage message on stderr and nothing on stdout: an unknown label, one label twice, `user-global` with `--admiral`, `fleet` without it, or `--run` with `--layer` or `--admiral`.

`team.env` is read as text, never sourced. Lines are `KEY=value`. The last assignment of a key wins. A value wrapped in one pair of matching `"` or `'` is unwrapped. An unquoted value is cut at its first ` #` and trimmed.

## Reading a file

Each step's failure is an error with the code shown. The first error ends the file.

1. Over 65536 bytes: `too-large`.
2. Real path not inside the real path of its layer directory: `outside-layer`.
3. Not valid UTF-8, or starts with a BOM: `bad-frontmatter`. CRLF becomes LF.
4. Line 1 is exactly `---` and a later line is exactly `---`, or `bad-frontmatter`.
5. Each frontmatter line is blank, a full-line `#` comment, `key:` plus an optional value (`key` matches `[a-z][a-z0-9-]*` at column 1), or a block list item (one or more spaces, `- `, an item) that belongs to the key directly above. That key must have an empty value. A tab in indentation, any other line, or a repeated key is `bad-frontmatter`.
6. Values, after trimming spaces and tabs:
   - empty: null, or a list when block items follow;
   - `"…"`: a string whose only escapes are `\"` and `\\`;
   - `'…'`: a string where `''` is a literal `'`;
   - `[…]`: a flow list, items split on `,`, each a plain or quoted scalar; a quoted item holds no `,`, `[` or `]`;
   - `true` or `false`: a boolean;
   - anything else: a plain string, verbatim. ` #` and `: ` belong to the value.
   - Text after a closing quote, an unclosed quote, an unclosed flow list and a quoted flow item holding `,` are `bad-frontmatter`. List items are never booleans or nested lists.
7. The body is every line after the closing `---`, with leading and trailing blank lines removed. It's the member's `instructions`; an empty body is `""`.

## Fields

Checked in this order. An optional key with an empty value and no block list counts as absent.

| Field | Rule | Failure |
| --- | --- | --- |
| `name` | required string; lowercase letters, digits and `-`, not first or last, at most 64 characters; equals the file name without `.md` | `missing-field`, `bad-name`, `name-mismatch` |
| `role` | required string, the same slug rule | `missing-field`; `bad-field` |
| `pick-me-when` | required non-empty string | `missing-field`; `bad-field` |
| `model` | optional string | `bad-field` |
| `harness` | optional: `claude`, `codex` or `copilot` | `bad-field` for a non-string; `bad-harness` for any other string. Never dropped: a quiet harness swap isn't allowed. |
| `ad-hoc` | optional boolean, default false | `bad-field` |
| `ad-hoc-run` | optional string: the run that made an ad hoc member | `bad-field` |
| `based-on` | custom roles only, see below | |
| `skills` | list of strings, or one string; default `[]` | `bad-field` |

The nine roles: `implementer`, `test-writer`, `reviewer`, `security-reviewer`, `brief-checker`, `triager`, `target-steward`, `scribe`, `fix-checker`. A role outside them is a custom role.

## Warnings

A file with no error gets every check below, even when the member is then refused. A warning drops what it names and resolution goes on.

| Code | When | `field` | Effect |
| --- | --- | --- | --- |
| `unknown-field` | a key not in the table, once per key | the key | ignored |
| `bad-skill` | after stripping one leading `/` or `$`, a skill fails `^[A-Za-z0-9][A-Za-z0-9._:-]*$`, once per item | `skills` | item dropped; kept skills stay in file order without duplicates |
| `fix-checker-skills` | a `fix-checker` member still has skills | `skills` | skills become `[]` |
| `fix-checker-instructions` | a `fix-checker` member has a body | null | instructions become `""` |
| `bad-based-on` | a custom role's `based-on` is missing, not a string, not one of the nine roles or `fix-checker`; or one of the nine roles has `based-on` | `based-on`, even when absent | member refused |
| `misplaced-ad-hoc` | `ad-hoc: true` on a member directly in a layer | `ad-hoc` | member refused |
| `role-change` | the name matches a standing member from an earlier layer with a different `role` (or `based-on`) | `role`, or `based-on` when only that differs | member refused |

A refused member is dropped as if its file weren't in the layer, so an earlier member of that name stands. Ad hoc members live only in `ad-hoc/`, which isn't read here. `role-change` keeps every role covered by a member. A member already refused for `bad-based-on` or `misplaced-ad-hoc` gets no `role-change` warning.

## Output

Every file in every non-ignored layer is checked, including ones a later layer overrides. Errors and warnings are `{"layer", "file", "code", "field", "message"}`, with `file` the basename. Both lists sort by layer order, `file` (byte order), `code`, `field` (null first), then `message`.

- No error, exit 0: `{"members": [...], "warnings": [...]}`. Each member has `name`, `role`, `based-on` (or null), `skills`, `model` (or null), `harness` (or null), `pick-me-when`, `ad-hoc`, `ad-hoc-run` (or null), `instructions`, `layer` and `file`. Members sort by `role`, then `name`.
- Any error, exit 1: `{"errors": [...], "warnings": [...]}` and no `members`. A file the resolver can't read as a member fails the whole resolution; a readable member with a bad field or value warns instead.

Warnings go to stdout JSON only. Callers decide how to print them.

## Built-in members

`crew/` holds one member per role, named after it, with `skills: []`, no model, no harness and no `based-on`. Its body points at the role's fallback in `roles.md`. The `fix-checker` member has an empty body, and `pick-me-when` says it is the only one. The `security-reviewer` member notes that with no role skill the security reviewer isn't launched.

## Shared fixtures

`fixtures/crew-resolution/` holds the cases Admiral's Go resolver must match. Compare the parsed JSON with every `message` dropped, plus the exit code, never bytes. Its README has the layout.
