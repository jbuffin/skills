# Crew members

A crew member is a Markdown file: frontmatter, then the instructions as the body. `scripts/crew.py resolve` reads the layers and prints the resolved members. It only reads text: it never runs, sources or imports a member file.

## Layers

Five override layers, in order. The ad hoc directory is not one of them: see [Ad hoc members](#ad-hoc-members). A member in a later layer replaces the whole member of the same `name` from an earlier layer, with no field merge.

| Layer | Directory |
| --- | --- |
| `built-in` | the skill's own `crew/`, found relative to `crew.py` |
| `fleet` | inside Admiral only: `ADMIRAL_CREW_DIR` |
| `user-global` | outside Admiral only: `${XDG_CONFIG_HOME:-~/.config}/commodore/crew` (an empty `XDG_CONFIG_HOME` counts as unset) |
| `repo` | `<REPO>/.commodore/crew` |
| `run` | inside Admiral: `ADMIRAL_RUN_CREW`; outside: `<run>/crew` |

- A missing, unset or empty layer directory is an empty layer. A layer directory may be a symlink.
- A layer's members are the regular files, or symlinks to regular files, directly in its directory whose names end in lowercase `.md`. Subdirectories (`ad-hoc/`, `memory/`; `ad-hoc/` is read separately), other files, any name starting with `.` (such as the macOS AppleDouble `._x.md`) and any name that isn't valid UTF-8 are skipped.
- Inside Admiral means `ADMIRAL_SHIP` is non-empty. The environment wins, even when it sets `ADMIRAL_SHIP` to the empty string (outside Admiral); `team.env` is read only when the environment doesn't set it. `ADMIRAL_CREW_DIR` and `ADMIRAL_RUN_CREW` work the same way: the environment when it sets the variable, even empty, otherwise `team.env`. Inside Admiral an unset or empty one is an empty layer, with no fallback to `<run>/crew`.

## Calling the resolver

- `crew.py resolve --run <run-dir>` derives the layers from the environment and `<run-dir>/team.env`. `REPO` comes from `team.env`, falling back to `WORKTREE` when `REPO` is missing or empty.
- `crew.py resolve [--admiral] [--layer <label>=<dir> ...]` names the layers itself. `--layer ad-hoc=<dir> --run-id <id>` adds the ad hoc directory; they go together, with or without `--admiral`.
- `--admiral` only selects which labels are allowed: `fleet` with it, `user-global` without it.
- Exit 5, a usage message on stderr and nothing on stdout: an unknown label, one label twice, `user-global` with `--admiral`, `fleet` without it, `--run` with `--layer` or `--admiral`, `--run` twice, `--run` with no value or an empty one, `--layer ad-hoc` without `--run-id` (or the reverse), `--run-id` twice, empty, or with a control character, or `--run-id` with `--run`.

`team.env` is read as text, never sourced. Lines are `KEY=value`. The last assignment of a key wins. A value wrapped in one pair of matching `"` or `'` is unwrapped. An unquoted value is cut at its first space-then-`#` and trimmed.

## Casting

`crew.py cast --run <run-dir> [--pick <role>=<member> ...] [--unlock <role> ...] [--save]` picks one member for each role and prints the cast table for `profile.md` (Role, Member, Based on, Skills, Instructions, Model, Harness, Source). Errors and warnings go to stderr. Exit 1 when the layers hold errors or a role has several run-layer members; exit 4 when a locked harness is unavailable; exit 5 on a bad call, a missing `<run-dir>/team.env`, or a `HARNESS` that isn't `^[a-z0-9-]+$`.

- A run-layer member for a role is a **pin** and wins over any pick. Two pins for one role are an error unless `--pick` names one.
- Otherwise the pick wins. Otherwise the member from the latest layer wins for each of the nine roles, ties broken by name in byte order, with a warning when the role had several candidates. An ad hoc member is never a default and doesn't count as a candidate there; a role whose only candidates are ad hoc has no default, like a custom role.
- A custom role is in the cast only when pinned or picked. It launches with its `based-on` role's contract.
- A member with a `harness` other than the run's `HARNESS` is **locked**: it runs on that harness, and `cast` treats every role it fills per member. A `harness` equal to the run's is no lock.
- Each skill goes through the driver of the harness the member runs on (`has-skill`, and its `SKILL_PREFIX` in the table); one that harness can't load is dropped with a warning. A driver without `has-skill` keeps every skill, with one warning.
- Each `model` goes through [the `model` launch rule](#fields).
- `--save` writes `<run>/cast.json` (the explicit picks and the cast; each entry has `ad-hoc` and `ad-hoc-run` as resolve gave them) and rewrites the `# crew models (crew.py cast)` block of `MODEL_<ROLE>='<model>'` lines in `team.env`. The next `cast` keeps the saved picks; a saved pick whose member is gone is dropped with a warning.
- Availability: `cast` runs `harness-available.sh <run> <h>` once per locked harness. It prints the script's `WARN` lines, and for an unavailable one an `UNAVAILABLE <role>: <member> is locked to <h>: <reason>` line on stderr per role, `<h> (unavailable)` in the table's Harness cell, and exits 4 after printing the table. Exit 4 saves nothing. The fix checker follows the implementer, so it has no line of its own.
- `--unlock <role>` (once per role) runs a locked role on the run's harness for this run. The role must be in the cast with a lock, or `cast` exits 5. The member's `model` is dropped with a warning (it names a model of the locked harness), the Harness cell reads `<run harness> (unlocked from <h>)`, and no availability check runs for it. `--save` records the roles in `cast.json` as `"unlocks"` (sorted); the next `cast` keeps them, and drops one whose role is no longer locked, with a warning.
- The fix checker runs on the implementer's harness and model: its own member's `harness` is ignored with a warning.
- A locked member with no `model` gets a warning to set `MODEL_<ROLE>` and `EFFORT_<ROLE>` for its harness (from `agent-teammates/references/harness-<h>.md`); the implementer's warning adds the fix checker's two.
- `--save` also writes `HARNESS_<ROLE>='<h>'` for each locked role of the nine (and `HARNESS_FIX_CHECKER` when the implementer is locked), after the `MODEL_<ROLE>` lines in the same block, and removes stale ones. `HARNESS` is left alone. A custom role has no line: pass `--harness <h>` when launching it.
- A leftover `roles.json` (user-global outside Admiral, `<REPO>/.commodore/roles.json`, `<run>/roles.json`) is never read; `cast` warns once per file and points to `setup-commodore`'s `convert-roles.py`.

## Reading a file

Each step's failure is an error with the code shown. The first error ends the file.

1. Over 65536 bytes: `too-large`. A file that can't be statted, opened or read: `unreadable`.
2. Real path not inside the real path of its layer directory: `outside-layer`.
3. Not valid UTF-8, or starts with a BOM: `bad-frontmatter`. CRLF becomes LF.
4. Line 1 is exactly `---` and a later line is exactly `---`, or `bad-frontmatter`.
5. Each frontmatter line is blank, a full-line `#` comment, `key:` plus an optional value (`key` matches `[a-z][a-z0-9-]*` at column 1), or a block list item (one or more spaces, a dash, a space, then an item) that belongs to the key directly above. That key must have an empty value. Blank and comment lines may come between a key and its items. A tab in indentation, any other line, or a repeated key is `bad-frontmatter`.

   Blank, empty and whitespace mean only the ASCII space and tab, here and everywhere below: a no-break space is content.
6. Values, after trimming spaces and tabs:
   - empty: null, or a list when block items follow;
   - `"…"`: a string whose only escapes are `\"` and `\\`;
   - `'…'`: a string where `''` is a literal `'`;
   - `[…]`: a flow list, items split on `,`, each a plain or quoted scalar; a quoted item holds no `,`, `[` or `]`;
   - `true` or `false`: a boolean;
   - anything else: a plain string, verbatim. A space-then-`#` and a colon-then-space belong to the value.
   - Text after a closing quote, an unclosed quote, an unclosed flow list and a quoted flow item holding `,` are `bad-frontmatter`.
   - List items are never booleans: `true` in a list is the string. An empty item is `bad-frontmatter`, in a flow list (`[a,,b]`, a trailing `,`) and in a block list (a dash with nothing after it, with or without the space). An item starting with `[` is `bad-frontmatter`, block or flow.
7. The body is every line after the closing `---`, with leading and trailing blank lines (only spaces and tabs) removed. It's the member's `instructions`; an empty body is `""`.

## Fields

Checked in this order. An optional key with an empty value and no block list counts as absent.

| Field | Rule | Failure |
| --- | --- | --- |
| `name` | required string; lowercase letters, digits and `-`, not first or last, at most 64 characters; equals the file name without `.md` | `missing-field`; `bad-name`, also for a non-string; `name-mismatch` |
| `role` | required string, the same slug rule | `missing-field`; `bad-field`, also for a non-string |
| `pick-me-when` | required string with something other than spaces and tabs in it | `missing-field`, also for only spaces and tabs; `bad-field` |
| `model` | optional string | `bad-field` |
| `harness` | optional: `claude`, `codex` or `copilot` | `bad-field` for a non-string; `bad-harness` for any other string. Never dropped: a quiet harness swap isn't allowed. |
| `ad-hoc` | optional boolean, default false; `true` only in a member of this run in the ad hoc directory | `bad-field` |
| `ad-hoc-run` | optional string: the run id of the run that made an ad hoc member. A filter, never a path | `bad-field` |
| `based-on` | custom roles only, see below | |
| `skills` | list of strings, or one string; default `[]` | `bad-field` |

**The `model` launch rule.** The resolver keeps `model` as written. Every launcher applies this rule before it passes the value on: Commodore's `crew.py cast` and Admiral's `crew launch --member`. A `model` that doesn't match `^[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,127}$` is dropped with a warning and the role keeps its default. The fix checker's `model` is ignored, since it runs on the implementer's model.

The nine roles: `implementer`, `test-writer`, `reviewer`, `security-reviewer`, `brief-checker`, `triager`, `target-steward`, `scribe`, `fix-checker`. A role outside them is a custom role.

## Warnings

A file with no error gets every check below, even when the member is then refused. A warning drops what it names and resolution goes on.

| Code | When | `field` | Effect |
| --- | --- | --- | --- |
| `unknown-field` | a key not in the table, once per key | the key | ignored |
| `bad-skill` | after stripping one leading `/` or `$`, a skill fails `^[A-Za-z0-9][A-Za-z0-9._:-]*$`, once per item | `skills` | item dropped; kept skills stay in file order without duplicates |
| `fix-checker-skills` | a `fix-checker` member still has skills | `skills` | skills become `[]` |
| `fix-checker-instructions` | a `fix-checker` member has a body | null | instructions become `""` |
| `bad-based-on` | a custom role's `based-on` is missing, not a string, not one of the nine roles other than `fix-checker`; or one of the nine roles has `based-on` | `based-on`, even when absent | member refused |
| `misplaced-ad-hoc` | `ad-hoc: true` on a member directly in a layer | `ad-hoc` | member refused |
| `ad-hoc-name-taken` | an ad hoc member of this run has the name of a standing member | `name` | member refused; names the layer that holds the name |
| `ad-hoc-fix-checker` | an ad hoc member of this run has role `fix-checker` | `role` | member refused |
| `ad-hoc-unreadable` | a file in the ad hoc directory names this run in an `ad-hoc-run` line but fails the filter; or the directory can't be listed | null | file skipped |
| `ad-hoc-dir-refused` | the ad hoc directory, or `crew/` or `commodore/` above it, is a symlink, or its real path is the repo or inside it or inside a `.commodore/` directory | null | the directory is skipped; `file` is null |
| `role-change` | the name matches a standing member from an earlier layer with a different `role` (or `based-on`) | `role`, or `based-on` when only that differs | member refused |

A refused member is dropped as if its file weren't in the layer, so an earlier member of that name stands. Ad hoc members live only in the ad hoc directory, which has its own rules below. `role-change` keeps every role covered by a member. A member already refused for `bad-based-on` or `misplaced-ad-hoc` gets no `role-change` warning.

## Ad hoc members

An ad hoc member is one the lead writes for a single run. It lives in the ad hoc directory, outside the repo, and only the run that wrote it resolves it. It is read after the run layer and never replaces a member. It doesn't go in a layer's table because it is not an override layer.

- **Where.** Inside Admiral: `<ADMIRAL_CREW_DIR>/ad-hoc/` (unset or empty `ADMIRAL_CREW_DIR`: none). Outside: `${XDG_CONFIG_HOME:-~/.config}/commodore/crew/ad-hoc/`. Never the repo, `.commodore/` or the run layer. One file per member, `ad-hoc/<name>.md`, with `ad-hoc: true` and `ad-hoc-run: "<run id>"`.
- **Run id.** The real path of the `--run` directory (`os.path.realpath`), compared as an exact string, never read from `team.env`, the environment or a member file. A run id with a control character, `"` or `\` is an error (`ERROR bad run id`, exit 1). `--run-id <id>` names it in explicit mode.
- **Filter.** A file is this run's only when it parses with no error, has `ad-hoc: true`, and `ad-hoc-run` equals the run id. Every other file is skipped without a warning, even a broken one, so another run's file never fails this run. A skipped file whose text has this run's `ad-hoc-run` line gets one `ad-hoc-unreadable` warning.
- **This run's members** get the usual field warnings with `layer: "ad-hoc"` (`misplaced-ad-hoc` doesn't apply). A name held by a standing member, from any layer, is `ad-hoc-name-taken`; a `fix-checker` is `ad-hoc-fix-checker`. Neither replaces anything, so `role-change` doesn't apply.
- **Safety.** Outside Admiral `ad-hoc/`, `crew/` and `commodore/` may not be symlinks; inside Admiral `ad-hoc/` may not be (`ADMIRAL_CREW_DIR` may). The directory's real path may not be the repo, inside it or inside a `.commodore/` directory. Otherwise the whole directory is skipped with `ad-hoc-dir-refused`. A missing directory is silent.
- **Casting.** `cast --pick <role>=<name>` casts one, and the table's Source cell reads `ad-hoc`. It is never a default.

`crew.py adhoc --run <run-dir> --name <name> --role <role> --pick-me-when <line> [--based-on <role>] [--skill <skill> ...] [--model <model>] [--harness <h>] --body-file <file>` writes one:

- The body file must be a regular file whose real path is inside `<run-dir>/prompts/`. It is read, never run.
- The frontmatter keys come in this order: `name`, `role`, `based-on`, `pick-me-when`, `skills`, `model`, `harness`, `ad-hoc`, `ad-hoc-run`. Strings are double-quoted.
- Exit 1 with one `ERROR` line and nothing written when: `name` or `role` isn't a slug; the role is `fix-checker`; `--based-on` is missing for a custom role or given for a built-in one; `--harness` isn't `claude`, `codex` or `copilot`; `--model` fails the launch rule; a skill is invalid; `--pick-me-when` is blank or has a newline; the name is taken by a member or by any `<name>.md` already in the ad hoc directory; the body is unreadable, not UTF-8 or over 65536 bytes with the frontmatter; the directory fails the safety rules; or `resolve --run` has errors. Exit 5 for a bad call.
- It creates the ad hoc directory (mode 0700; the parent too outside Admiral, but inside Admiral `ADMIRAL_CREW_DIR` must exist) and the file (mode 0600, created through a temp file and a link that can't replace anything). Then it resolves the run again. When the member doesn't come back, it removes the file and exits 1. On success it prints `wrote <path>`.
- To keep a member, the engineer moves it up out of `ad-hoc/` and drops `ad-hoc` and `ad-hoc-run`.

## Output

Every file in every non-ignored layer is checked, including ones a later layer overrides; the ad hoc directory is the exception (see [Ad hoc members](#ad-hoc-members): it skips files silently and never errors). `layer` is a layer label, or `ad-hoc`. Errors and warnings are `{"layer", "file", "code", "field", "message"}`, with `file` the basename. A layer directory that exists but can't be listed is one error, `unreadable`, with `file` null. Both lists sort by layer order, `file` (null first, then byte order), `code`, `field` (null first), then `message`.

- No error, exit 0: `{"members": [...], "warnings": [...]}`. Each member has `name`, `role`, `based-on` (or null), `skills`, `model` (or null), `harness` (or null), `pick-me-when`, `ad-hoc`, `ad-hoc-run` (or null), `instructions`, `layer` and `file`. Members sort by `role`, then `name`.
- Any error, exit 1: `{"errors": [...], "warnings": [...]}` and no `members`. A file in a layer the resolver can't read as a member fails the whole resolution; a readable member with a bad field or value warns instead.

Warnings go to stdout JSON only. Callers decide how to print them.

## Built-in members

`crew/` holds one member per role, named after it, with `skills: []`, no model, no harness and no `based-on`. Its body points at the role's fallback in `roles.md`. The `fix-checker` member has an empty body, and `pick-me-when` says it is the only one. The `security-reviewer` member notes that with no role skill the security reviewer isn't launched.

## Shared fixtures

`fixtures/crew-resolution/` holds the cases Admiral's Go resolver must match. Its README has the layout and how to compare.
