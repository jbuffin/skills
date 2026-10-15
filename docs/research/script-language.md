# Research: which language portable agent-skill scripts should use

Ticket: [#94](https://github.com/jbuffin/skills/issues/94), for [Map: Linux support #92](https://github.com/jbuffin/skills/issues/92).
Windows notes are flagged **[Windows]** for [Map: Windows support #93](https://github.com/jbuffin/skills/issues/93).
Researched 2026-10-14. Throwaway branch; never merged.

## Answer

Use **two languages, chosen per script**:

1. **bash, written to bash 3.2** (`#!/usr/bin/env bash`, shellcheck-clean) for thin glue: run a few CLIs (`git`, `gh`,
   a harness CLI), check exit codes, print a line. This is what every published skill repo ships when it ships shell, and
   it is the shell every harness's Bash tool already uses.
2. **Python 3, stdlib only, floor 3.9** for anything with real logic: maps/sets, JSON, file mtimes, timestamps, locks,
   process groups, parsing CLI output. Python removes every BSD/GNU split the repo hits today (`stat -f %m`, `date`,
   `flock`, `setsid`/`setpgrp`) and is the only option of the five that also runs natively on Windows.

Drop zsh. Don't use POSIX `sh` (too weak, and bash is present everywhere sh is that matters). Don't use Node (not on
any OS by default, and no harness the repo drives needs it).

Keep deterministic, fragile steps in scripts; Anthropic's guidance is explicit that those belong in scripts, not prose
(see below). Prose is for judgment calls, not for replacing `verify-report`, `push-branch` or the secret helpers.

## What the spec and Anthropic guidance say

- **agentskills spec, `scripts/`**: "Contains executable code that agents can run. Scripts should: be self-contained or
  clearly document dependencies; include helpful error messages; handle edge cases gracefully. Supported languages
  depend on the agent implementation. Common options include Python, Bash, and JavaScript."
  ([spec](https://agentskills.io/specification#scripts))
- **agentskills spec, `compatibility` field** (≤500 chars) is where environment requirements go, e.g. "Requires git,
  docker, jq, and access to the internet" or "Requires Python 3.14+ and uv". "Most skills do not need" it.
  ([spec](https://agentskills.io/specification#compatibility-field))
- **agentskills "Using scripts in skills"**: its SKILL.md examples invoke scripts through the interpreter, not the exec
  bit: `bash scripts/validate.sh "$INPUT_FILE"`, `python3 scripts/process.py --input results.json`. It says to state
  prerequisites in SKILL.md (or `compatibility`), to move complex commands into "a tested script in `scripts/`", and
  that scripts must never prompt interactively ("a hard requirement of the agent execution environment"). Self-contained
  dependency declaration is shown for Python (PEP 723 + `uv run`), Deno, Bun and Ruby; no shell is listed there.
  ([using scripts](https://agentskills.io/skill-creation/using-scripts))
- **Anthropic best practices, degrees of freedom**: use *low freedom* ("specific scripts, few or no parameters") when
  "operations are fragile and error-prone", "consistency is critical", or "a specific sequence must be followed"; use
  *high freedom* (text instructions) when "multiple approaches are valid" and "decisions depend on context".
  ([best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices#set-appropriate-degrees-of-freedom))
- **Anthropic, utility scripts**: pre-made scripts are "more reliable than generated code", "save tokens", "ensure
  consistency across uses"; "Prefer scripts for deterministic operations"; "Solve, don't defer" (handle errors in the
  script). Every code example on the page is Python; the only shell is the invocation line.
  ([best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices#advanced-skills-with-executable-code))
- **Anthropic, paths** **[Windows]**: "Always use forward slashes in file paths, even on Windows." Also: "Avoid assuming
  tools are installed"; list required packages.

So: neither source picks a language. Both treat Python and bash as the default pair, and both say deterministic,
fragile operations stay in scripts. Moving logic into prose is endorsed only where the step is a judgment call.

## What published skill repos ship

Files under any `*/scripts/` directory, by extension, from each repo's default branch (GitHub tree API, 2026-10-14):

| Repo | Python | JS (`.mjs/.js/.cjs`) | Shell (`.sh` / no-ext) | PowerShell | zsh |
| --- | --- | --- | --- | --- | --- |
| anthropics/skills | 62 | 0 | 2 (`#!/bin/bash`) | 0 | 0 |
| openai/skills | 42 | 14 | 4 (`#!/bin/bash`, `#!/usr/bin/env bash`) | 1 | 0 |
| github/awesome-copilot | 40 | 13+ | 3 (`#!/bin/bash`) | 14 | 0 |
| vercel-labs/agent-skills | 0 | 15 | 0 | 0 | 0 |
| obra/superpowers | 0 | 2 | 2 `.sh` + 5 extensionless, all `#!/usr/bin/env bash` | 0 | 0 |
| mattpocock/skills | 0 | 0 | 2 (`#!/bin/bash`) | 0 | 0 |

- **No surveyed repo ships a zsh script.** Shell scripts are bash, never `sh`-only and never zsh.
- Python dominates where scripts carry logic (Anthropic, OpenAI, GitHub). Node shows up only in skills that are about
  JS tooling (Vercel's).
- **Cross-platform pattern [Windows]**: openai/skills `screenshot` ships `take_screenshot.py` for "macOS and Linux
  (Python helper)" and a separate `take_screenshot.ps1` for Windows, with macOS-only bits isolated in
  `ensure_macos_permissions.sh` and Swift helpers. awesome-copilot ships whole Windows-only skills in `.ps1`.
- **Bash on Windows [Windows]**: obra/superpowers' `hooks/run-hook.cmd` is a cmd/bash polyglot that finds Git for
  Windows' `bash.exe` (standard, per-user, then `PATH`, skipping the WSL launchers) and runs extensionless bash scripts
  through it. Its comment says scripts are extensionless so that Claude Code's Windows handling, "which prepends
  `bash` to any command containing .sh", doesn't interfere (a claim from that repo, not verified in Anthropic docs).

## What each platform and harness provides

| | macOS | Ubuntu/Debian | GitHub `ubuntu-24.04` runner | Windows |
| --- | --- | --- | --- | --- |
| bash | `/bin/bash` **3.2.57** (checked on macOS 27.0.1) | 5.x, `Essential: yes` | 5.2.21 | Git Bash 5.x if Git for Windows installed; WSL |
| zsh | 5.9, default login shell since 10.15 | not installed by default | **not installed** (this repo's CI `apt-get install`s it) | none |
| python3 | `/usr/bin/python3` 3.9.6 from Command Line Tools (same CLT that provides `git`) | 3.x on server/desktop images | 3.12.3 | `python`/`py`; `python3` exists but "not meant to be widely used or recommended" |
| node | not shipped | not shipped | 22.x | not shipped |

Sources: Apple, "Use zsh as the default shell on your Mac": "Starting with macOS 10.15, your Mac uses zsh as the default
login shell" ([support.apple.com/102360](https://support.apple.com/en-us/102360)); bash version checked locally;
Debian `bash` control file "Priority: required / Essential: yes"
([sources.debian.org](https://sources.debian.org/src/bash/5.2.37-2/debian/control/)); runner contents from
[actions/runner-images Ubuntu2404-Readme.md](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md)
and [Windows2025-Readme.md](https://github.com/actions/runner-images/blob/main/images/windows/Windows2025-Readme.md);
Python on Windows from [docs.python.org/3/using/windows.html](https://docs.python.org/3/using/windows.html) §4.1.1–4.1.2.

Harnesses **[Windows]**:

- **Claude Code**: supports Bash, Zsh, PowerShell or CMD. On native Windows, "With Git for Windows, Claude Code uses Git
  Bash for the Bash tool"; without it, "Claude Code runs shell commands via the PowerShell tool". WSL is a supported
  option and "do[es] not need Git for Windows". The native binary needs no Node.
  ([setup](https://code.claude.com/docs/en/setup#set-up-on-windows))
- **Codex**: on Windows "can run natively in PowerShell with a Windows sandbox instead of requiring WSL"; WSL is
  suggested "when you need Linux tooling". ([Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox))
- **Copilot CLI**: prerequisites list "(On Windows) PowerShell v6 or higher"; npm install needs Node 22+.
  ([install](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli))
  The docs don't name the Windows command shell; PowerShell is the inference.

## The options compared

| Option | macOS | Linux | Windows | Fit for this repo |
| --- | --- | --- | --- | --- |
| **zsh** (today) | yes | must install; absent on runners and stock Debian/Ubuntu | none (not in Git Bash) | Worst. No linter: ShellCheck doesn't support zsh, so CI only runs `zsh -n` (syntax). No prior art in any surveyed repo. |
| **POSIX sh** | yes (`/bin/sh` is bash 3.2) | yes (dash) | Git Bash/WSL only | No arrays, no `[[`, no `local` guarantee. Not worth it: everywhere `sh` runs for us, bash does too. |
| **bash ≤3.2** | yes, built in | yes, Essential | Git Bash (Claude Code's Bash tool) or WSL; not Codex/Copilot native | Good for glue. Lacks associative arrays, `mapfile`, `${v,,}` (all bash 4.0), namerefs, negative subscripts, `wait -n` (4.3), `EPOCHSECONDS` (5.0) ([bash NEWS](https://tiswww.case.edu/php/chet/bash/NEWS)). Fully linted by shellcheck in CI already. External tools still split BSD/GNU. |
| **Python 3.9+ stdlib** | yes (CLT; present wherever `git` is) | yes on normal installs | **native** (`py`/`python`) | Best for logic. `os.stat().st_mtime`, `time.time()`, `fcntl.flock`, `subprocess.Popen(start_new_session=True)`, `json` replace `stat -f`, `date`, `zsystem flock`, `perl setpgrp`, `jq`. Already a `REQUIRED_TOOLS` entry (`ci-branch-check.py`, `team-init.sh` inline JSON). Linted by ruff in CI. POSIX process calls (`os.killpg`, `setpgrp`) don't exist on Windows. |
| **Node** | install | install | install | No. Not shipped anywhere; the harnesses' native binaries don't need it. Only Vercel's JS-domain skills use it. |

## Against this repo's scripts

Inventory: 57 files under `skills/engineering/*/scripts/`, ~2,400 lines; every executable is `#!/bin/zsh` except
`run-preflight/scripts/ci-branch-check.py`. zsh-only features in use (need rewriting for bash 3.2):

- `${0:A:h}`, `${x:t}`, `${x:h}` path modifiers everywhere (≈40 sites); bash needs `cd "$(dirname "$0")" && pwd -P`.
- Parameter flags `${(f)…}`, `${(k)…}`, `${(u)…}`, `${(P)…}`, `${(L)…}`, `${(j:, :)…}` in `team-preflight.sh`,
  `role-skills.sh`, `team-init.sh`, `watch-teammates.sh`, `preflight.sh`.
- Glob qualifiers `*(N)`, `*(/N)`, numeric glob `<->` (`preflight.sh`, `team-init.sh`, `watch-teammates.sh`).
- Associative arrays (`seen`, `blocked`, `lastalert` in `watch-teammates.sh`): **not in bash 3.2**.
- `zmodload zsh/system` + `zsystem flock` (`evidence.sh`): bash has no portable equivalent (`flock(1)` is util-linux,
  not on macOS).
- `print -r` (≈90 sites), `&!`, `setopt`.

Platform-specific externals: BSD `stat -f %m` (9 sites; CI shims it), `security` (Keychain, 51 sites), `perl -e
'setpgrp…'` (Copilot driver), `ps -o pgid=`/`kill -- -$pg` (process groups), `jq`, `python3`.

Suggested split (input for the map's "which logic moves" question, not a decision):

- **Python**: `watch-teammates` (assoc state, mtimes, timing), `evidence` (lock), `verify-report`, the Copilot/Codex
  driver supervisors and liveness checks (process groups), `role-skills`/`team-init` JSON work (drops `jq`),
  `team-preflight`.
- **bash 3.2**: `push-branch`, `retask`, `retasked`, `close-teammate`, `teammate-tail`, `detect-harness`, driver
  `launch/send/stop/status/tail` wrappers that only call the harness CLI, `secret-run` (wrapping the per-platform
  secret command).

## Conventions to adopt with this choice

- Shebangs `#!/usr/bin/env bash` and `#!/usr/bin/env python3`; keep the exec bit, but **write SKILL.md commands as
  `bash scripts/x.sh` / `python3 scripts/x.py`** like the agentskills examples, so they don't depend on the exec bit or
  shebang handling. **[Windows]** `python3` is a discouraged alias on Windows; a Windows path will need `py`/`python`
  or a launcher.
- Target bash 3.2 explicitly; CI can enforce it by running the bash tests under macOS `/bin/bash` (macOS job) and
  shellcheck everywhere.
- Python: stdlib only, `requires 3.9` (macOS CLT version), no PEP 723/uv (not installed by default anywhere).
- State `python3` and `bash` in each skill's `compatibility` field.

## Windows summary [Windows]

- bash scripts run on Windows only through Git Bash (Claude Code's Bash tool when Git for Windows is installed) or WSL.
  Codex and Copilot run PowerShell natively, so bash scripts there need an explicit `bash.exe` (the superpowers
  `run-hook.cmd` pattern) or WSL.
- Python stdlib scripts run natively, except POSIX process-group calls (`os.setpgrp`, `os.killpg`) and `fcntl`;
  Windows equivalents are `subprocess.CREATE_NEW_PROCESS_GROUP` and `msvcrt.locking`.
- zsh has no Windows story outside WSL.
- Prior art for native Windows is a parallel `.ps1` next to the Python/bash script (openai `screenshot`, awesome-copilot),
  i.e. per-OS scripts rather than one universal shell.
- Moving logic toward Python now shrinks a future Windows port to the process-control and secret-store edges.

## Open questions

- Whether the Codex/Copilot drivers' process-group supervision can be expressed portably at all, or stays POSIX-only
  (the Windows map's "process control" item).
- Exact minimum Python on target Linux hosts (headless servers without python3 exist, e.g. minimal containers); a
  preflight check already covers this via `REQUIRED_TOOLS`.
