---
name: target-evaluation
description: Evaluate a change on its real target (a physical device, a browser against stage, the deployed API, a clean install) before any fallback, with a light check per change and full scenario evaluations against the reference. Use when a change needs checking on a device, in a browser or on stage, or QA before a PR.
---

# Target evaluation

The target is wherever the work runs for its users. Evaluate there, on the most realistic option you can get. The defects that matter most often only show up there, in packaging, configuration, real data, real input, and how the thing actually looks.

## Choose the option

List the options for the target type in order of preference, real thing first, and take the first one that's actually available.

- Mobile: a physical device, then an emulator or simulator.
- Web: the users' browser against a deployed environment (stage, a preview), then a local server. Cover every viewport the product supports.
- API or backend: the deployed stage service, then a local instance with the real schema and realistic data.
- CLI or library: a clean install of the built artifact in a fresh environment, then the dev build.
- Desktop: the installed build, then a dev run.

Say what the option you picked can't show. How to install, drive and inspect a particular target comes from the repo's own docs, not from this skill. Use the repo's helper scripts for capturing frames, reading element bounds and checking the build's environment where it has them. If it has none and you write your own, put them in the run's working directory and name them in your report, so the next request reuses them instead of rebuilding them.

If the acceptance bar names the real target ("works on a real device") and you only have a fallback, the bar stays open. Report it as open, or get the engineer to accept the fallback.

## Own the target

Only one agent touches a target at a time. Use your own test account and your own browser profile or device session, so the engineer's stay untouched. Secrets reach the target only through run-preflight's helpers. Without that skill, use the repo's own secret helper if it has one, or have the engineer sign the target in before you start. Never type, print or write a secret's value yourself. Dismiss the target's known dialogs with the button the run's notes or the repo's docs name, choosing only options that keep data in and permissions as they are. Clean up only the processes you started. After every request, leave the target the way you agreed to: signed out, settings restored, production untouched.

## Light check, every change

This should take minutes, not an hour.

1. Install or deploy the build.
2. Confirm the build points at the environment the accounts live in, from the build's own output (the served bundle, the deployed config, a request's host). Do this before signing in. A build that fell back to another environment makes valid credentials fail, and that reads as a credentials problem.
3. Sign in through run-preflight's secret helper, or confirm the engineer's sign-in is still active.
4. Run the change's smoke flow.
5. Confirm the error channel is empty, whether that's the crash log, the browser console or the service logs.
6. Run the project's UI or integration suite, if it has one.

The light check passes when every step succeeds and the error channel is empty. At the first failing step, stop and report that step with its output.

## Full evaluation, on a cadence

Run one every 2–3 changes, whenever something user-visible changed, and for final acceptance. It passes when every scenario passes and the comparison shows no unexplained difference.

- Run every scenario, each with pass/fail and evidence: screenshots, logs, request/response pairs (secrets redacted).
- Compare side by side with the reference at the same scale. The reference is the design, or the version being replaced. Check sizes, spacing, alignment and copy. "It renders" isn't enough.
- Cover the edge states the scenarios imply: empty, error, slow network, long content, rotation or resize, signed out.
- Rank the defects, each with exact steps to reproduce it.

## Report

```text
Target: <option used>; blind spots: <list>
Light check: <pass/fail per step>   Full evaluation: <yes/no>
Not checked: <scenarios, states or viewports skipped, and why | nothing>
Scenarios: <table: scenario | pass/fail | evidence path>
Comparison with reference: <differences found, with screenshot paths>
Defects: <ranked, with repro>
Left the target: <state>
```
