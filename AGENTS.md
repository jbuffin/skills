# Working in this repo

This repo publishes agent skills. Each skill is a folder with a `SKILL.md` (YAML frontmatter + instructions).

## Lifecycle

- New skills start in `incubator/` via `scripts/new-skill.sh <name>`. Incubator skills keep
  `metadata.internal: true` and are never installed by `npx skills add`.
- A skill moves to `skills/<category>/` only via `scripts/promote.sh <name> <category>`. It removes the
  internal flag, adds the skill's row to the Skills table in `README.md`, and adds a new category to the
  `skills` array in `.claude-plugin/plugin.json` (the Claude Code plugin only loads categories listed
  there). Do not hand-move skills between trees.
- When you rename or remove a skill, update its row in the README Skills table yourself.
  `scripts/validate.sh` fails if a promoted skill has no row.
- Bump `version` in both `.claude-plugin/*.json` files when promoting or materially changing a skill.

## Writing skills

- Frontmatter `name` must equal the folder name (lowercase, hyphens, ≤64 chars). `description` says
  what the skill does and when to use it, ≤1024 chars. It's the only text an agent sees when deciding
  whether to load the skill.
- Set `disable-model-invocation: true` on skills that change shared systems (push, post, deploy, file
  tickets), so they run only when the user types `/<name>`.
- Write for an agent, not a human reader: imperative steps and concrete commands. Leave out background
  prose the agent can't act on.
- Keep skills narrow. If a skill covers two unrelated jobs, split it into two.
- Keep `SKILL.md` focused; put long reference material in `references/`, executables in `scripts/`,
  and static files in `assets/` next to it. Link to them instead of duplicating them.
- Scripts that ship in a skill keep LF line endings, are executable, and pass the CI linters
  (`shellcheck` or `zsh -n`, `ruff`).

## Checks and pull requests

- Run `scripts/validate.sh` before committing. CI runs it plus shell, Markdown, Python, workflow,
  plugin and discovery checks (see the Checks section of `README.md`).
- When a PR changes a `SKILL.md`, say in the description what behaviour changes for the agent.
