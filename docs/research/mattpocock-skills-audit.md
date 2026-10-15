# mattpocock skills: scripts and platform assumptions

Research for [#98](https://github.com/jbuffin/skills/issues/98), part of
[Map: Linux support](https://github.com/jbuffin/skills/issues/92) (Windows notes feed
[#93](https://github.com/jbuffin/skills/issues/93)). Findings only; fixes would be upstream issues.

## Answer

Two of the 27 skills in the plugin ship scripts, both bash: `wizard/template.sh` and
`diagnosing-bugs/scripts/hitl-loop.template.sh`. Neither is macOS-only. Both use
`#!/usr/bin/env bash` and only bash 3.2-compatible features, so they run on Linux as they are. On Windows they
need Git Bash or WSL. Nothing in the plugin calls `pbcopy`, `osascript`, `security`, BSD `stat`, `/Applications`
or Homebrew. The other assumptions are in the prose: a POSIX shell for heredocs and `--jq` quoting in the
issue-tracker docs, a desktop with a URL opener for the HTML report, and a temp dir. Every one of these
already names its Linux and Windows equivalent. Linux has no blocker. On Windows outside WSL,
the bash templates can't run without Git Bash, and Git Bash has one known bug that upstream hasn't fixed.

## Sources

- Installed plugin: `~/.claude-personal/plugins/cache/mattpocock/mattpocock-skills/1.3.1/`
  (`.claude-plugin/plugin.json` lists the 27 skills and points at `https://github.com/mattpocock/skills`).
- Upstream `mattpocock/skills` `main` @ `49dd158` (2026-10-09). This is also version 1.3.1. It has the same set of script
  files as the installed copy. `git hash-object` matches `hitl-loop.template.sh` and
  `improve-codebase-architecture/SKILL.md`. `wizard/template.sh` differs: upstream has
  unreleased fixes from #1237 (wraps the stages in `run_wizard`, decodes double-quoted `.env` values, adds a `tput clear`
  fallback). None of those fixes is platform-related.
- Upstream issues: [#963](https://github.com/mattpocock/skills/issues/963) (open),
  [#954](https://github.com/mattpocock/skills/issues/954), [#272](https://github.com/mattpocock/skills/issues/272),
  [#1105](https://github.com/mattpocock/skills/issues/1105), and `SCOPE.md` ("The bar").

## Every executable file in the repo

| File | In plugin? | Language | Shebang | Platform notes |
| --- | --- | --- | --- | --- |
| `skills/engineering/wizard/template.sh` | yes (wizard) | bash | `#!/usr/bin/env bash` | See [wizard](#wizard). |
| `skills/engineering/diagnosing-bugs/scripts/hitl-loop.template.sh` | yes (diagnosing-bugs) | bash | `#!/usr/bin/env bash` | Uses `read -r -p` and `printf -v`, both bash-only, available since bash 3.1. The usage line says `bash hitl-loop.template.sh`. |
| `skills/misc/git-guardrails-claude-code/scripts/block-dangerous-git.sh` | **no** (`misc/` is frozen and not in `plugin.json`) | bash | `#!/bin/bash` | Needs `jq`. A hard `/bin/bash` path fails on NixOS. Needs bash on Windows. |
| `skills/in-progress/setup-ts-deep-modules/dependency-cruiser.config.cjs` | no | JS config | n/a | Portable. |
| `scripts/link-skills.sh` | no (maintainer dev-only) | bash | `#!/usr/bin/env bash` | `readlink -f` needs macOS 12.3 or later. `ln -sfn` makes copies, not symlinks, in Git Bash unless `MSYS=winsymlinks:nativestrict` is set. |
| `scripts/list-skills.sh` | no (dev) | bash | `#!/usr/bin/env bash` | Portable POSIX tools. |
| `scripts/sync-plugin-version.mjs` | no (release) | Node ESM | `#!/usr/bin/env node` | Portable. |

The installed copies of both templates are mode `0644`, not executable. The skills tell the agent to copy the file and
then `chmod +x` it (wizard) or to run it as `bash <file>` (hitl-loop), so the missing exec bit causes no failure.

Upstream has no `.gitattributes`. On a Windows clone with `core.autocrlf=true`, which the Git for Windows installer
sets by default, the `.sh` files are checked out with CRLF line endings, and bash then fails with
`$'\r': command not found`. I inferred this from the missing file; I did not reproduce it.

## Per skill

These are the 27 skills that `plugin.json` ships. Under "Shell in SKILL.md" I list the commands and shell constructs
the skill tells the agent to use.

| Skill | Ships scripts | Shell in SKILL.md / refs | Linux | Windows outside WSL |
| --- | --- | --- | --- | --- |
| ask-matt | no | none (prose; describes `/wizard` as an interactive bash script) | ok | ok |
| diagnosing-bugs | **bash** template | `git bisect run`; the HITL loop is bash | ok | needs Git Bash for the HITL loop |
| grill-with-docs | no | none | ok | ok |
| triage | no | `gh` via tracker docs | ok | see tracker docs below |
| improve-codebase-architecture | no | `git log --oneline`; temp dir `$TMPDIR` → `/tmp` → `%TEMP%`; opener `xdg-open` / `open` / `start` | ok on desktop; headless has no `xdg-open`, so the user only gets the path | ok (prose names `%TEMP%` and `start`) |
| setup-matt-pocock-skills | no | `git remote -v`, `gh`/`glab label create`; tracker docs use heredocs and `--jq '…IN("OWNER",…)'` | ok | heredocs are POSIX-shell syntax; nested quotes in `--jq` break under Windows PowerShell 5.1 native-arg passing (inference) |
| tdd | no | none | ok | ok |
| to-spec, to-tickets | no | tracker commands (or `.scratch/` files for a local tracker) | ok | as tracker docs |
| wayfinder | no | tracker commands (`gh api … dependencies/blocked_by`) | ok | as tracker docs |
| implement, implement-spec | no | git worktrees and branches (prose) | ok | ok |
| prototype | no | `pnpm`/`python`/`bun <path>`; logic demo is an HTML file | ok | ok |
| research | no | none | ok | ok |
| domain-modeling, codebase-design | no | none | ok | ok |
| code-review | no | `git diff A...HEAD`, `git log`, `git rev-parse` | ok | ok |
| pr | no | none (examples are prose) | ok | ok |
| retro | no | none | ok | ok |
| wizard | **bash** template | `bash -n`, `shellcheck`, `chmod +x` | ok | needs Git Bash or WSL; see below |
| grill-me, grilling, teach, to-questionnaire, wait-what, writing-for-agents | no | none | ok | ok |
| handoff | no | temp dir `$TMPDIR` → `/tmp`; `%TEMP%` on Windows | ok | ok (prose; the fix for #272 / #1105) |

## wizard

`template.sh` ([upstream](https://github.com/mattpocock/skills/blob/main/skills/engineering/wizard/template.sh)):

- **bash-only.** It uses `[[ ]]`, arrays, `printf -v`, `read -e` (Readline), `read -s`, `read -p` and `${var//…}`.
  bash 3.2 (macOS) and 4/5 (Linux) both support all of these. Under POSIX `sh` or `dash` it fails. The
  `env bash` shebang avoids that unless someone runs `sh wizard.sh`.
- **Portable tools only:** `tput` (guarded; falls back to ANSI escapes), `grep -E`, `mktemp` with no
  arguments (works on both GNU and BSD), `cat`, `rm`, and `gh` (guarded, so a missing `gh` only records a "skipped").
- **`open_url`** tries `wslview`, then `explorer.exe`, then `xdg-open`, then `open`, and falls back to a warning. On headless Linux
  it warns and the human visits the URL by hand. That is a graceful fallback, not a failure.
- **Windows outside WSL:**
  - It doesn't run from PowerShell or cmd at all (no bash).
  - Under Git Bash, `explorer.exe <url>` exits non-zero even when the browser opens, so the wizard prints a false
    "couldn't open a browser" warning. This is upstream [#963](https://github.com/mattpocock/skills/issues/963)
    (open; the triage brief suggests `cmd.exe //c start "" "$url"`, because a bare `/c` gets mangled by MSYS and hangs).
  - `write_env` creates `.env` with `umask 077`. NTFS ignores this, so the file isn't mode `0600`
    (inference).
- Upstream declined a PowerShell variant ([#954](https://github.com/mattpocock/skills/issues/954), not planned).
  Their stance is that the wizard is bash by design and Windows users should add "write /wizard scripts in
  PowerShell" to their own `AGENTS.md`/`CLAUDE.md`. `SCOPE.md` rejects OS- and harness-specific branches.

## diagnosing-bugs HITL loop

`hitl-loop.template.sh` is plain bash (`read -r -p`, `printf -v`, `set -euo pipefail`). It runs on Linux. On
Windows it needs Git Bash or WSL. It also needs an interactive TTY on every platform: the harness's
Bash tool has no stdin, so the human has to run it in their own terminal. That limit is not platform-specific.

## Prose-level assumptions (no script)

- **Heredocs** for multi-line issue bodies (`issue-tracker-github.md`, `issue-tracker-gitlab.md`). This is POSIX-shell
  syntax. PowerShell would need a here-string or `--body-file`.
- **`gh --jq` filters with embedded double quotes inside single quotes** (`issue-tracker-github.md:24`). This works
  in POSIX shells and Git Bash. Windows PowerShell 5.1 strips embedded quotes when it passes arguments to native exes
  (inference; PowerShell 7.3+ fixed this).
- **Temp dir and file opener** (handoff, improve-codebase-architecture). These are already written per OS. The only Linux gap
  is headless machines with no `xdg-open`, where the skill falls back to printing the path.

## What would fail

- **Linux (desktop and headless):** nothing breaks. Small issues: a headless machine prints a path or
  "couldn't open a browser" warning instead of opening a browser (wizard, improve-codebase-architecture).
  `block-dangerous-git.sh` (not in the plugin) needs `jq` and `/bin/bash`.
- **Windows outside WSL:**
  1. The wizard and HITL templates can't run without Git Bash.
  2. Under Git Bash, the wizard shows a false browser-open warning (#963).
  3. CRLF checkout breaks both `.sh` templates if `core.autocrlf=true` (no `.gitattributes` upstream).
  4. Heredoc and `--jq` quoting in the tracker docs assume a POSIX shell. Claude Code's Bash tool on Windows runs Git Bash,
     so they work there. They fail in a PowerShell-based harness.
  5. `.env` gets no owner-only permissions.

## Suggested upstream issues

These are not filed. Under `SCOPE.md` an issue needs an observed failure in a real session.

- Add a `.gitattributes` with `*.sh text eol=lf`, to protect the templates from CRLF on Windows clones.
- Fix `open_url`'s Windows branch per #963 (already open; add a +1 only if it is reproduced).
- Change `block-dangerous-git.sh` to `#!/usr/bin/env bash`. This one is moot: `misc/` is frozen and every issue there gets closed.
