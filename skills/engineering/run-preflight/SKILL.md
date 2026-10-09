---
name: run-preflight
description: Pre-flight for an unattended run. List what only the engineer can give (secrets, allow rules, environments, data the run may write, decisions), store secrets in the Keychain, and prove each gated action with a probe. Use when the user is about to leave a run unattended or overnight.
---

# Run pre-flight

An unattended run fails at the first thing only the engineer can give it, like a password, a permission prompt or a decision. And it fails while they're asleep. One denied file read a few hours in can leave the whole run waiting until morning. Pre-flight finds every one of those things while the engineer is still at the keyboard, settles it, and proves it's settled.

A requirement counts as settled only once it has actually been exercised. Someone saying yes isn't enough.

## 1. Requirements manifest

Walk through the plan step by step, including every agent's actions within each step, and write `requirements.md` in the run directory (one you choose, or the one an orchestrating skill gives you). It lists everything the run can't provide for itself. Done when every agent action in the plan either maps to a row or needs nothing from the engineer.

| Kind | Examples | Settled by |
| --- | --- | --- |
| Secrets | a stage test user's password, API tokens | the engineer storing them (section 2) |
| Accounts and data | a test user with several tenants, or enough records for the scenarios | the engineer confirming, or choosing scenarios the data supports |
| Shared data the run writes | stage records a test changes, uploads, sent messages | named test records, a way to reset them, and the engineer's OK |
| Target | the device, browser or environment the work is evaluated on, who else uses it, what must not be touched | the `target-evaluation` skill, and telling other sessions to stay off it |
| Build environment | which backend or config the build under test points at, and that the accounts exist there | reading the build's config where the agents will build it (an ignored env file that a fresh worktree lacks is the usual miss), then the probe |
| Manual target changes | settings the target won't let an agent change, like an OS setting or a device mode the scenarios need | the engineer making them before leaving, asked for in the same batch |
| Tools | the CLIs, SDKs and extensions the run calls | `scripts/preflight.sh` |
| Gated actions | installs and deploys, typing or passing credentials, `gh pr create/edit/comment/ready`, force-pushes to the run's branches, writes to external systems (ticket trackers, chat) | allow rules (section 3), approved in the batch (section 4), then the probe (section 5) |
| Decisions | anything only the engineer can decide: product behaviour, departures from the design, scope, PR state | one batch (section 4) |
| Availability | when the engineer will be away | a plan where nothing in that window needs them |

## 2. Secrets go in a store

The engineer stores each secret in their own terminal, outside the session. Typing it into the session or a `!` command leaves the command line in a transcript.

```bash
security add-generic-password -U -s <service> -a <account> -w
# -w with no value prompts for the secret; -U updates an existing item
```

Name the services per project and environment, like `agent-team/<project>/stage-test-pass`. Agents use secrets only through this skill's helpers, which read the Keychain and hand the value straight to whatever consumes it. Every other skill's secret rule points here. `scripts/secret-run.sh <service> <ENV_VAR> -- <command…>` runs a command with the secret in one environment variable. That fits a UI-test run that fills a field from the environment, an API script, or a CLI.

If a target needs a secret typed in rather than passed, write a helper of the same shape: Keychain straight to the consumer, value never printed. Or make that sign-in a step the engineer does before leaving. If the engineer already uses a password manager CLI (`op read`, `bw get`), point the helpers at it. The rule doesn't change. The value goes from the store to its consumer and never passes through a model.

The first Keychain read from a new process can pop up a macOS "allow access" dialog. Have the probe trigger it while the engineer is there to click Always Allow.

If the engineer pastes a secret into chat anyway, keep it out of every file, brief, log and message you write. Tell them to store it the way shown above, and to think about rotating it, since it's now in the transcript. Treat a plaintext credentials file left over from an earlier run the same way. Move it to the Keychain, delete the file, and remove any allow rule that pointed at it.

## 3. Allow rules

