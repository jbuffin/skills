# Contributing

This is a personal skill collection. Issues are welcome; pull requests aren't accepted. Each skill
keeps one author's voice and scope, so I make the changes myself. A PR opened here will be closed,
however good it is.

## Report a problem

Use the [Skill problem](https://github.com/jbuffin/skills/issues/new?template=skill-problem.yml)
form when a skill did the wrong thing, stopped partway, or wouldn't install or load. The most useful
reports include:

- the skill version (from `/plugin`, or the commit you installed from) and `claude --version`
- the command or prompt that started it
- the step where it went wrong, with the excerpt of the transcript, report or error that shows it
- the line in the `SKILL.md` that says it should have gone otherwise, if there is one

Redact secrets, internal hostnames, and company or customer names first. These skills run against
real repos, accounts and devices, so their transcripts often contain things that shouldn't be public.

## Suggest a skill or a change

Use the [Skill idea](https://github.com/jbuffin/skills/issues/new?template=skill-idea.yml) form.
Describe one narrow job and the situation that should make an agent load the skill. That becomes the
skill's description, so it matters most. I may build it, fold it into an existing skill, or decline it
if it doesn't fit the collection.

## Security problems

If a skill could leak a secret or act outside what it was allowed to do, don't open an issue.
[Report it privately](https://github.com/jbuffin/skills/security/advisories/new).

## Using the skills elsewhere

The skills are [MIT licensed](LICENSE). Forking, copying and adapting them is fine. Keep the license
notice with what you copy.
