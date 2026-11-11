---
name: setup-commodore
description: Writes Commodore crew members with you, one role at a time. It picks installed skills for each role, drafts how they combine, and saves one member file per role for just you or for everyone on the repo. Use when setting up which skills Commodore's roles run, or rerun it to update the members when skills change.
disable-model-invocation: true
---

# Setup Commodore

Write Commodore crew members with the engineer, one role at a time. Each member is a Markdown file named after its role, so it replaces the built-in one. Its `skills` list is the installed skills in run order, and its body is the instructions for combining them. The file format is in commodore's [`references/crew-members.md`](../commodore/references/crew-members.md); follow it rather than restating it here.

`scripts/crew-draft.sh` does every file and harness lookup. Run it from the repo. `<run>` below is the scratch directory its `init` prints, and the draft is the directory `<run>/draft/`.

## 1. Load the target directory

Ask the engineer which crew directory to edit:

- **Just me, everywhere** (`user`): `${XDG_CONFIG_HOME:-~/.config}/commodore/crew/`.
- **Everyone on this repo** (`repo`): `.commodore/crew/`, committed.

Run `scripts/crew-draft.sh init <user|repo>`. The run keeps that target to the end. On exit 5 about the harness, ask the engineer which harness this session runs in, and pass it as a third argument (`claude`, `codex` or `copilot`). It prints these lines:

- `<run>` (any `WARN` line `init` prints for a member it skipped, a symlink or a file outside the target, goes to stderr: show it to the engineer);
- `FROM <dir>` (the draft starts with that directory's role-named members) or `NEW <dir>` (the draft starts empty);
- `ROLESJSON <file>`, only when the target still holds a `roles.json`, which Commodore no longer reads. Offer `scripts/convert-roles.py <file> <dir>` before going on; it writes member files and never deletes the JSON. Once the engineer confirms the members resolve, they delete it. Then run `init` again so the draft picks up the converted members;
- `ROLES <path>`: commodore's role reference. Read its Crew members section and every role's **contract** and **fallback**. Skip the fix checker's section: it takes no role skills and has no fallback, so don't offer it as a role to configure.

On `FROM`, run `scripts/crew-draft.sh check <run>`. Show the engineer the table, and each `not available` line as a skill missing on this harness, whose role needs re-picking.

Done when you've read the role reference and the engineer has seen what the current file resolves to (or knows it's new).

## 2. Rank candidates

Run `scripts/crew-draft.sh skills <run>`. It prints `<name><TAB><file><TAB><description>` for each skill this harness can load here. Exit 3 means the harness can't list its skills, so ask the engineer which skills to consider.

For each role, compare each description with the role's contract and fallback. Rank the skills that fit, best first, each with one line on why it fits.

Done when every role has a ranked list, possibly empty.

## 3. Pick skills from a checklist

Ask for the picks as checklists, four roles per prompt, in this order: `implementer`, `test-writer`, `reviewer`, `security-reviewer`, then `brief-checker`, `triager`, `target-steward`, `scribe`.

- **On Claude Code:** one `AskUserQuestion` call per four roles, one multi-select question per role. The options are three skills, each described by its one-line reason, then `None`. The skills in the role's current member come first, marked `(current)`, and its best candidates fill the rest. The tool's own "Other" line takes skill names the checklist missed.
- **On a harness without a multiple-choice tool:** one message listing every role with its numbered candidates, answered in one reply, e.g. `implementer: 2,1  reviewer: none  scribe: 1, unslop`.

Done when every role has its picks, even if that's none.

## 4. Approve the members

Draft every role's member, then get them approved in one batch.

1. Order each role's picks, and for a role with skills, read each one's `<file>` and draft the member's body, its instructions:
   - the order the skills run in and what each one's output feeds into, e.g. "Draft the PR body with `pr`, then run `unslop` over it.";
   - every step that clashes with the role's contract, resolved in the contract's favour. The contract wins over any skill or instruction, so the instructions bend each skill to the contract and keep every contract item: read-only, the report, proofs, the triager's data rule. Example: `tdd`'s confirm-the-seams step and its vertical slices clash with a separate red test writer and green implementer. The test writer takes the seams from the brief and writes the failing tests without asking, and the implementer makes them pass.

   When the picks match the current member's skills, start from its instructions. Draft a `pick-me-when` for each member too: one line saying when the lead should pick it for the role.
2. Show every drafted member together, file by file.
3. Ask for approval as checklists too, four roles per prompt, the `pick-me-when` included. A role with skills gets `Approve` and `Edit…`, where "Other" carries the edit. A role with none gets two choices, each described by what it means:
   - `Leave out`: no draft file, so a lower layer decides. Below the repo crew, that's each engineer's user-global crew. Below the user-global crew there's only the built-in member.
   - `Clear with []`: a member named after the role with `skills: []` and `pick-me-when: Clears <role>'s skills, so the role uses its fallback procedure.`, so the role uses its fallback even where a lower layer sets skills.

   The fallback is the role's fallback procedure, with two exceptions (the fix checker, which is never configured, has none). A security reviewer with no skills isn't launched at all. Every run puts that in its phase 1 decision batch and won't start without approval. In the review mission, the review waits for approval. The target steward always runs `target-evaluation`, which no layer replaces, and any role skills run within that skill's rules.
4. Write each approved member to `<run>/draft/<role>.md`. Redraft each edited one and ask about those roles again.

Done when every role has an approved member file in `<run>/draft/`, or an approved choice to leave it out or clear it.

## 5. Check the draft

Run `scripts/crew-draft.sh check <run>` and show the engineer the table and each `UNSET` line. Settle each `WARN` line with them: fix the member, or keep a skill this harness lacks because they use it on another harness. Exit 1 means a member file is invalid: fix it and run the check again.

Done when it prints `CLEAN`, or the engineer has accepted each remaining warning.

## 6. Save

Show each file the save will write and each file it will remove (a role the draft leaves out loses its member in the target), and get the engineer's go-ahead. To save to the other target instead, start again from step 1 with that target, so its members load first. Before saving, tell the engineer:

- For each `SHADOWED` line, the repo has a member of the same name, and the repo layer replaces the whole member, so their user-global member does nothing in this repo.
- For each `OUTRANKED` line, the repo has a differently named member for that role, and it wins the default pick in this repo over the draft's member. On the user target that member outranks their user-global one. On the repo target both are in the same layer, so the other member competes with the new one and the name order decides: offer to rename or remove it.
- The check covered this harness only, but the file applies on every harness. A skill missing on another harness is dropped there, like Claude Code's built-in `code-review` on Codex. Offer to rerun this skill from another harness to check.

Run `scripts/crew-draft.sh save <run>`. It writes the draft's files into the target, removes the role-named members the draft left out, touches no other member, and prints `SAVED <file>` or `REMOVED <file>` for each. Exit 1 with a `symlink` message means the target dir, its parent or a member file is a symlink and nothing was written: show the engineer the path and stop until they resolve it.

For `user`, that's it. For `repo`, show `git diff` (or the new files), then offer to commit them on a new branch and open a PR. Only once the engineer agrees, branch, commit `.commodore/crew/` alone, push, and open the PR with `gh pr create`.

Finish by deleting `<run>`.
