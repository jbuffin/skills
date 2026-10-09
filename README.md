# skills

Personal collection of agent skills ([Agent Skills spec](https://agentskills.io)), installable with the
[`skills` CLI](https://github.com/vercel-labs/skills) or as a Claude Code plugin.

## Layout

```
skills/<category>/<name>/    Promoted, grouped by category (e.g. engineering). Discovered and
                             installed by `npx skills add`.
incubator/<name>/SKILL.md    In development. Not in a discovery path, and marked
                             `metadata.internal: true` as a second guard.
templates/SKILL.template.md  Starting point used by scripts/new-skill.sh.
scripts/                     new-skill, promote, validate.
.claude-plugin/              Claude Code plugin + marketplace manifests.
```

## Install

The repo is private, so the CLI needs GitHub access (`gh auth login`, or `GITHUB_TOKEN`/`GH_TOKEN`).

```bash
# list / install promoted skills
npx skills add jbuffin/skills --list
npx skills add jbuffin/skills --skill <name>
npx skills add jbuffin/skills            # all promoted skills

# Claude Code plugin route
/plugin marketplace add jbuffin/skills
/plugin install jasonbuffin@skills
```

To try an incubator skill without promoting it, point the CLI at its folder:

```bash
npx skills add ./incubator/<name>
```

## Prerequisites

### Engineering team skills

`skills/engineering/` holds four skills that work together: `agent-team-build` (the orchestrator),
`agent-teammates`, `run-preflight` and `target-evaluation`.

- **Install all four together.** `agent-team-build` runs scripts from the other three by sibling path, so
  `npx skills add jbuffin/skills --skill agent-team-build` alone leaves it broken. The plugin route always
  installs all four.
- **macOS with zsh.** The scripts are zsh, and secrets live in the macOS Keychain (`security`).
- **Claude Code with background sessions.** Teammates run as `claude --bg` sessions and are watched with
  `claude agents`. Run `claude` once in the target repo and accept the trust prompt, or launches fail with
  "Workspace not trusted". Without background sessions, teammates fall back to in-process subagents.
- **CLI tools on `PATH`:** `git`, `gh` (logged in with `gh auth login`), `python3`, `jq`, `curl`.
- **`gh-stack` 0.2.0 or later** for stack mode: `gh extension install github/gh-stack`. Also installable
  as a skill (`npx skills add github/gh-stack`), which the stack mode reads if it's there.
- **Optional:** `cmux` or `tmux` for viewer panes on each teammate (`VIEWER` in `team.env`).
- **Optional role skills.** The profile can name a skill per role. The examples (`/tdd`, `/code-review`,
  `/pr`) come from [mattpocock/skills](https://github.com/mattpocock/skills):
  `npx skills add mattpocock/skills`. A role with no skill named follows its section in
  `agent-team-build/references/roles.md`.

`agent-team-build/scripts/team-preflight.sh` checks most of this at the start of a run.

## Workflow

```bash
scripts/new-skill.sh my-skill      # scaffold incubator/my-skill
# ...iterate...
scripts/validate.sh                # check frontmatter in both trees
scripts/promote.sh my-skill engineering   # move to skills/engineering/, drop internal flag
```

Validation runs in CI on every push and pull request.
