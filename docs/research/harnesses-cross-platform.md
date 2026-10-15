# How Claude Code, Codex and Copilot CLI run on Linux and Windows

Research for [#97](https://github.com/jbuffin/skills/issues/97) (map [#92](https://github.com/jbuffin/skills/issues/92), Windows map [#93](https://github.com/jbuffin/skills/issues/93)). Read 2026-10-14 against each vendor's current docs and, for Codex, its source. Version-sensitive: re-check before building on a detail.

## Answer

- **Linux:** all three harnesses are officially supported, and every harness feature the agent-teammates drivers use (`claude --bg` / `claude agents --json`, `codex exec --json` + `exec resume`, `copilot -p --session-id`) exists there unchanged, with config and sessions in the same `~/.<harness>` paths as on macOS. What breaks on Linux is our own script tooling (BSD `stat -f %m`, a `#!/bin/zsh` that needs zsh installed), plus one harness prerequisite: Codex's sandbox (which the Codex driver relies on for every role) needs `bubblewrap`, or unprivileged user namespaces, and Ubuntu's AppArmor may block it.
- **Windows (native):** all three run natively, but none of them gives the agent a POSIX shell by default. Claude Code uses Git Bash *if installed* and otherwise PowerShell. Codex uses PowerShell, falling back to `cmd.exe`. Copilot uses PowerShell, and its shell tool there is named `powershell`, not `bash`. Our drivers are zsh scripts built on POSIX process groups, `ps` and `kill -- -pgid`, so they don't run on native Windows as written, under any harness.
- **Windows (WSL2):** all three document WSL as a supported way to run on Windows. Inside WSL2 a harness behaves as it does on Linux, and so do our scripts. WSL1 is out for Codex (≥0.115) and gives Claude Code no sandbox.

## Per harness

### Claude Code

| | Linux | Windows |
| --- | --- | --- |
| Supported | Ubuntu 20.04+, Debian 10+, Alpine 3.19+ (musl needs `bash curl libgcc libstdc++ ripgrep` and `USE_BUILTIN_RIPGREP=0`); apt/dnf/apk repos [^cc-setup] | Windows 10 1809+ / Server 2019+, native or WSL [^cc-setup] |
| Bash tool shell | `CLAUDE_CODE_SHELL` (bash or zsh only), else `$SHELL` if it's bash or zsh, else first zsh then bash on `PATH` [^cc-env] | Git Bash when Git for Windows is installed (`CLAUDE_CODE_GIT_BASH_PATH` overrides); without it, PowerShell tool only [^cc-setup] |
| PowerShell tool | opt-in, `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`, needs `pwsh` 7+ [^cc-tools] | on by default for claude.ai/Console accounts even with Git Bash; "Claude treats PowerShell as the primary shell" when enabled [^cc-tools] |
| Monitor tool | available | only when Git Bash is installed [^cc-tools] |
| Sandbox | bubblewrap + socat; Ubuntu 24.04+ AppArmor needs a `bwrap` profile [^cc-sandbox] | none native; WSL2 only (WSL1 none) [^cc-sandbox][^cc-setup] |
| Credentials | `~/.claude/.credentials.json`, mode 0600 [^cc-auth] | `%USERPROFILE%\.claude\.credentials.json` [^cc-auth] |

**Background sessions** (`claude --bg`, `claude agents [--json --all]`, `attach`, `logs`, `stop`): run under a per-config-dir supervisor ("background service") that Claude Code starts on demand, with state in `~/.claude/daemon.log`, `~/.claude/daemon/roster.json`, `~/.claude/jobs/<id>/` [^cc-agentview]. The agent-view page has Windows- and Linux-specific behaviour and fixes in its changelog (Windows `daemon.lock` recovery v2.1.257, `taskkill` for a stuck supervisor, Linux/WSL dead-terminal-host handling v2.1.247, Windows background-work handoff v2.1.195/196), so the feature works on both [^cc-agentview]. Platform differences:

- If the supervisor dies, "on macOS and Linux" sessions wait about a minute for a new one and then stop. The doc doesn't say what happens on Windows [^cc-agentview].
- The page names no service manager (systemd, launchd or a Windows service). The supervisor doesn't survive a reboot: "Shutting down or restarting your machine stops running background sessions" [^cc-agentview].
- The docs don't say whether `--bg` needs a TTY or display on a headless Linux box. **Unverified.**

**Transcripts:** `~/.claude/projects/<project>/<session-id>.jsonl`, where `<project>` is the cwd with every non-alphanumeric character replaced by `-` (truncated and hashed past 200 chars) [^cc-sessions]. On Windows the drive letter and backslashes are encoded the same way, so `transcript_of`'s glob `projects/*/<id>*.jsonl` still matches. `CLAUDE_CONFIG_DIR` moves all of it [^cc-env].

### Codex CLI

| | Linux | Windows |
| --- | --- | --- |
| Supported | standalone installer "for macOS and Linux", npm, Homebrew [^cx-cli] | standalone PowerShell installer (`install.ps1`), npm; native sandbox or WSL2 [^cx-cli][^cx-winsandbox] |
| Shell | the user's login shell from the passwd entry (`getpwuid_r`), if zsh/bash/sh/pwsh; else bash, then zsh; else `/bin/sh` [^cx-src] | PowerShell: `pwsh`, then `powershell.exe` (skipping Store-installed copies the sandbox can't use); else `cmd.exe`. Never Git Bash [^cx-src] |
| Sandbox | bubblewrap: first `bwrap` on `PATH`, else a bundled helper that needs unprivileged user namespaces; Ubuntu 25.04 AppArmor needs an extra profile [^cx-sandbox] | MXC (Windows 11 24H2/25H2 builds), else `elevated` (admin-approved setup, sandbox users and firewall rules), else `unelevated` (restricted token, weaker network isolation) [^cx-winsandbox] |
| WSL | WSL2 runs the Linux sandbox; **WSL1 unsupported from 0.115** (sandbox moved to bubblewrap) [^cx-wsl] | |
| Windows 10 | | "Best effort", needs 1809+ for ConPTY [^cx-winsandbox] |

