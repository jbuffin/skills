# Mission files

A mission file is a Markdown file: frontmatter, then the procedure as the body. `scripts/mission.py` reads them and prints the parsed missions. It only reads text: it never runs, sources or imports a mission file.

## Calling the parser

- `mission.py list [--dir <dir>]` reads every file directly in `<dir>` whose name ends in lowercase `.md`. Without `--dir` it reads `missions/` next to `scripts/`. Subdirectories, other files, names starting with `.` (such as the macOS AppleDouble `._x.md`), names that aren't valid UTF-8 and anything that isn't a regular file or a symlink to one are skipped. Files are read in byte order of file name.
- `mission.py validate <file> [<file> ...]` runs the same checks on the named files. It skips the `outside-layer` check, so a symlink may point anywhere.
- Exit 5, a usage message on stderr and nothing on stdout: no subcommand, an unknown subcommand, an unknown flag, `--dir` twice, empty or with no value, an argument `list` doesn't take, or `validate` with no file.

A directory that is missing or can't be listed is one error, `unreadable`, with `file` null. This differs from `crew.py`, where a missing layer is empty: a mission directory that isn't there is a broken install. An existing empty directory lists `{"missions": [], "warnings": []}` with exit 0.

## Reading a file

These steps are `crew.py`'s "Reading a file" (see [crew-members.md](crew-members.md#reading-a-file)), with one `unreadable` code for the directory. Each failure is an error with the code shown. The first error ends the file.

1. Over 65536 bytes: `too-large`. A file that can't be statted, opened or read: `unreadable`.
2. `list` only: real path not inside the real path of the directory: `outside-layer`.
3. Not valid UTF-8, or starts with a BOM: `bad-frontmatter`. CRLF becomes LF.
4. Line 1 is exactly `---` and a later line is exactly `---`, or `bad-frontmatter`.
5. Frontmatter lines, values and lists follow `crew.py`'s rules: a `key:` line, a block list item under an empty key, `"…"`, `'…'`, `[…]`, `true` or `false`, or a plain string. A tab in indentation, a repeated key or any other line is `bad-frontmatter`.
6. The body is every line after the closing `---` with leading and trailing blank lines removed. It is the mission's `procedure`.

## Fields

Checked in this order. The first failure refuses the file. A role is one of the nine roles: `implementer`, `test-writer`, `reviewer`, `security-reviewer`, `brief-checker`, `triager`, `target-steward`, `scribe`, `fix-checker`.

| Field | Rule | Failure |
| --- | --- | --- |
| `name` | required lowercase slug of at most 64 characters; equals the file name without `.md` | `missing-field`; `bad-name`, also for a non-string; `name-mismatch` |
| `pick-me-when` | required string | `missing-field`; `bad-field` for a list or boolean |
| `source-of-truth` | required string | `missing-field`; `bad-field` for a list or boolean |
| `task-force` | required list, flow or block, of distinct roles, at least one | `missing-field`; `bad-field` for a string, a boolean, an empty list, a repeat or an item that isn't a role |
| `builder` | required, a role in `task-force` | `missing-field`; `bad-field` |
| `checker` | required: a role in `task-force`, or exactly `engineer` | `no-checker` when absent or blank; `checker-is-builder` when it equals `builder`; `bad-field` for anything else, a list included |
| `stop-rule` | required string | `missing-field`; `bad-field` for a list or boolean |
| `delivery` | required string | `missing-field`; `bad-field` for a list or boolean |

- Blank means absent, null or only spaces and tabs; a no-break space is content. A blank `name`, a quoted one included, is `missing-field`.
- `task-force` lists roles only. `engineer` is not a role: it is `bad-field` in `task-force` and as `builder`. It is valid only as the `checker`, the engineer's gate. Casting a member to each role stays with `crew.py cast` at run time.
- Only the nine roles are accepted: a custom role in `task-force` is `bad-field`. That is a limit of the built-in missions' format.
- A mission with no `checker`, or whose `checker` equals its `builder`, is refused.
- An empty body is `missing-field` with `field` `body`. This differs from `crew.py`, where an empty body is allowed: a mission without a procedure has nothing to run.

## Warnings

A file with no error gets the check below. A warning drops what it names and reading goes on.

| Code | When | `field` | Effect |
| --- | --- | --- | --- |
| `unknown-field` | a key not in the table, once per key | the key | ignored |

## Output

Both commands print JSON on stdout. Errors and warnings are `{"file", "code", "field", "message"}`, with `file` the basename (null for a directory that can't be listed). Both lists sort by `file` (null first, then byte order), `code`, `field` (null first), then `message`.

- No error, exit 0: `{"missions": [...], "warnings": [...]}`. Each mission has `name`, `pick-me-when`, `source-of-truth`, `task-force`, `builder`, `checker`, `stop-rule`, `delivery`, `file` (the basename) and `procedure` (the body). Missions sort by `name`.
- Any error, exit 1: `{"errors": [...], "warnings": [...]}` and no `missions`. One refused file fails the whole call. The warnings are those of the files without an error; a refused file has none.
