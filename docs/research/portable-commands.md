# Portable replacements for the macOS-only commands in the team skills

Research for [#96](https://github.com/jbuffin/skills/issues/96) under the map
[#92 Linux support](https://github.com/jbuffin/skills/issues/92). Throwaway branch; never merged.
Inventory taken at `origin/main` 949173f.

## Answer

Most constructs already have a form that works on macOS (BSD) and GNU. Busybox is the hard target. The fixes:

- **mtime:** use zsh's `zstat +mtime` while the scripts stay zsh. If they move off zsh, use a
  `stat -c %Y || stat -f %m` fallback.
- **Process groups:** `perl setpgrp` and `python3 os.setsid` already work on Linux. POSIX `set -m` then `cmd &` gives
  the same new process group with no interpreter.
- **`ps`:** `ps -o pgid= -p PID` works on BSD and procps but not busybox, which has no `-p`. Read `ps -A -o pid=,pgid=`
  and filter it, or read `/proc`.
- **`date`, `mktemp`, `sed -i.bak`:** the shipped scripts already use portable forms. The `date -r` vs `date -d @`
  fallback is confined to the tests.
- **cmux:** macOS only, so Linux falls back to tmux or `VIEWER=none`.
- **Hard-coded `/bin/...` paths:** these break on NixOS.

## Inventory and portable equivalents

Each row lists the call sites, what breaks, and the portable form. "BSD" means macOS. "GNU" means coreutils, procps-ng
and util-linux. "bb" means busybox (the Alpine default).

### 1. File mtime: `stat -f %m`

Sites: `agent-teammates/scripts/watch-teammates.sh:47,63`, `verify-report.sh:19`, and `drivers/{claude,codex,copilot}/{status,tail}`.
The tests paper over it with the shim `tests/bin/stat`, which maps the call to `stat -c %Y`.

- BSD `stat -f format` takes a format string, and `%m` is the mtime as epoch seconds (macOS `stat(1)`, which has the
  example `stat -f %m /tmp/foo`).
- In GNU `stat`, `-f` means `--file-system`: "display file system status instead of file status". The mtime format
  is `-c %Y`, "time of last data modification, seconds since Epoch" ([stat(1)](https://man7.org/linux/man-pages/man1/stat.1.html)).
  On GNU, `stat -f %m f` therefore misparses or fails.
- bb `stat` supports `-c fmt` with `%Y` ([BusyBox.html](https://busybox.net/downloads/BusyBox.html)).

Portable forms:

- **zsh (no external command):** `zmodload zsh/stat; zstat +mtime "$f"` prints the mtime as epoch seconds. Use
  `zstat -A var +mtime "$f"` to assign it ([zsh modules, zsh/stat](https://zsh.sourceforge.io/Doc/Release/Zsh-Modules.html)).
  This is the same on every platform that has zsh, and it lets `tests/bin/stat` be deleted.
- **sh/bash:** `mtime() { stat -c %Y -- "$1" 2>/dev/null || stat -f %m -- "$1"; }`. Try GNU/bb first, because BSD
  `stat -c` is an error (BSD has no `-c`). Trying `-f %m` first on GNU prints filesystem info instead of failing
  cleanly.
- **Alternative:** `date -r FILE +%s` reads a file's mtime on GNU, bb and BSD alike. GNU and bb document `-r FILE`.
  BSD `-r` accepts either seconds or a filename, so a numeric-looking filename is ambiguous there (macOS `date(1)`).
  Usable, but `zstat`/`stat` is clearer.

### 2. New process group / session (`setsid` avoidance)

Sites: `drivers/codex/lib.zsh:45` (`python3 -c 'os.setsid(); os.execvp(...)'`), `drivers/copilot/lib.zsh:86` and
`drivers/copilot/preflight:14` (`perl -e 'setpgrp(0,0); exec ...'`), and the fakes in `tests/bin/codex:104` and `tests/run.sh:2178`.

- `setsid(1)` is part of **util-linux** ([setsid(1)](https://man7.org/linux/man-pages/man1/setsid.1.html)), so it is
  missing on macOS. bb ships a `setsid` applet. It forks only if the caller is already a group leader; use `-f`
  to always fork.
- The existing python3/perl one-liners call the POSIX `setsid()`/`setpgid()` syscalls. They already work on
  Linux unchanged, provided python3/perl exist. Debian/Ubuntu ship `perl-base` as essential. Alpine and minimal
  containers have neither by default.
- No interpreter, POSIX: with job control on (`set -m`), an asynchronous list's PID is "a child process that is made a
  process group leader", and the other processes it creates take that PID as their process group ID
  ([POSIX Shell §2.11 Job Control, `set -m`](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html)).
  So `set -m; cmd & pg=$!; set +m` gives pgid == `$!` in bash, zsh (`setopt monitor`) and dash. This matches perl's
  `setpgrp(0,0)`, a new group in the same session. It does not match `setsid`, which also drops the controlling
  terminal. Keep python's `os.setsid()` where escaping the terminal's SIGHUP matters (Codex).
- Signalling the group, `kill -TERM -- -$pg`, is POSIX and works everywhere.

Recommendation: keep the perl/python one-liners, or switch to `set -m` and drop the interpreter dependency. Don't
adopt `setsid(1)`, because it reintroduces the macOS gap.

### 3. `ps` flags

Sites: `drivers/codex/lib.zsh:19` (`ps -ww -o args= -p PID`), `:20` and `drivers/copilot/lib.zsh:13`
(`ps -o pgid= -p PID`), `drivers/codex/lib.zsh:56` (`ps -A -o pid=,ppid=,pgid=`), `drivers/codex/launch:36`, and `tests/bin/codex:74`.

- **POSIX** specifies `-A`, `-p proclist` and `-o` with `name=` (an empty header), and lists `pgid` and `args` as
  format names. It says nothing about `-ww` beyond advising against more than one `-w`
  ([POSIX ps](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/ps.html)).
- **BSD** has `-A`, `-p`, `pgid`, and `-w` twice for unlimited width (macOS `ps(1)`). **procps-ng** also has `-A`
  (= `-e`), `-p` and `-o x=`, and "-w twice for unlimited width"
  ([ps(1)](https://man7.org/linux/man-pages/man1/ps.1.html)). Every current form works on macOS and glibc Linux.
- **bb `ps`** (DESKTOP build): getopt is `"Zo:*aAdefl[T]"`. It accepts `-o` (fields include `pid ppid pgid args`)
  and accepts but ignores `-A/-e`. It has **no `-p` and no `-w`**, and the non-DESKTOP build has no `-o` at all
  ([busybox procps/ps.c](https://raw.githubusercontent.com/mirror/busybox/master/procps/ps.c)).

Portable forms:

- Per-PID lookups: `ps -A -o pid=,pgid= | awk -v p=$PID '$1==p{print $2}'`. This works on BSD, procps and bb DESKTOP.
- For `args`: `ps -A -o pid=,args= | awk -v p=$PID '$1==p{sub(/^ *[0-9]+ +/,""); print}'`. bb's `args` is
  not truncated to a terminal width. procps and BSD don't truncate when output isn't a terminal (macOS `ps(1)`:
  "When output is not to a terminal, an unlimited number of columns are always used"). Keep `-ww` only on the BSD/GNU path.
- Linux-only, no `ps` at all: `/proc/$PID/stat` (field 5 is pgrp) and `/proc/$PID/cmdline`. This is the fallback if
  bb support matters and the busybox build lacks DESKTOP.
- `kill -0 PID` (liveness) is POSIX and fine everywhere.

### 4. `mktemp`

Sites: `copilot/preflight:26-45` (`mktemp`, `mktemp -d`), `commodore/scripts/team-preflight.sh:65`, `watch-ci.sh:10`,
`setup-commodore/scripts/roles-draft.sh:48`, and `tests/run.sh:42` (`mktemp -d ${TMPDIR:-/tmp}/name.XXXXXX`).

POSIX Issue 8 has no `mktemp` utility page (404 at the expected URL). GNU: "no template: use tmp.XXXXXXXXXX, and
--tmpdir is implied" ([mktemp(1)](https://man7.org/linux/man-pages/man1/mktemp.1.html)). macOS: "If no arguments
are passed or if only the -d flag is passed mktemp behaves as if -t tmp was supplied" (macOS `mktemp(1)`). bb supports
`-d`, `-t` and `-p`, and the template must end in `XXXXXX`. **Already portable.** For the widest reach, prefer the explicit
`mktemp [-d] "${TMPDIR:-/tmp}/name.XXXXXX"` form the newer scripts use. It avoids the `-t` meaning differing between
GNU (template) and BSD (prefix).

### 5. `date`

Sites: `date -u +%s` (team-env, watch-teammates, launch-teammate, copilot lib), `date +%s` (driver tails),
`date -u +%FT%TZ` (evidence.sh). Tests only: `date -u -r EPOCH ... || date -u -d @EPOCH ...` (`tests/run.sh:123`,
`tests/bin/copilot:62-63`).

- Issue 8 POSIX `date` formats "as if by strftime()", and POSIX `strftime` defines `%s` (CX), `%F` and `%T`
  ([date](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/date.html),
  [strftime](https://pubs.opengroup.org/onlinepubs/9799919799/functions/strftime.html)). **The shipped scripts are portable.**
  bb passes the format straight to libc `strftime`, so `%s` depends on libc (glibc and musl both have it).
- Converting an epoch to a date isn't POSIX. GNU uses `-d @N` ([date(1)](https://man7.org/linux/man-pages/man1/date.1.html)),
  BSD uses `-r N`, and bb lists `@seconds_since_1970` under `-d`
  ([busybox date.c](https://raw.githubusercontent.com/mirror/busybox/master/coreutils/date.c)). The tests' `-r || -d @`
  fallback is the right pattern. Alternatives: zsh `strftime` from `zsh/datetime`, or `$EPOCHSECONDS` in place of
  `date +%s`, which drops a fork.

### 6. `sed -i`

Sites: tests only (`tests/run.sh:1111,1351,2350,2616`), all `sed -i.bak ...`. BSD takes `-i extension`, which can be
attached. GNU takes `-i[SUFFIX]`, which must be attached because it is an optional argument
([sed(1)](https://man7.org/linux/man-pages/man1/sed.1.html)). bb supports `-i`. **`-i.bak` attached is the portable
spelling, and the repo already uses it.** Never write `sed -i ''` (BSD-only) or a bare `sed -i` (GNU-only).

### 7. cmux viewer and its `/Applications` path

Sites: `agent-teammates/scripts/team-env.zsh:20`, `commodore/scripts/team-init.sh:47`
(`${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}`), `drivers/claude/launch:30-32`,
`close-teammate.sh:15`, and `team-preflight.sh:35`.

cmux is "a Ghostty-based macOS terminal". Its FAQ answers "What platforms does it support?" with "**macOS only, for
now.** cmux is a native Swift + AppKit app" ([manaflow-ai/cmux README](https://github.com/manaflow-ai/cmux)).
Distribution is a `.dmg` and a Homebrew cask. **There is no Linux cmux.** On Linux, `VIEWER=cmux` should be refused or
downgraded at preflight, the way `VIEWER=tmux` outside tmux already warns. The `/Applications` default is harmless
there because `-x $CMUX` fails, but `command -v cmux` is a better second fallback on macOS too.

tmux (`split-window -d -h -P -F '#{pane_id}'`, `kill-pane -t`) is the same on macOS and Linux, so it is the Linux
viewer. Headless Linux uses `VIEWER=none`.

### 8. Locking: `zsystem flock`

Site: `agent-teammates/scripts/evidence.sh:27-30`. zsh's `zsystem flock [-t timeout] file` uses fcntl(2) advisory
locks, and `zsystem supports flock` reports availability
([zsh modules, zsh/system](https://zsh.sourceforge.io/Doc/Release/Zsh-Modules.html)). It is portable wherever zsh is.
If the scripts leave zsh: util-linux `flock(1)` (`-n`, `-w secs`) is Linux-only and missing on macOS
([flock(1)](https://man7.org/linux/man-pages/man1/flock.1.html)), and bb `flock` has `-sxun` but no `-w`
([busybox flock.c](https://raw.githubusercontent.com/mirror/busybox/master/util-linux/flock.c)). The portable shell
fallback is an atomic `mkdir "$K.d"` lock with a retry loop.

### 9. Fractional `sleep` and hard-coded `/bin/...` paths

Sites: `/bin/sleep 0.1|0.2|0.3|0.5` (copilot lib/stop/send/preflight, codex lib/launch), `#!/bin/zsh` on every script,
`/bin/zsh -f` (`copilot/lib.zsh:86`), `/bin/date` (tests), and `/usr/bin/stat` (stat shim).

- POSIX `sleep` takes "a non-negative decimal integer"
  ([sleep](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/sleep.html)). GNU accepts "an integer or
  floating-point" ([sleep(1)](https://man7.org/linux/man-pages/man1/sleep.1.html)), as does macOS. bb accepts fractions
  only with `FEATURE_FANCY_SLEEP` (default y). Fractions are fine on the target platforms. zsh's own wait
  (`zselect -t 50`, or `read -t 0.5` against a never-written fd) avoids the fork.
- `/bin/sleep`, `/bin/zsh` and `/bin/date` exist on macOS, Debian/Ubuntu (merged `/usr`) and Alpine. They do **not**
  exist on NixOS, and zsh on Debian is `/usr/bin/zsh` with a `/bin` alias only through merged-usr. Prefer
  `#!/usr/bin/env zsh` (the CI linter already accepts it), bare `sleep`, and `$ZSH_ARGZERO`/`$SHELL` over `/bin/zsh`.

### 10. Other things checked

- `sort -V` (`team-preflight.sh:43`, `unit-worktree.sh:58`) works on GNU and macOS `sort` but is absent from bb `sort`.
  The portable form is a field-wise numeric compare in awk.
- `grep -o` is in GNU, BSD and bb, though not POSIX. Keep it.
- `touch -t` (tests `settime`) is POSIX. Old bb docs list only `touch -d`, so it matters only for tests on Alpine.
- `&!` (background and disown) is zsh-only. The bash form is `cmd & disown`.
- `security` (Keychain) in run-preflight and `team-init.sh:167` `REQUIRED_TOOLS` is macOS-only. It is out of scope
  here and belongs to the map's secrets work. Note that `team-init` lists `security` as *required*, so it will fail
  on Linux.

## Bearing on Windows ([#93](https://github.com/jbuffin/skills/issues/93))

- Native Windows has no POSIX process groups or signals. `set -m`, `setpgrp`, `os.setsid`, `kill -- -pgid` and
  `ps -o pgid=` have no Win32 equivalent (MSYS2/Cygwin emulate them only inside their own process tree). The
  stop/liveness logic in the codex and copilot drivers needs a different mechanism there, such as Job Objects or
  `taskkill /T`.
- cmux is macOS-only, and tmux runs only under WSL/MSYS2/Cygwin, so Windows needs `VIEWER=none` or a WSL path.
- The zsh-only answers above (`zstat`, `zsystem flock`) don't help Git Bash, which has no zsh. The sh fallbacks
  (`stat -c %Y`, `date -r`, mkdir-lock) do work under Git Bash's GNU coreutils.
- `/bin/...` hard-coded paths and `/Applications` don't exist on native Windows.

## Sources

- POSIX.1-2024 (Issue 8): [ps](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/ps.html),
  [date](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/date.html),
  [strftime](https://pubs.opengroup.org/onlinepubs/9799919799/functions/strftime.html),
  [sleep](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/sleep.html),
  [Shell Command Language (set -m, §2.11)](https://pubs.opengroup.org/onlinepubs/9799919799/utilities/V3_chap02.html)
- Linux man-pages (GNU coreutils / procps-ng / util-linux): [stat](https://man7.org/linux/man-pages/man1/stat.1.html),
  [date](https://man7.org/linux/man-pages/man1/date.1.html), [mktemp](https://man7.org/linux/man-pages/man1/mktemp.1.html),
  [sed](https://man7.org/linux/man-pages/man1/sed.1.html), [sleep](https://man7.org/linux/man-pages/man1/sleep.1.html),
  [ps](https://man7.org/linux/man-pages/man1/ps.1.html), [setsid](https://man7.org/linux/man-pages/man1/setsid.1.html),
  [flock](https://man7.org/linux/man-pages/man1/flock.1.html)
- BusyBox: [BusyBox.html](https://busybox.net/downloads/BusyBox.html), source
  [procps/ps.c](https://raw.githubusercontent.com/mirror/busybox/master/procps/ps.c),
  [coreutils/date.c](https://raw.githubusercontent.com/mirror/busybox/master/coreutils/date.c),
  [coreutils/sleep.c](https://raw.githubusercontent.com/mirror/busybox/master/coreutils/sleep.c),
  [util-linux/flock.c](https://raw.githubusercontent.com/mirror/busybox/master/util-linux/flock.c)
- macOS 27 man pages read locally: `stat(1)`, `date(1)`, `mktemp(1)`, `sed(1)`, `ps(1)`
- [zsh manual, Zsh Modules (zsh/stat, zsh/system)](https://zsh.sourceforge.io/Doc/Release/Zsh-Modules.html)
- [manaflow-ai/cmux README](https://github.com/manaflow-ai/cmux) (FAQ "What platforms does it support?")