**Headless:** `codex exec` (with `--json`, `-o/--output-last-message` and `exec resume <SESSION_ID>`) is documented without platform caveats [^cx-exec].

**Config and sessions:** `CODEX_HOME`, default `~/.codex`, holds "config, auth, logs, sessions, skills" (it must already exist if you set it) [^cx-envvars]. On Windows that's `%USERPROFILE%\.codex`. A CLI inside WSL uses the Linux home, so its config and sessions aren't shared with Windows-side Codex [^cx-winapp]. The visible binary goes to `~/.local/bin`, or `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin` on Windows [^cx-envvars].

### Copilot CLI

| | Linux | Windows |
| --- | --- | --- |
| Supported | "Linux"; Homebrew, install script, npm (Node 22+) [^cp-about][^cp-install] | "Windows from within Powershell and Windows Subsystem for Linux (WSL)"; WinGet `GitHub.Copilot`, npm; needs PowerShell v6+ [^cp-about][^cp-install] |
| Shell tool | `bash` (with `read_bash`, `write_bash`, …) | `powershell` (with `read_powershell`, …); prefers `pwsh` 7+, falls back to `powershell.exe`, flags `powershellFlags` (default `-NoProfile -NoLogo`) [^cp-cmdref][^cp-config] |
| Permission kinds | `shell(...)` | `PowerShell(...)`, "matched the same way as `Shell(...)`" [^cp-config] |
| OS sandbox | MXC → Bubblewrap [^cp-config] | MXC → ProcessContainer; network host rules rely on programs honouring the proxy [^cp-config] |

