# Windows environments for agent-skill scripts: WSL2, Git Bash, native PowerShell

Research for [#101](https://github.com/jbuffin/skills/issues/101) under the map
[#93 Windows support](https://github.com/jbuffin/skills/issues/93). Read 2026-10-14. Throwaway branch; never merged.

This builds on the closed Linux research and doesn't repeat it:
[script-language](https://github.com/jbuffin/skills/blob/research/script-language/docs/research/script-language.md),
[harnesses-cross-platform](https://github.com/jbuffin/skills/blob/research/harnesses-cross-platform/docs/research/harnesses-cross-platform.md),
[portable-commands](https://github.com/jbuffin/skills/blob/research/portable-commands/docs/research/portable-commands.md),
[secret-storage](https://github.com/jbuffin/skills/blob/research/secret-storage/docs/research/secret-storage.md) and
[mattpocock-skills-audit](https://github.com/jbuffin/skills/blob/research/mattpocock-skills-audit/docs/research/mattpocock-skills-audit.md).
It assumes the Linux map ships bash 3.2 glue plus stdlib Python 3.9+.

## Answer

| | WSL2 | Git Bash (native Windows) | Native PowerShell |
| --- | --- | --- | --- |
| Runs bash 3.2 glue | Yes, unchanged | Yes (bash 5.3 in Git for Windows) | No. Needs a `bash.exe` it can find, or a `.ps1` twin |
| Runs stdlib Python | Yes, unchanged | Yes, through the native Windows `python`/`py` | Yes (`python`/`py`, not `python3`) |
| Process groups, `kill -- -pg`, `ps -o` | Yes (Linux) | **No.** MSYS `ps` has no `-o`, and MSYS signals don't reach native `.exe` children | No. Job Objects or `taskkill /T` |
| Claude Code | Bash tool, Monitor, sandbox all work | Bash and Monitor tools work. PowerShell tool is also on and is "the primary shell" | PowerShell tool only. No Monitor tool, so no watchdog |
| Codex | Linux sandbox (bubblewrap) | Never uses Git Bash. Only an explicit `bash.exe` call from PowerShell works | `pwsh` → `powershell.exe` → `cmd.exe`. MXC kills leftover children when the foreground command exits |
| Copilot CLI | `bash` tool | Not used. Tool is `powershell` | `powershell` tool. `--available-tools bash` leaves no shell |
| Cost to us | Docs plus a "you're in WSL2" check | Find `bash.exe`, rewrite process control in Python, and accept that only Claude uses it | Same as Git Bash, plus `.ps1` twins or Python for every glue script, `PowerShell(...)` allows, and native secrets |

**Recommendation for the map:** support **WSL2 as the Windows platform**. Inside WSL2 every harness and every script behaves as
it does on Linux, so the Linux map's work carries over at no extra cost. Native Windows (Git Bash or PowerShell) needs
three pieces of new work. Process control has to be rebuilt on Job Objects. Every harness except Claude-with-Git-Bash
needs PowerShell-shaped allow rules. Secrets need Credential Manager plus DPAPI. Two of the three harnesses can't run
our bash at all without an explicit `bash.exe` call. No published skill repo does more than add a parallel `.ps1` for a
single script.

Whatever the map picks, make one change now: **pin the 25 extensionless driver scripts to LF.** `.gitattributes` covers
`*.sh`, `*.zsh` and `*.py` only, so `drivers/*/{launch,stop,status,...}` get CRLF on a default Git for Windows checkout
(see [Line endings](#line-endings-and-gitattributes)).

## Environment by environment

### WSL2

- **Scripts:** a WSL2 distro is a Linux system, so the Linux map's findings apply unchanged. WSL1 is out, because Codex
  dropped it at 0.115 and Claude Code has no sandbox there (harnesses research).
- **Where the repo lives:** Microsoft says "store your files in the WSL file system if you are working in a Linux
  command line", meaning `/home/<user>/Project`, not `/mnt/c/...` ([WSL filesystems][wsl-fs]). Files on `/mnt/c` take
  their Linux permissions from the Windows ACLs unless the `metadata` mount option is on, and `chmod` there only
  toggles the read-only attribute ([WSL file permissions][wsl-perm]). So both the exec bit and the `0600` on a secrets
  file are meaningless on `/mnt/c`, while the Linux home behaves normally.
- **Two Gits:** "You will need to install Git on each file system that you intend to use it with", and Microsoft says
  to keep line endings consistent with `.gitattributes` when one folder is shared between Windows and WSL
  ([Git on WSL][wsl-git]). A repo cloned by Windows Git into `C:\` and opened from WSL gets Windows' `core.autocrlf`.
- **Interop:** WSL runs Windows `.exe`s and Windows runs `wsl <cmd>`, and arguments pass through unmodified
  ([WSL filesystems][wsl-fs]). That is the only bridge to Credential Manager, through GCM (secret-storage research).
- **Detecting it:** `wsl --list --verbose` (from Windows) shows each distro's WSL version
  ([WSL basic commands][wsl-cmd]). From inside, the kernel release contains `microsoft` and `/proc/sys/fs/binfmt_misc/WSLInterop`
  exists ([WSL filesystems][wsl-fs] documents that file). The `microsoft` kernel-string check is a common convention,
  **not documented by Microsoft**.
- **What the harnesses need:** install each harness inside the distro (all three document this). Claude: "WSL setups do
  not need Git for Windows", and sandboxing works on WSL2 only ([Claude setup][cc-setup]). Codex: a separate `CODEX_HOME`
  from Windows-side Codex (harnesses research). Copilot supports Windows "from within PowerShell and WSL" (harnesses research).

### Git Bash (Git for Windows / MSYS2)

- **bash version:** Git for Windows 2.56 ships Bash 5.3.15 ([GfW release notes][gfw-notes]). bash 3.2 code runs
  as is, and GNU coreutils supply `stat -c %Y`, `date -r` and `mktemp` (portable-commands research).
- **Python isn't in Git for Windows.** Scripts call the native Windows Python. `python3` exists under the Python Install
  Manager but is "not meant to be widely used or recommended"; `python` and `py` are the supported commands
  ([Using Python on Windows][py-win]). Without an install, `python` may open the Store instead of running
  ([same page, troubleshooting][py-win]). The `py` launcher understands `#!/usr/bin/env python3` shebangs as "virtual
  commands", so the shebang form stays portable ([same page][py-win]).
- **Path mangling:** arguments to native programs that start with `/` are rewritten to Windows paths (for example
  `/usr/bin/bash.exe` → `C:\Program Files\Git\usr\bin\bash.exe`). Turn it off per command with `MSYS_NO_PATHCONV=1`, or
  double the leading slash (`//c`) ([GfW release notes, Known issues][gfw-notes]). MSYS2 upstream uses
  `MSYS2_ARG_CONV_EXCL` instead ([MSYS2 paths][msys-paths]). This is the cause of the `cmd.exe /c start` hang in the
  mattpocock audit. It also hits any `gh api /repos/...`-style argument. Our scripts have none today (grep at `origin/main`).
- **Process control doesn't carry over.** MSYS `ps` takes `-aeflsW`, `-u` and `-p`, and **has no `-o`**. Its PGID
  column covers Cygwin/MSYS processes only, and the `WINPID` column is the real Windows PID ([Cygwin `ps`][cyg-ps]).
  `kill` signals "other Cygwin programs". For "native Windows processes not started by Cygwin processes" you need
  `kill -f`, which uses Windows `TerminateProcess` ([Cygwin `kill`][cyg-kill]). `codex.exe`, `copilot.exe`,
  `claude.exe` and `python.exe` are native Windows programs. So `ps -o pgid= -p`, `kill -- -$pg` and `set -m` group
  tracking in the drivers fail or miss the real harness process under Git Bash (the second half is inferred from the
  Cygwin docs and **unverified** on a Windows host).
- **Which `bash` you get:** `C:\Windows\System32\bash.exe` is the WSL launcher, which Microsoft lists as a deprecated
  command ([WSL basic commands][wsl-cmd]). A PATH lookup for `bash` from PowerShell can land on it. Prior art
  (superpowers `run-hook.cmd`, below) checks the Git for Windows install paths first and skips System32, Sysnative and the
  WindowsApps alias. Claude Code reads `CLAUDE_CODE_GIT_BASH_PATH` when it can't find Git Bash ([Claude setup][cc-setup]).
- **Harness fit:** only Claude Code uses Git Bash as its shell, and then only when Git for Windows is installed. Even
  then, on claude.ai and Console accounts the PowerShell tool is also on and "Claude treats PowerShell as the primary
  shell. The Bash tool remains available for POSIX scripts" ([Claude tools reference][cc-tools]). Codex never selects
  bash on Windows. Its default is `pwsh`, then `powershell`, then `cmd.exe` ([Codex `shell_detect.rs`][cx-src]). Copilot's
  Windows tool is `powershell` ([Copilot command reference][cp-cmdref]). Under Codex and Copilot, Git Bash is only
  reachable as `& 'C:\Program Files\Git\bin\bash.exe' script` from PowerShell.

### Native PowerShell

- **Two products.** Windows ships Windows PowerShell 5.1 (`powershell.exe`), which gets no new features. PowerShell 7
  (`pwsh.exe`) is a separate install ([What is Windows PowerShell?][ps-what]). Codex and Claude prefer `pwsh` and fall
  back to `powershell.exe` ([cx-src], [cc-tools]). Copilot needs PowerShell 6+ (harnesses research) and has a
  `powershellFlags` setting, default `-NoProfile -NoLogo` ([Copilot config][cp-config]). So scripts must assume 5.1 unless a
  preflight demands 7.
- **Quoting differs by version.** PowerShell 7.3 changed native argument passing. Windows PowerShell 5.1 (`Legacy`) drops
  embedded quotes and empty strings, and that is "a breaking change" between the two
  ([about_Parsing][ps-parsing]). This is why the mattpocock audit saw `gh --jq '…"…"…'` break under 5.1. Use `--%` or
  `Start-Process` to avoid it ([same page][ps-parsing]).
- **Execution policy.** The default is `RemoteSigned` on Windows computers, and `Restricted` (no scripts) when nothing is
  set on a client ([about_Execution_Policies][ps-exec]). `-ExecutionPolicy Bypass` on the command line sets a
  process-scope policy that Group Policy still overrides ([same page][ps-exec]). Claude Code already spawns PowerShell
  with `-ExecutionPolicy Bypass` at process scope ([cc-tools]). openai/skills invokes its `.ps1` as `powershell
  -ExecutionPolicy Bypass -File ...` ([screenshot SKILL.md][oa-shot]). A skill can't count on the harness doing this for
  Codex or Copilot.
- **Scripts:** bash glue doesn't run. Each glue script needs a `.ps1` twin, or has to move into Python. Python stdlib
  runs natively, with the process caveats below.

## Process control without POSIX process groups

What the drivers do today (portable-commands research): start the harness in a new process group, record the pgid, check
liveness with `kill -0` and `ps -o pgid=`, and stop with `kill -- -$pg`.

| Need | POSIX (today) | Windows native | Source |
| --- | --- | --- | --- |
| Start detached in own group | `setsid` / `setpgrp` / `set -m` | `subprocess.Popen(..., creationflags=CREATE_NEW_PROCESS_GROUP \| DETACHED_PROCESS)`. `start_new_session` and `process_group` are POSIX-only | [py-subprocess] |
| Kill the whole tree | `kill -- -$pg` | A **Job Object**: `AssignProcessToJobObject`, then `TerminateJobObject`, or `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Children made with `CreateProcess` join the job by default, and jobs nest since Windows 8 | [job-objects] |
| Kill tree, no handle kept | — | `taskkill /pid N /t /f` "ends the specified process and any child processes started by it" | [taskkill] |
| Liveness | `kill -0 $pid` | **Not `os.kill(pid, 0)`.** On Windows any signal other than `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` "will cause the process to be unconditionally killed by the TerminateProcess API". Use `OpenProcess` + `GetExitCodeProcess` via `ctypes`, `tasklist /fi "PID eq N"`, or `Get-Process -Id` | [py-os] |
| Graceful stop | `SIGTERM` | `CTRL_BREAK_EVENT`, only to a child started with `CREATE_NEW_PROCESS_GROUP` that shares the console. Otherwise `terminate()` is `TerminateProcess` | [py-subprocess], [py-os] |
| Parent PID after parent exits | reparented to 1 | "on Windows it is still the same id, which may be already reused by another process" | [py-os] |
| File lock | `fcntl.flock` / `zsystem flock` | `msvcrt.locking`. Or the `mkdir` lock, which works on every platform | [py-msvcrt] |

Implications:

- **Job Objects are the only reliable tree kill.** `taskkill /t` walks parent links from a live PID. Because a dead
  parent's PID can be reused ([py-os]), an orphaned grandchild escapes it. That last step is inference, **unverified**.
  A Job Object has to be created and held by a live supervisor process (it's destroyed when its last handle closes), so the
  supervisor needs to be a long-running Python process. stdlib has no Job Object API; `ctypes` calls to
  `kernel32` cover it.
- **Codex's MXC sandbox:** "Remaining child processes stop when the foreground command exits" ([cx-winsandbox]). A
  commodore session *running under Codex on native Windows* can't leave a teammate running in the background from
  inside its sandbox. WSL2 avoids this.
- **The Claude driver** relies on `claude --bg` and its supervisor, which already handles Windows (`daemon.lock` fix,
  `taskkill` recovery; harnesses research). It needs the least change.

## File mtimes

- **Commands:** Python `os.stat(f).st_mtime` works everywhere. Git Bash: `stat -c %Y`. PowerShell:
  `[DateTimeOffset]::new((Get-Item f).LastWriteTimeUtc).ToUnixTimeSeconds()`. NTFS stores UTC with 100 ns resolution.
  FAT write times have 2 s resolution ([File Times][ms-ftime], [py-os]).
- **The catch for the watchdog:** "When writing to a file, the last write time is not fully updated until all handles
  that are used for writing are closed", and "the only guarantee about a file time stamp is that the file time is
  correctly reflected when the handle that makes the change is closed" ([File Times][ms-ftime]). The harnesses keep their
  transcript and log files open while they append. So on native Windows, `watch-teammates` and the driver `status`
  scripts can see a file as stale while the teammate is still writing to it. Use **size growth** (`st_size`) as the
  progress signal, or as a second check. How often NTFS updates mtime in practice is **unverified**. Inside WSL2 (ext4)
  this doesn't apply.

## Paths

- **In SKILL.md and scripts:** Anthropic says to use forward slashes even on Windows (script-language research). Windows
  APIs and Python accept `/`. Git Bash rewrites `/x` arguments for native programs (above).
- **Config roots:** `%USERPROFILE%\.claude`, `%USERPROFILE%\.codex` and `%USERPROFILE%\.copilot`. Copilot's cache is
  `%LOCALAPPDATA%/copilot` (harnesses research).
- **Hard-coded paths:** `/bin/zsh`, `/bin/sleep`, `/Applications/...` and `${TMPDIR:-/tmp}` don't exist natively. In Git
  Bash `/tmp` maps into the Git install, which native programs can't see as `/tmp`. Python's `tempfile.gettempdir()`
  is the portable form.
- **Long paths:** Git for Windows refuses to check out paths over 260 characters unless `core.longPaths` is set
  ([GfW release notes][gfw-notes]). Worktrees under `.claude/worktrees/agent-<id>/skills/engineering/...` get close to that.
- **Symlinks:** cloning with symlinks needs Developer Mode or special permissions, otherwise they're off by default
  ([GfW release notes][gfw-notes]). The repo has no tracked symlinks. But `npx skills add` symlinks into agent
  directories by default and offers `--copy` "when symlinks aren't supported" ([vercel-labs/skills README][skills-cli]).
  Whether it falls back on Windows by itself is **unverified**.

## Line endings and .gitattributes

- Git for Windows' installer defaults to "Checkout Windows-style, commit Unix-style line endings", which sets
  `core.autocrlf=true` ([GfW `install.iss`][gfw-iss]).
- `text=auto` only marks a file as text. When `eol` is unset, the working-tree ending comes from `core.autocrlf` /
  `core.eol`, and it is CRLF on Windows. `eol=lf` keeps LF at checkout ([gitattributes][gitattr]).
- This repo's `.gitattributes` is `* text=auto` plus `*.sh`, `*.zsh`, `*.py` → `text eol=lf`. **The 25 extensionless
  driver scripts** (`skills/engineering/agent-teammates/scripts/drivers/{claude,codex,copilot}/*`, for example `launch`,
  `stop`, `status`, `tail`, `preflight`) and the `tests/bin/*` fakes match only `text=auto`. On a default Git for Windows
  checkout they get CRLF and the shebang breaks (`zsh\r`/`bash\r`). That covers Git Bash, and also WSL when the clone
  lives on `C:` and was made by Windows Git. Fix: add a path rule such as
  `skills/**/scripts/** text eol=lf` and `tests/bin/** text eol=lf`. If the map adds `.ps1`, `.cmd` or `.bat` files, pin
  `*.cmd`/`*.bat` to `eol=crlf`, because cmd.exe needs CRLF. `.ps1` works with either ending (not checked against a source).
- `umask 077` / mode 0600 does nothing on NTFS or on `/mnt/c` without metadata ([wsl-perm]; `os.chmod` on Windows only
  sets the read-only flag, [py-os]).

## What each harness needs, per environment

### Claude Code

- WSL2: install in the distro. Everything works as on Linux, including the sandbox ([cc-setup]).
- Native + Git for Windows: the Bash tool runs our bash, and Monitor (the watchdog) is available only in this setup
  ([cc-tools]). The PowerShell tool is also on, as the primary shell. Expect Claude to reach for PowerShell unless the
  SKILL.md says `bash scripts/x.sh`. Any `Bash(...)` deny rule silently turns the PowerShell tool off ([cc-tools]).
  `CLAUDE_CODE_GIT_BASH_PATH` points at a nonstandard install ([cc-setup]).
- Native without Git Bash: PowerShell tool only, no Monitor, so no watchdog.
- Skill frontmatter `shell: powershell` runs a skill's `` !`cmd` `` blocks in PowerShell ([cc-tools]). This is the
  only harness-level per-skill shell switch we found.

### Codex

- WSL2: Linux sandbox, so bubblewrap or user namespaces are needed (harnesses research).
- Native: the shell is PowerShell, never Git Bash ([cx-src]). The sandbox is MXC, then `elevated`, then `unelevated`, and
  under MXC leftover child processes are killed ([cx-winsandbox]). Codex's own Windows docs don't mention bash or `.sh` at
  all ([cx-winsandbox]). Whether Git Bash's `bash.exe` runs inside the restricted-token sandbox is **unverified**.

### Copilot CLI

- WSL2: the `bash` tool and `shell(...)` rules, as on Linux.
- Native: the tool names are `powershell`, `read_powershell`, `write_powershell`, `stop_powershell` and
  `list_powershell` ([cp-cmdref]). So the driver's read-only `--available-tools bash view glob grep` must name
  `powershell` on Windows, or the teammate has no shell. In managed policy, `PowerShell(...)` is "matched the same way as
  `Shell(...)`" ([cp-config]). But the `--allow-tool`/`--deny-tool` kinds table lists only `shell`, described as
  "Shell command execution" ([cp-cmdref]). Whether `shell(git:*)` passed on the command line governs the `powershell`
  tool is **still unverified**. Probe it on a Windows host before relying on it.

## Prior art: how published skill repos handle Windows

- **Parallel `.ps1` next to the POSIX script.** openai/skills `screenshot` documents a "Windows (PowerShell helper)"
  section that runs `powershell -ExecutionPolicy Bypass -File <skill>/scripts/take_screenshot.ps1`, next to a
  `python3 ... take_screenshot.py` path for macOS/Linux ([oa-shot]). It is the only `.ps1` in openai/skills.
- **Windows-only skills in `.ps1`.** github/awesome-copilot has 15 `.ps1` files across skills such as `copilot-pr-autopilot`
  and `winmd-api-search`, and separate `.sh`-only skills. Only two skills pair languages, both as a `.ps1` next to a
  `.py`: `optimize-simplicite-logs` (`SimpliciteLog2Json.ps1` + `simplicite-log2json.py`) and `batch-script-progress`
  (examples in `.ps1`, `.py` and `.mjs`). None pairs `.ps1` with `.sh` (tree listing, 2026-10-14).
- **Find Git Bash and run bash.** obra/superpowers `hooks/run-hook.cmd` is a cmd/bash polyglot. On Windows it tries
  `C:\Program Files\Git\bin\bash.exe`, `C:\Program Files (x86)\...`, then `%LOCALAPPDATA%\Programs\Git\bin\bash.exe`,
  then `where $PATH:bash`, skipping System32, Sysnative and `WindowsApps` (the WSL launchers). If it finds no bash it
  exits 0. It keeps hook scripts extensionless "so Claude Code's Windows auto-detection -- which prepends `bash` to any
  command containing .sh -- doesn't interfere" ([superpowers run-hook.cmd][sp-hook]; that Claude behaviour is their
  claim and isn't in Anthropic's docs).
- **Decline native Windows.** mattpocock/skills declined a PowerShell wizard and leaves it to Windows users' own
  AGENTS.md (mattpocock audit, mattpocock/skills#954).
- **Nobody** ships Job-Object process supervision, a Windows credential helper, or CI on a Windows runner for skill
  scripts. Our drivers would be the first.

## CI note (for the map's "how CI proves it")

GitHub-hosted Windows runners default to `pwsh`. `shell: bash` on Windows uses "the bash shell included with Git for
Windows" ([workflow syntax][gh-wf]). So a `windows-latest` job can run our bash tests under Git Bash and the Python tests
natively. It can't test WSL2 without extra setup. Whether the Windows runner image includes a ready WSL2 distro is
**unverified**.

## Open questions

1. Does `--allow-tool 'shell(git:*)'` govern Copilot's `powershell` tool on Windows? (probe)
2. Does Git Bash `bash.exe` start under Codex's `unelevated`/`elevated` restricted token? (probe)
3. How stale does NTFS mtime get on a file a harness holds open for appending? (probe, or just use size)
4. Does `npx skills add` fall back to copies on Windows without Developer Mode? (probe)

## Sources

[wsl-fs]: https://learn.microsoft.com/en-us/windows/wsl/filesystems
[wsl-perm]: https://learn.microsoft.com/en-us/windows/wsl/file-permissions
[wsl-git]: https://learn.microsoft.com/en-us/windows/wsl/tutorials/wsl-git
[wsl-cmd]: https://learn.microsoft.com/en-us/windows/wsl/basic-commands
[job-objects]: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
[taskkill]: https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill
[ms-ftime]: https://learn.microsoft.com/en-us/windows/win32/sysinfo/file-times
[ps-what]: https://learn.microsoft.com/en-us/powershell/scripting/what-is-windows-powershell
[ps-parsing]: https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing
[ps-exec]: https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies
[py-os]: https://docs.python.org/3/library/os.html
[py-subprocess]: https://docs.python.org/3/library/subprocess.html
[py-msvcrt]: https://docs.python.org/3/library/msvcrt.html
[py-win]: https://docs.python.org/3/using/windows.html
[gitattr]: https://git-scm.com/docs/gitattributes
[gfw-notes]: https://github.com/git-for-windows/build-extra/blob/main/ReleaseNotes.md
[gfw-iss]: https://github.com/git-for-windows/build-extra/blob/main/installer/install.iss
[msys-paths]: https://www.msys2.org/docs/filesystem-paths/
[cyg-ps]: https://cygwin.com/cygwin-ug-net/ps.html
[cyg-kill]: https://cygwin.com/cygwin-ug-net/kill.html
[cc-setup]: https://code.claude.com/docs/en/setup
[cc-tools]: https://code.claude.com/docs/en/tools-reference
[cx-src]: https://github.com/openai/codex/blob/main/codex-rs/shell-command/src/shell_detect.rs
[cx-winsandbox]: https://learn.chatgpt.com/docs/windows/windows-sandbox
[cp-cmdref]: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
[cp-config]: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference
[gh-wf]: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
[oa-shot]: https://github.com/openai/skills/blob/main/skills/.curated/screenshot/SKILL.md
[sp-hook]: https://github.com/obra/superpowers/blob/main/hooks/run-hook.cmd
[skills-cli]: https://github.com/vercel-labs/skills/blob/main/README.md

- WSL: [filesystems][wsl-fs], [file permissions][wsl-perm], [Git on WSL][wsl-git], [basic commands][wsl-cmd]
- Win32: [Job Objects][job-objects], [taskkill][taskkill], [File Times][ms-ftime]
- PowerShell: [What is Windows PowerShell?][ps-what], [about_Parsing][ps-parsing], [about_Execution_Policies][ps-exec]
- Python: [os][py-os], [subprocess][py-subprocess], [msvcrt][py-msvcrt], [Using Python on Windows][py-win]
- Git / MSYS2 / Cygwin: [gitattributes][gitattr], [Git for Windows release notes][gfw-notes],
  [Git for Windows installer][gfw-iss], [MSYS2 filesystem paths][msys-paths], [Cygwin ps][cyg-ps], [Cygwin kill][cyg-kill]
- Harnesses: [Claude setup][cc-setup], [Claude tools reference][cc-tools], [Codex shell_detect.rs][cx-src],
  [Codex Windows sandbox][cx-winsandbox], [Copilot command reference][cp-cmdref], [Copilot config][cp-config]
- CI: [GitHub Actions workflow syntax][gh-wf]
- Prior art: [openai/skills screenshot][oa-shot], [obra/superpowers run-hook.cmd][sp-hook], [vercel-labs/skills][skills-cli],
  github/awesome-copilot tree (GitHub API, 2026-10-14)
