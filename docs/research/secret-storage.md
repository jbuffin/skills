# Secret storage for unattended agent runs, per platform

Research for [#95](https://github.com/jbuffin/skills/issues/95), under the Linux map
[#92](https://github.com/jbuffin/skills/issues/92); Windows findings also feed
[#93](https://github.com/jbuffin/skills/issues/93). Throwaway branch, never merged.

**Question.** What's the best secret store an unattended agent run can read on macOS, Linux desktop,
headless Linux and Windows? How do gh, git-credential-manager (GCM), Python `keyring` and
99designs/keyring detect and pick a backend, and could one cross-platform tool cover several platforms?
Constraint: existing macOS Keychain items (`agent-team/<project>/...`) keep working unchanged.

Today `skills/engineering/run-preflight/scripts/secret-run.sh` runs
`security find-generic-password -s <service> -w` (lookup by **service only**) and exports the value
into one env var before `exec`. `preflight.sh` checks presence with `security find-generic-password -s`.

## Answer

1. **No single tool covers every platform for this use, so don't build on one.** Do what gh, GCM and
   both keyring libraries do: keep one small helper interface (`secret-run.sh <service> <VAR> -- cmd`,
   plus a "present?" check for preflight) and dispatch to a per-platform backend in a fixed priority
   order, with an explicit override (env var) like `GCM_CREDENTIAL_STORE` / `PYTHON_KEYRING_BACKEND` /
   99designs' `AllowedBackends`.
2. **macOS: keep `security` unchanged.** It's what go-keyring (and so gh) uses, existing items keep
   working, and the ACL "Always Allow" the probe already triggers is tied to `/usr/bin/security`.
3. **Linux desktop: Secret Service via `secret-tool`** (libsecret), when a D-Bus session bus is
   reachable and the default collection is unlocked.
4. **Headless Linux: there's no settled single answer; every established tool either needs a GUI
   prompt, a daemon unlocked by hand, or a key on disk.** For the run-preflight shape (engineer present at
   preflight, then away for hours on the same box), the best fits, in order:
   - **Kernel user keyring (`keyctl`, `@u`)**: in memory only, no daemon, no prompt, lives as long as
     the user has processes (the run itself keeps it alive), gone at reboot. Use the persistent keyring
     if the run must survive logout. 99designs/keyring ships it as a backend.
   - **`systemd-creds --user`** (systemd ≥ 256): encrypted at rest, bound to the host key/TPM2 and the
     UID, decrypts without a prompt, survives reboot. Not on systemd 255 or older.
   - **Secret Service on a headless box** only if the engineer already runs one: start
     `gnome-keyring-daemon --unlock` inside a D-Bus session and run the agents in that same session
     (Python keyring's documented recipe). Fragile across SSH sessions.
   - **`pass`** only with care: gpg-agent's default `max-cache-ttl` is 2 h, so an overnight run loses
     the passphrase unless the agent is configured otherwise or the key has no passphrase.
   - A password-manager CLI (1Password `op` with a service-account token) when the engineer already
     uses one; the token then needs one of the stores above.
5. **Windows: Credential Manager (`CRED_TYPE_GENERIC`) is the native store and the default for GCM,
   go-keyring, Python keyring and 99designs**, but **it doesn't exist in network logon sessions**, which
   is what an SSH key login is. Over SSH, GCM's answer is DPAPI-protected files. Under WSL, the Linux
   rules apply (WSL can't reach Credential Manager except by calling a Windows `.exe`, as GCM does).
6. **Python `keyring` is the closest thing to one cross-platform CLI** (macOS Keychain, Secret
   Service, KWallet, Windows Credential Manager), and it can read existing Keychain items, but it
   needs the account name as well as the service, triggers a fresh Keychain ACL prompt for the Python
   binary, adds a Python dependency, and has no headless-Linux backend in core. Not worth it over
   calling `security` / `secret-tool` / `keyctl` directly. 99designs/keyring is a Go library with no
   CLI and no pushes since May 2024.

## How the established tools pick a backend

| Tool | macOS | Linux | Windows | Headless/fallback | Selection |
| --- | --- | --- | --- | --- | --- |
| gh | go-keyring → `/usr/bin/security` | go-keyring → Secret Service (D-Bus) | go-keyring → Credential Manager | falls back to a plaintext file when the store "is not found or fails"; `--insecure-storage`; `GH_TOKEN` env for automation | try store, 60 s timeout per call, fall back |
| GCM | `keychain` (default) | **no default**; `secretservice`, `gpg` (pass), `cache`, `plaintext` | `wincredman` (default), `dpapi` | `cache` (in-memory, 900 s) for ephemeral envs; `dpapi` over SSH | `GCM_CREDENTIAL_STORE` / `credential.credentialStore` |
| Python keyring | Keychain (SecItemCopyMatching) | Secret Service, KWallet | WinVault (CredRead, generic) | none in core; `keyrings.alt`, `keyrings.cryptfile` opt-in | `PYTHON_KEYRING_BACKEND` → `keyringrc.cfg` → highest `priority` among viable backends |
| 99designs/keyring | keychain | secret-service, kwallet, keyctl | wincred | pass, file (encrypted, password) | first that opens, in `backendOrder` or caller's `AllowedBackends` |

Sources:
- gh's keyring wrapper imports `github.com/zalando/go-keyring` and wraps each call in a 60 s timeout
  ([cli/cli `internal/keyring/keyring.go`](https://github.com/cli/cli/blob/trunk/internal/keyring/keyring.go)).
  Fallback and `--insecure-storage`: "If a credential store is not found or there is an issue using it
  gh will fallback to writing the token to a plain text file"; `GH_TOKEN` is "most suitable for
  'headless' use of gh such as in automation" ([gh auth login](https://cli.github.com/manual/gh_auth_login)).
- go-keyring: macOS "depends on the `/usr/bin/security` binary"; Linux/BSD "depends on the Secret
  Service dbus interface, which is provided by GNOME Keyring" and expects a `login` collection; Windows
  uses Credential Manager with target `service:username`
  ([zalando/go-keyring README](https://github.com/zalando/go-keyring)).
- GCM stores, defaults and notes, including "Linux has no default"; Secret Service: "A graphical user
  interface is required in order to show a secure prompt to request a secret collection be unlocked";
  gpg/pass needs `GPG_TTY` and a TTY pinentry headless; `cache` is in-memory (default 900 s) "for
  ephemeral environments"; Windows Credential Manager can't persist over SSH/network sessions, DPAPI is
  the alternative ([GCM docs/credstores.md](https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/credstores.md)).
- Python keyring selection is `load_env() or load_config() or max(viable backends, key=priority)`
  ([jaraco/keyring `keyring/core.py`](https://github.com/jaraco/keyring/blob/main/keyring/core.py));
  backends per OS, `keyringrc.cfg`, headless recipe, third-party backends
  ([README](https://github.com/jaraco/keyring/blob/main/README.rst)).
- 99designs/keyring `backendOrder` = wincred, keychain, secret-service, kwallet, keyctl, pass, file;
  `Open` returns the first allowed backend that opens, else `ErrNoAvailImpl`
  ([`keyring.go`](https://github.com/99designs/keyring/blob/master/keyring.go)). Repo last pushed
  2024-05-07 (`gh api repos/99designs/keyring`, checked 2026-10-14).

## Per platform

### macOS: Keychain (keep as is)

- `security find-generic-password -s <svc> -w` is the same mechanism gh uses through go-keyring. No
  change needed; the constraint is met by leaving the macOS branch of the helper exactly as it is.
- Switching readers would cost a prompt: the Keychain item's ACL trusts the app that created it, so a
  new reader (Python's `keyring`, a Go binary) gets a fresh "allow access" dialog. Python keyring's
  README says the inverse for its own items: "Any Python script or application can access secrets
  created by keyring from that same Python executable without the user having to enter their password."
- Python keyring looks items up by **service and account** (`kSecAttrService` + `kSecAttrAccount`,
  [`macOS/api.py` `find_generic_password`](https://github.com/jaraco/keyring/blob/main/keyring/backends/macOS/api.py)).
  `secret-run.sh` looks up by service only, so adopting keyring would also require knowing each item's
  account name.

### Linux desktop: Secret Service (`secret-tool`)

- `secret-tool store --label=L {attr} {value}…` reads the secret from stdin; `secret-tool lookup
  {attr} {value}…` prints it to stdout ([secret-tool(1)](https://manpages.debian.org/testing/libsecret-tools/secret-tool.1.en.html)).
  A helper would use attributes like `service agent-team/<project>/stage-test-pass`, mirroring the
  Keychain service name, and capture `lookup` output into the env var exactly as `security -w` is used.
- Provided by GNOME Keyring or KWallet over the D-Bus session bus (go-keyring README; Python keyring
  README). Needs the collection unlocked; unlocking prompts through a GUI (GCM credstores.md).
- Detection: `command -v secret-tool`, a session bus (`DBUS_SESSION_BUS_ADDRESS` set), and a cheap
  `secret-tool lookup` of a sentinel attribute that exits without hanging. gh wraps calls in a 60 s
  timeout because a locked collection can block on a prompt; the helper should time out too.

### Headless Linux

No D-Bus session keyring by default, and Secret Service's unlock needs a GUI prompt. Options:

**Kernel keyring (`keyctl`, keyutils)**
- `keyctl padd user <desc> @u` reads the value from stdin; `keyctl pipe <id>` writes the raw payload
  to stdout; `keyctl request user <desc>` / `keyctl search @u user <desc>` find the id
  ([keyctl(1)](https://man7.org/linux/man-pages/man1/keyctl.1.html)).
- `@u` is "shared by all processes with that UID"; it lives while processes with that UID exist and is
  destroyed when the last one exits ([user-keyring(7)](https://man7.org/linux/man-pages/man7/user-keyring.7.html)).
  Keys live in kernel memory, so nothing is written to disk and a reboot clears them.
- The persistent keyring (`keyctl get_persistent @u`) outlives the UID record and expires after
  `/proc/sys/kernel/keys/persistent_keyring_expiry`, default 259200 s (3 days), reset on each access;
  the man page's own example is cron jobs using credentials after logout
  ([keyrings(7)](https://man7.org/linux/man-pages/man7/keyrings.7.html)).
- Permission caveat: what a process may read depends on **possession**. pam_keyinit links the user
  keyring into the login session keyring, so processes from a login session possess `@u`'s keys; a
  process started outside that session (a systemd user service, a tmux server started elsewhere) may
  only get the narrower "user" permissions (keyrings(7)). The probe must read the key from the same kind
  of process the run's agents are, which run-preflight's probe already does. 99designs exposes
  `KeyCtlPerm` for exactly this.
- Fit: best match for "engineer stores it at preflight, run reads it overnight": no prompt, no daemon,
  no at-rest copy. Downside: a reboot or the user's last process exiting loses it (the run then fails at
  its first read, which is the right failure).

**`systemd-creds --user`**
- `--user`/`--uid=` encrypt a user-scoped credential that "may only be decrypted from the specified
  user's context", binding the UID, username and machine-id into the key
  ([systemd-creds(1) source](https://github.com/systemd/systemd/blob/main/man/systemd-creds.xml)).
  Added in **v256** ("Encrypted service credentials can now be made accessible to unprivileged users.
  systemd-creds gained new options --user/--uid=", [systemd NEWS](https://github.com/systemd/systemd/blob/main/NEWS));
  per-user credentials are decrypted through the `systemd-creds.socket` Varlink service (NEWS, v258 section).
- Keys: TPM2, the root-only host key `/var/lib/systemd/credential.secret`, or both (default when a TPM2
  exists). Decryption is automatic, no prompt (systemd-creds(1)).
- Fit: encrypted at rest, survives reboot, no prompt. Store with
  `systemd-creds encrypt --user --name=<n> - <file>` (stdin), read with
  `systemd-creds decrypt --user --name=<n> <file> -`. Requires systemd ≥ 256 and systemd as init (not
  in most containers or WSL without systemd). Older LTS distros ship older systemd (unverified for a
  specific distro here; detect with `systemctl --version`).

**Secret Service on a headless box**
- Python keyring's documented recipe: `dbus-run-session -- sh`, run `gnome-keyring-daemon --unlock`,
  type the password on stdin, Ctrl+D, then "run your application in the same D-Bus session as the
  daemon" ([keyring README](https://github.com/jaraco/keyring/blob/main/README.rst)).
- Fit: works if the agents are launched inside that session; any agent launched from another SSH
  session or tmux server won't see it. Worth supporting only through detection (if `secret-tool` works,
  use it), not as the recommended headless setup.

**`pass` (GPG)**
- Each secret is a GPG-encrypted file under `~/.password-store`; decryption goes through gpg-agent
  ([passwordstore.org](https://www.passwordstore.org/)). GCM supports it as `gpg` and needs `GPG_TTY` and
  a TTY pinentry headless (credstores.md).
- gpg-agent defaults: `--default-cache-ttl` 600 s, `--max-cache-ttl` **7200 s (2 h)**
  ([gpg-agent options](https://www.gnupg.org/documentation/manuals/gnupg/Agent-Options.html)). An
  overnight run therefore hits a pinentry prompt with nobody there unless the engineer raises the TTLs,
  presets the passphrase (`--allow-preset-passphrase` + `gpg-preset-passphrase`), or uses a
  passphrase-less key (then it's a key file on disk). Use it only when the engineer already uses pass.

**Password-manager CLI (1Password `op`)**
- Service accounts authenticate `op` without a person; export the token as `OP_SERVICE_ACCOUNT_TOKEN`;
  needs op ≥ 2.18.0; can't access Personal/Private/Employee vaults; rate-limited
  ([1Password service accounts: get started](https://www.1password.dev/service-accounts/get-started/)).
- The token is itself a secret that has to live in one of the stores above. SKILL.md already allows
  pointing the helpers at `op read` / `bw get`; keep that as an opt-in backend, not the default.

**Not recommended for this use**
- sops/age and similar file encryption: the decryption key sits in a file readable by the run, so it adds
  little over a 0600 file for a same-user unattended run (judgment, not a sourced claim).
- `keyrings.alt` / GCM `plaintext`: plaintext; GCM says "This is not a secure method of credential storage!"
- GCM `cache` / `git credential-cache`: in-memory with a 900 s default timeout, too short for a night.

### Windows: Credential Manager, with two catches

- Native store: `CredRead`/`CredWrite` with `CRED_TYPE_GENERIC`; blob ≤ `CRED_MAX_CREDENTIAL_BLOB_SIZE`
  (5×512 = 2560 bytes); persistence `SESSION`, `LOCAL_MACHINE` or `ENTERPRISE` (roams with the
  profile) ([CREDENTIALW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)).
  Python keyring writes `CRED_PERSIST_ENTERPRISE` by default, stores under the service name (compound
  `user@service` on collision) and reads with `CredRead(Type=CRED_TYPE_GENERIC)`
  ([`keyring/backends/Windows.py`](https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py)).
  go-keyring uses target `service:username`. The two tools' items are therefore **not interchangeable**;
  pick one naming scheme.
- **Catch 1, SSH:** `CredWrite` fails with `ERROR_NO_SUCH_LOGON_SESSION`: "Network logon sessions do not
  have an associated credential set" ([CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew)).
  GCM: over SSH "GCM is unable to persist credentials to the Windows Credential Manager due to
  limitations in Windows"; RDP is fine; use `dpapi` instead (credstores.md). So a run driven over SSH
  into a Windows box can't use Credential Manager; a run in an interactive (console/RDP) session can.
- **Catch 2, reading from a script:** there's no built-in CLI that prints a generic credential's secret
  (`cmdkey` lists and adds but, to my knowledge, doesn't show passwords; not verified against a primary source here). Reading needs the Win32 API: from PowerShell via
  P/Invoke or a module, from Python keyring, or a small binary. Microsoft's SecretManagement/SecretStore
  modules are archived ("feature complete and will no longer be actively developed"), and SecretStore
  is its own encrypted file whose unattended use needs a vault password, which Microsoft's example keeps
  in a DPAPI-encrypted `Export-Clixml` file
  ([SecretStore in automation](https://learn.microsoft.com/en-us/powershell/utility-modules/secretmanagement/how-to/using-secrets-in-automation),
  [overview](https://learn.microsoft.com/en-us/powershell/utility-modules/secretmanagement/overview)).
  The CredMan vault for SecretManagement is a community module.
- **WSL:** inside WSL it's Linux, so the headless-Linux options apply. GCM's WSL setup calls the
  Windows `git-credential-manager.exe` from WSL so credentials live in the Windows host store; a Linux
  GCM inside WSL "cannot use the host's credential storage"
  ([GCM docs/wsl.md](https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/wsl.md)).
  A secret helper could do the same by calling a Windows-side reader through interop, at the cost of
  a Windows-side dependency.
- Fit: if the Windows map chooses WSL-only, Windows needs nothing beyond the Linux helper. If it chooses
  native, Credential Manager for console/RDP sessions and DPAPI-protected files for SSH sessions, mirroring
  GCM's split.

## Detection order a helper could use

Modelled on 99designs' order and GCM's explicit override; a sketch for the build tickets, not a design:

1. `$AGENT_SECRET_BACKEND` if set (explicit override, like `GCM_CREDENTIAL_STORE`).
2. macOS: `security` (unchanged behaviour and item names).
3. Windows native (if in scope): Credential Manager; DPAPI file when in a network logon.
4. Linux: `secret-tool`, if installed, a session bus is reachable and a sentinel lookup returns within
   a timeout.
5. Linux: `systemd-creds --user`, if `systemctl --version` ≥ 256 and systemd is PID 1.
6. Linux: `keyctl` user keyring, if keyutils is installed.
7. Otherwise fail with the setup command for the best option on that box. Never fall back to plaintext
   silently (gh does; it shouldn't here, since preflight's purpose is to fail early).

Whichever backend is chosen, the service name `agent-team/<project>/<name>` stays the key, so the
skill text, allow rules and probe stay the same across platforms. Allow rules still pin one service,
one variable and one consumer per `secret-run.sh` rule.

## Open points for the build tickets

- `systemd-creds --user` and `keyctl` behaviour should be confirmed on the CI ubuntu runner (systemd
  version, whether keyutils is installed, possession from the runner's process tree).
- Whether the store-a-secret instruction in SKILL.md becomes one command per platform or a wrapper
  (`secret-store.sh <service>`) that reads from the terminal and writes to the detected backend.
- Windows naming scheme if native: go-keyring's `service:username` vs Python keyring's bare service.
