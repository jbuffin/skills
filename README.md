# agent-skills

Personal collection of agent skills ([Agent Skills spec](https://agentskills.io)), installable with the
[`skills` CLI](https://github.com/vercel-labs/skills) or as a Claude Code plugin.

## Layout

```
skills/<name>/SKILL.md       Promoted. Discovered and installed by `npx skills add`.
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
npx skills add jbuffin/agent-skills --list
npx skills add jbuffin/agent-skills --skill <name>
npx skills add jbuffin/agent-skills            # all promoted skills

# Claude Code plugin route
/plugin marketplace add jbuffin/agent-skills
/plugin install jbuffin-skills@jbuffin-skills
```

To try an incubator skill without promoting it, point the CLI at its folder:

```bash
npx skills add ./incubator/<name>
```

## Workflow

```bash
scripts/new-skill.sh my-skill      # scaffold incubator/my-skill
# ...iterate...
scripts/validate.sh                # check frontmatter in both trees
scripts/promote.sh my-skill        # move to skills/, drop internal flag
```

Validation runs in CI on every push and pull request.
