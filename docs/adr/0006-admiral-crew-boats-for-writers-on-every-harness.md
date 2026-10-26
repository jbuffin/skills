# Inside an Admiral ship, writers on every harness are crew boats

Inside an Admiral ship (`ADMIRAL_SHIP` set), the admiral driver launches a Codex or Copilot teammate that isn't read-only as a crew boat (`admiral crew launch --harness <HARNESS>`), live and re-tasked by `admiral crew send`, as it already does for Claude. A `--read-only` Codex or Copilot teammate stays headless: the admiral driver hands it to `drivers/<HARNESS>`, exactly as outside a ship, and routes its later operations there by id. Under `ADMIRAL_AUTOPILOT=1` Admiral refuses Codex and Copilot boats, so every teammate on those harnesses stays headless.

## Considered options

- **Every teammate is a crew boat, read-only ones too**: rejected. Interactive Codex has no `--ignore-rules` (it is an `exec` flag), so the user's git allow rules would apply to a read-only boat, and an allow rule runs its command outside the sandbox. A read-only Copilot boat can't write its report without a permission prompt. Headless keeps today's read-only guarantee and report path.
- **Keep Codex and Copilot headless everywhere**: rejected. Inside a ship the engineer wants Admiral as the viewer and live re-tasking, and #115 asks for "every harness".
- **Select the driver per harness in `team-env.zsh` alone**: rejected. The choice is per teammate (writer or read-only), so the routing lives in `drivers/admiral`: `launch` records a handed-over teammate's id in `<team-dir>/admiral-delegated`, and `send`, `stop`, `status` and `tail` check that file first.

## Consequences

This changes ADR 0002's teammate-contract paragraph and ADR 0003 for writers inside an Admiral ship. There the teammate contract depends on the role: a writer gets the `LIVE_MESSAGING=1` lines and a read-only Codex or Copilot teammate the `LIVE_MESSAGING=0` lines, and one run uses two drivers. ADR 0003's decision text stands for everything outside a ship, for read-only teammates and under autopilot.

A new boat stops at a first-run screen that never fires a hook: Codex's folder trust and "Hooks need review", Copilot's folder trust. The launch then closes the boat and exits 5 after `LAUNCH_WAIT`. The engineer settles these once per dock before a run, and the admiral driver's `preflight` WARNs about them. Admiral also hasn't confirmed that Copilot loads its hooks from `--plugin-dir`; if it doesn't, every Copilot writer launch exits 5.

`teammate-tail.sh` can't render a Codex or Copilot crew boat's transcript with the harness's own tail, so it prints the transcript path and its last lines raw.
