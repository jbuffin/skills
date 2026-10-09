# Changesets

Each file here describes one change and how much it bumps the version. Add one with `npx changeset`
in any PR that adds, removes or materially changes a skill. On merge to `main`, the release workflow
collects them into a "Release skills" PR that bumps `package.json`, syncs both `.claude-plugin/*.json`
manifests and writes `CHANGELOG.md`. Merging that PR tags the release.

- `patch`: wording fixes and small behaviour corrections in an existing skill.
- `minor`: a new or promoted skill, or a new capability in an existing one.
- `major`: a removed or renamed skill, or a change that breaks how existing users run one.
