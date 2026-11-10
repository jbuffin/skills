# Crew memory is engineer-approved knowledge, per member

A crew member (ADR 0007) can remember things between runs as **crew notes**. A crew note is knowledge, never reasoning: a short fact the member learned and will need again, such as a test flag the repo needs or a convention a team expects. Verdicts, opinions on code quality, past review findings and accounts of what happened on a run are banned. Each note is a Markdown line with its date and the run that proposed it.

**Each member reads only its own notes.** Notes are never shared across a role or a crew. Anything true for everyone belongs in the repo's docs or the member file's instructions. This keeps reviewers independent.

**Two scopes, both loaded at launch:** (fleet, member) for notes that apply in every repo of the fleet, and (fleet, repo, member) for one repo. The member proposes the scope, and the engineer can change it when approving.

**Memory follows the name, never the layer.** A repo member that replaces a fleet member with the same name reads and adds to the same notes. A built-in member collects notes per fleet too, and "Customize for this fleet" keeps them because the name stays the same. A renamed member is a new member. Admiral's Crew page offers **Carry notes** on a rename, unchecked by default, and lists notes no member uses anymore under "Unclaimed notes" until they are deleted.

**Proposing.** A member proposes notes only in its final report, at most 3 per run. A crew boat that is stopped or killed proposes nothing. An unkept ad hoc member may propose notes. They wait on its ad hoc Inbox item: Keep approves them along with the member, and Drop discards them. The fix checker has no memory: it neither reads nor proposes notes.

**Approval is always the engineer's.** Inside Admiral, one Inbox item per run holds that run's proposals, with Keep, Edit or Drop per note and the member and scope shown in Peek. Outside Admiral, the lead asks in its final decision batch, and anything left unanswered is dropped. Notes are never approved automatically, not under autopilot and not when AdmiralBot launched the run. This is the gate that stops PR or comment text from becoming lasting instructions.

**Storage.** Notes live in the fleet's crew directory, at `crew/memory/<member>/fleet.md` and `crew/memory/<member>/repos/<owner>/<repo>.md`. Outside Admiral they live under `${XDG_CONFIG_HOME:-~/.config}/commodore/crew/memory/` in the same shape, beside the user-global crew files (ADR 0007). #194 wrote `~/.config`; the engineer chose to follow `XDG_CONFIG_HOME` while recording (2026-11-10). Notes are never stored in the repo, so a repo shared by two fleets never mixes their memory. Inside Admiral the user-global memory is ignored and never imported, as with the member files.

**Loading.** The resolution script puts the member's fleet notes and this repo's notes into the crew boat's prompt under a fixed heading. A ship launched as a member gets them the same way through Admiral's Go resolver, and both paths are checked against the shared fixtures in this repo.

**Cap.** 30 notes per scope. Once a scope is full, a proposal must name the note it replaces. Nothing expires. On the Crew page, each member shows its notes by scope, and the engineer can edit, move or delete them.

Decided in [#194](https://github.com/jbuffin/skills/issues/194).

## Consequences

ADR 0007's rule that the name slug is a member's identity now covers its memory too, and ADR 0007's "Renaming a member makes it a new member" means its notes stay behind unless the engineer ticks **Carry notes**. The resolution script and Admiral's Go resolver both load notes, so the two implementations ADR 0007 already keeps in step through shared fixtures gain one more thing to agree on. A teammate's report format grows a place for note proposals, which the skill text adds in a later build PR, alongside the crew-member changes from #193.