Draft the exact `permissions.allow` rules the manifest needs, and nothing more. Walk every gated action and every command that drives the target: installs, setting changes, file pulls off a device, typing a secret. A permission classifier also judges actions by category, such as credential use or changing a shared resource, so a command that looks harmless still needs its rule. For example:

```text
Bash(<this skill>/scripts/secret-run.sh agent-team/<project>/stage-test-pass STAGE_PASS -- <the UI test command>:*)
Bash(<the target's install or deploy command>:*)
Bash(gh pr create --draft:*)  Bash(gh pr edit:*)  Bash(gh pr comment:*)
Bash(<a push wrapper that pins the refspec> <run>:*)
```

Pin each `secret-run.sh` rule to one service, one variable and one consumer command, and add one rule per consumer. A prefix rule on the helper alone, `Bash(<this skill>/scripts/secret-run.sh:*)`, is the one to refuse. The command runs from the tail of the helper's arguments, so it approves any command with the secret already exported (`… -- sh -c 'echo $STAGE_PASS'` would print it). The same goes for any helper that runs the command after its `--`.

Force-pushes go through a wrapper that pins the refspec to the run's own branches, such as agent-team-build's `push-branch.sh`. A prefix rule on `git push --force-with-lease origin <branch-prefix>*` also matches `origin <branch-prefix>x:main`, which force-pushes main.

Rules match the literal command, and agents make every call bare (agent-teammates defines it). Write the paths exactly the way the agents will type them, because a symlinked skills folder resolves to a different path. Where a permission classifier judges actions by their description, add the plain phrasing the environment accepts, such as "pass the stage test user's password to the UI tests via the Keychain helper". Done when every gated action in the manifest has a rule. The engineer approves them in the section 4 batch, and then you write them to settings.

## 4. One batch of decisions

Ask the engineer one question (AskUserQuestion, or a single message) that covers the run's ground rules, the allow rules from section 3, the manual target changes, and every decision you can see coming, each with a recommended default. Done when every decision is answered and recorded wherever the run keeps its state, and the approved rules are in settings.

## 5. Static checks, then the probe

`scripts/preflight.sh <dir-or-env-file>` runs the static checks. It covers tools, `gh` auth, the repository and base branch, and whether CI actually runs on the run's branches. `scripts/ci-branch-check.py` does that last check, since a filter naming only the base branch skips every stacked PR above the first. It also checks the target URL, whether the Keychain items exist, and whether plaintext credential files or secret literals have crept into the run's files. The script's header lists the settings it reads.

Then comes the probe. It's an agent with the same runtime, model and permission mode as the run's real agents (in a team run, launched with the agent-teammates skill). It performs each gated action once, harmlessly, and reports each one as OK, DENIED or PROMPTED along with the exact message. Your own permissions as coordinator prove nothing here, because other sessions get judged separately. The probe does all of these:

- reads each Keychain item through the helpers into `true`, never onto the screen
- confirms the build under test points at the intended environment (the served bundle's or the config's API host), since a build that silently falls back to another environment makes valid credentials fail
- installs or deploys a throwaway build to the target, clears any install dialog, and removes the build
- drives the target once the way the run will, like a tap and a screenshot, a page load and a console read, or one API call
- passes a dummy Keychain item through whichever helper the target uses
- runs `gh pr view` on an open PR, and opens a throwaway draft PR only if the engineer agrees
- force-pushes one of the run's own branches through the same push command the run will use, while the push can't lose anything (a branch with no commits yet, or one already up to date)
- does a read with each external CLI, plus a write on a sandbox item if one exists
- waits inside a Bash loop for 2 minutes and confirms its turn didn't end
- writes its report, then its done marker

The probe records a denial and carries on with the next action, so one pass surfaces every gate. Fix every DENIED or PROMPTED line in one batch with the engineer, then probe again, until the report comes back clean.

## 6. The all-clear

Tell the engineer in so many words what's settled, what the run will do without them, what ends it, roughly how long it'll take, and what would make it stop and wait. Then tell them they can leave.
