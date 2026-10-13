---
name: setup-commodore
description: Writes a Commodore role-override file with you, one role at a time. It picks installed skills for each role, drafts how they combine, and saves the file for just you or for everyone on the repo. Use when setting up which skills Commodore's roles run, or rerun it to update the file when skills change.
disable-model-invocation: true
metadata:
  internal: true
---

# Setup Commodore

Write a Commodore role-override file with the engineer, one role at a time. Each role entry is an ordered list of installed skills and the `instructions` for combining them, in the shape ADR 0004 fixes: `{"<role>": {"skills": ["<bare name>", ...], "instructions": "..."}}`.

`scripts/roles-draft.sh` does every file and harness lookup. Run it from the repo. `<run>` below is the scratch directory its `init` prints.

## 1. Load the target file

Ask the engineer which file to edit:

- **Just me, everywhere** (`user`): `${XDG_CONFIG_HOME:-~/.config}/commodore/roles.json`.
- **Everyone on this repo** (`repo`): `.commodore/roles.json`, committed.

Run `scripts/roles-draft.sh init <user|repo>`. The run keeps that target to the end. On exit 5 about the harness, ask the engineer which harness this session runs in, and pass it as a third argument (`claude`, `codex` or `copilot`). It prints three lines:

- `<run>`;
- `FROM <file>` (the draft, `<run>/draft.json`, starts from that file's entries) or `NEW <file>` (the draft starts as `{}`);
- `ROLES <path>`: commodore's role reference. Read its Role skills section and every role's **contract** and **fallback**.

On `FROM`, run `scripts/roles-draft.sh check <run>`. Show the engineer the table, and each `not available` line as a skill missing on this harness, whose role needs re-picking.

Done when you've read the role reference and the engineer has seen what the current file resolves to (or knows it's new).

## 2. Rank candidates

Run `scripts/roles-draft.sh skills <run>`. It prints `<name><TAB><file><TAB><description>` for each skill this harness can load here. Exit 3 means the harness can't list its skills, so ask the engineer which skills to consider.

For each role, compare each description with the role's contract and fallback. Rank the skills that fit, best first, each with one line on why it fits.

Done when every role has a ranked list, possibly empty.

## 3. Settle each role

Go through the roles in this order: `implementer`, `test-writer`, `reviewer`, `security-reviewer`, `brief-checker`, `triager`, `target-steward`, `scribe`. For each role:

1. Show its entry in the draft, if any, and its ranked candidates. The engineer picks zero, one or several skills and puts them in order, or keeps the entry as it is.
2. For picked skills, read each one's `<file>`, then draft `instructions`:
   - the order the skills run in and what each one's output feeds into, e.g. "Draft the PR body with `pr`, then run `unslop` over it.";
   - every step that clashes with the role's contract, resolved in the contract's favour. The contract wins over any skill or instruction, so the instructions bend each skill to the contract and keep every contract item: read-only, the report, proofs, the triager's data rule. Example: `tdd`'s confirm-the-seams step and its vertical slices clash with a separate red test writer and green implementer. The test writer takes the seams from the brief and writes the failing tests without asking, and the implementer makes them pass.
3. Show the entry as JSON. Write it into `<run>/draft.json` only once the engineer approves it, edited or as drafted. Go to the next role only after approval.
4. For a role with no skills, tell the engineer what that means, then record their choice:
   - Leave the role out of the file, and a lower layer decides. Below the repo file, that's each engineer's user-global file. Below the user-global file there's only the fallback.
   - Write `"skills": []`, and the role gets the fallback even where a lower layer sets skills.

   The fallback is the role's fallback procedure, with two exceptions. A security reviewer with no skills isn't launched at all. Every run puts that in its phase 1 decision batch and won't start without approval. In the review mission, the review waits for approval. The target steward always runs `target-evaluation`, which no layer replaces, and any role skills run within that skill's rules.

Done when every role has an approved entry or a deliberate choice to leave it out or clear it.

## 4. Check the draft

Run `scripts/roles-draft.sh check <run>` and show the engineer the table and each `UNSET` line. Settle each `WARN` line with them: fix the entry, or keep a skill this harness lacks because they use it on another harness. Exit 1 means the draft isn't valid JSON. Fix it and run the check again.

Done when it prints `CLEAN`, or the engineer has accepted each remaining warning.

## 5. Save

Show the whole draft and the file it replaces, and get the engineer's go-ahead. To save to the other target instead, start again from step 1 with that target, so its file's entries load first. Before saving, tell the engineer:

- For each `SHADOWED` line, the repo's `.commodore/roles.json` sets that role, and the repo layer replaces the whole entry, so their user-global entry does nothing in this repo.
- The check covered this harness only, but the file applies on every harness. A skill missing on another harness is dropped there, like Claude Code's built-in `code-review` on Codex. Offer to rerun this skill from another harness to check.

Run `scripts/roles-draft.sh save <run>`. It writes only the target file, with each `skills` an ordered array of bare names, and prints `SAVED <file>`.

For `user`, that's it. For `repo`, show `git diff` (or the new file), then offer to commit it on a new branch and open a PR. Only once the engineer agrees, branch, commit `.commodore/roles.json` alone, push, and open the PR with `gh pr create`.

Finish by deleting `<run>`.