**Headless:** `-p`, `--session-id` (resumes the session if the ID exists, and creates one if it's a new UUID), `--no-ask-user`, `--allow-tool` / `--deny-tool` and `--available-tools` are all documented in one command reference with no platform split [^cp-cmdref]. `copilot login` falls back to a device-code flow on remote terminals and in CI [^cp-cmdref].

**Config and sessions:** `COPILOT_HOME`, default `~/.copilot` (on Windows typically `C:\Users\<user>\.copilot\`), holds config, `session-state/<session-id>/events.jsonl`, `logs/` and `skills/`. The cache ignores `COPILOT_HOME`: it's `$XDG_CACHE_HOME/copilot` or `~/.cache/copilot` on Linux and `%LOCALAPPDATA%/copilot` on Windows [^cp-config]. The `pkg/<platform>/<version>/` tree our `skills.zsh` reads isn't documented.

## What breaks the agent-teammates drivers

### On Linux (and WSL2)

The harness features hold. The breakage is ours:

1. **BSD `stat -f %m`** in `watch-teammates.sh`, `verify-report.sh`, and `status` and `tail` in all three drivers (already listed in #92). GNU `stat -f` means "filesystem status" and takes no argument, so on Linux `%m` is read as a file name: the call errors and prints filesystem data in place of an mtime. zsh's `zstat` module or a `date -r`/`find -printf` fallback avoids `stat` entirely.
2. **`#!/bin/zsh`** needs zsh installed. Agents' Bash tools also run bash or zsh only (Claude picks `$SHELL`, else zsh then bash; Codex uses the login shell, else bash first on Linux), so bash is the floor every harness guarantees on Linux.
3. **Codex sandbox prerequisites.** Every Codex teammate runs `-s read-only` or `-s workspace-write`, so on Linux and WSL2 the run needs `bwrap` on `PATH`, or user namespaces for the bundled helper. On Ubuntu 25.04 it also needs the extra AppArmor profile [^cx-sandbox]. A preflight check belongs in `drivers/codex/preflight`. The Claude driver doesn't turn on Claude's sandbox, so bubblewrap/socat matter only if the engineer has.
4. **Viewer.** cmux is a macOS app. `VIEWER=tmux` already works anywhere tmux does.
5. **Fine as written:** `python3 os.setsid` and `perl setpgrp` (Linux also has `setsid(1)`), `ps -o args=,pgid=` and `ps -A -o pid=,ppid=,pgid=` (procps accepts them), `kill -- -pgid`, `/bin/sleep`, `uuidgen` with its `/proc/sys/kernel/random/uuid` fallback, `jq`, and `lsof -a -p <pid> -d cwd` (Codex reference) if lsof is installed.
6. **Unverified:** `claude --bg` on a headless box (no TTY, no display) and over SSH. Run it in CI before claiming headless support.

### On native Windows

1. **No POSIX shell for the agent by default.** Claude reaches the scripts only through Git Bash, which has no zsh, and Claude prefers the PowerShell tool when it's on. Codex and Copilot run PowerShell, and never Git Bash, so they can't run `.sh` files.
2. **Process control.** Codex and Copilot `launch`/`stop`/`status` depend on `setsid`/`setpgrp`, process groups, `ps -o pgid=` and `kill -- -pgid`. Windows has none of these natively (#93 already lists this).
3. **Copilot read-only flags.** `--available-tools bash view glob grep` names a tool that doesn't exist on Windows (`powershell` does), so a read-only teammate would get no shell. And `shell(git log)` allows don't obviously cover the `PowerShell(...)` permission kind. **Unverified** whether `shell(...)` matches PowerShell commands.
4. **Claude watchdog.** The Monitor tool, which runs `watch-teammates.sh` on Claude, exists on Windows only when Git Bash is installed [^cc-tools].
5. **Claude Bash deny rules turn off PowerShell.** On Windows with Git Bash, any `Bash(...)` deny rule (including `--disallowedTools`) silently turns the PowerShell tool off unless it's explicitly enabled [^cc-tools]. That matters if the Claude driver ever adds Bash denies.
6. **Paths.** Config roots become `%USERPROFILE%\.claude`, `%USERPROFILE%\.codex` and `C:\Users\<user>\.copilot`. Copilot compares `allowed_directories` case-insensitively on Windows [^cp-config].

### Through WSL2 (the cheapest Windows route)

Install each harness *inside* the distro. All three document this. Codex and Claude Code each get their Linux sandbox there, and Codex keeps a separate `CODEX_HOME` from Windows-side Codex. Keep repos under the Linux home, not `/mnt/c`, for speed and fewer permission problems [^cx-wsl]. Everything in the Linux list then applies unchanged. WSL1 doesn't work: Codex dropped it at 0.115, and Claude Code runs on WSL1 without a sandbox [^cx-wsl][^cc-setup].

## Side finding

Copilot CLI now has an OS sandbox ([MXC](https://github.com/microsoft/mxc): Seatbelt, Bubblewrap, ProcessContainer), with a `--sandbox` flag "useful with `-p`" [^cp-cmdref][^cp-config]. That bears on [#49](https://github.com/jbuffin/skills/issues/49) (Copilot's OS sandbox) and [#81](https://github.com/jbuffin/skills/issues/81).

## Sources

[^cc-setup]: Claude Code, Advanced setup: <https://code.claude.com/docs/en/setup>
[^cc-env]: Claude Code, Environment variables (`CLAUDE_CODE_SHELL`, `CLAUDE_CODE_GIT_BASH_PATH`, `CLAUDE_CONFIG_DIR`): <https://code.claude.com/docs/en/env-vars>
[^cc-tools]: Claude Code, Tools reference (Bash, PowerShell, Monitor): <https://code.claude.com/docs/en/tools-reference>
[^cc-sandbox]: Claude Code, Configure the sandboxed Bash tool: <https://code.claude.com/docs/en/sandboxing>
[^cc-auth]: Claude Code, Authentication, credential management: <https://code.claude.com/docs/en/authentication>
[^cc-agentview]: Claude Code, Manage multiple agents with agent view (supervisor, `claude agents --json`, version history): <https://code.claude.com/docs/en/agent-view>
[^cc-sessions]: Claude Code, Sessions, where transcripts are stored: <https://code.claude.com/docs/en/sessions>
[^cx-cli]: Codex CLI: <https://learn.chatgpt.com/docs/codex/cli>
[^cx-src]: openai/codex `codex-rs/shell-command/src/shell_detect.rs` (`default_user_shell_from_path`, `ultimate_fallback_shell`): <https://github.com/openai/codex/blob/main/codex-rs/shell-command/src/shell_detect.rs>
[^cx-sandbox]: Codex, Sandbox: <https://learn.chatgpt.com/docs/sandboxing>
[^cx-winsandbox]: Codex, Windows sandbox: <https://learn.chatgpt.com/docs/windows/windows-sandbox>
[^cx-wsl]: Codex, WSL: <https://learn.chatgpt.com/docs/windows/wsl>
[^cx-winapp]: ChatGPT desktop app for Windows: <https://learn.chatgpt.com/docs/windows/windows-app>
[^cx-exec]: Codex, Non-interactive mode: <https://learn.chatgpt.com/docs/non-interactive-mode>
[^cx-envvars]: Codex, Environment variables (`CODEX_HOME`, `CODEX_INSTALL_DIR`): <https://learn.chatgpt.com/docs/config-file/environment-variables>
[^cp-about]: About GitHub Copilot CLI, supported operating systems: <https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli>
[^cp-install]: Installing GitHub Copilot CLI: <https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli>
[^cp-cmdref]: GitHub Copilot CLI command reference (tool names, permission patterns, flags): <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference>
[^cp-config]: GitHub Copilot CLI configuration directory (`COPILOT_HOME`, `session-state/`, `powershellFlags`, sandbox, `PowerShell(...)`): <https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference>
