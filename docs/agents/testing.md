# Testing

What to test, where each test goes, and how to run the tests.

## What to test

A skill is mostly Markdown an agent reads. `scripts/validate.sh` checks its structure (frontmatter, names, links,
the README row), and a person reviews its wording. Tests cover the scripts a skill ships and what an agent does with
the skill.

Each behavior gets one test, at the lowest layer that can see it:

| The behavior | Its layer |
| --- | --- |
| Frontmatter, names, links, plugin manifests, README rows | `scripts/validate.sh` |
| What a skill's script prints, writes or exits with for an input | Script test in `evals/<skill>/test_*.py` |
| A file a script parses (crew member files, run state) | Script test that asserts the parsed result |
| What an agent does when it runs the skill | Skill eval: `evals/<skill>/<case>/case.yaml` |

A test earns its place when it would catch a bug a person could hit:

- Assert outcomes: the exit code, the file written, the status token or prefix a skill reads (`OK`, `WARN`, `FAIL`,
  `DONE`). A test that still passes after the code under it breaks, or fails after a refactor that keeps the
  behavior, is a change detector; rewrite it or delete it.
- Assert behavior, never wording. A test that checks a `SKILL.md`, a reference, the glossary, a brief or a message's
  full sentence is a change detector; check the prefix and the names in the message instead.
- Take expected values from the spec, the skill's text or a worked example, never by recomputing them the way the
  code does.
- Pick one case per distinct rule. Spelling variants of one model name, the same branch on every harness, every way
  to write the same argument: one representative each.
- Test the inputs real callers send. The script's entry point validates; test it there, and trust the code behind it.
- Fake only what the repo doesn't control: `gh`, `admiral`, the harness CLIs, `tmux`, the network, the clock. Run the
  repo's own scripts for real.
- Wait on a condition (a file, a process state), never on a fixed sleep. A script that waits takes its interval from
  the environment, so the test can set it to zero.
- A red test describes the behavior it expects. Once the code exists, the test file's docstring is one line, with no
  interface it assumed, issue number, unit id or commit hash.

## Running the tests

The test helpers are imported as top-level modules, so run each directory on its own, from the repo root:

```bash
for d in evals/*/; do python3 -m unittest discover -s "$d" -t "$d" -p 'test_*.py' || exit 1; done
```

While you work on one file, run only that file: `python3 -m unittest discover -s evals/<skill> -t evals/<skill> -p 'test_<name>.py'`.
The scripts are zsh and run on macOS; keep them portable to Linux (`zstat`, not `stat -f`).
