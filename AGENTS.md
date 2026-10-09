# Working in this repo

This repo publishes agent skills. Each skill is a folder with a `SKILL.md` (YAML frontmatter + instructions).

- New skills start in `incubator/` via `scripts/new-skill.sh <name>`. Incubator skills keep
  `metadata.internal: true` and are never installed by `npx skills add`.
- A skill moves to `skills/` only via `scripts/promote.sh <name>`, which removes the internal flag.
  Do not hand-move skills between trees.
- Frontmatter `name` must equal the folder name (lowercase, hyphens, ≤64 chars). `description` says
  what the skill does and when to use it, ≤1024 chars.
- Keep `SKILL.md` focused; put long reference material in `references/`, executables in `scripts/`,
  and static files in `assets/` next to it.
- Run `scripts/validate.sh` before committing.
- Bump `version` in both `.claude-plugin/*.json` files when promoting or materially changing a skill.
