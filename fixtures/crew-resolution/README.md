# Crew resolution fixtures

Language-neutral cases for the crew member resolver. Commodore's resolver (`skills/engineering/commodore/scripts/crew.py`) and Admiral's Go resolver (admiral#296) both run every case, so the layer rules stay in step. The rules themselves are in `skills/engineering/commodore/references/crew-members.md`.

## Case layout

Each directory under `cases/` is one case:

- `case.json`: `{"description": "...", "admiral": true|false}`. `admiral` says whether the case runs inside an Admiral ship.
- `layers/<label>/`: the layer directories that exist for the case, named by layer label: `built-in`, `fleet`, `user-global`, `repo`, `run`. A label with no directory is an empty layer. The built-in layer is a small made-up set, not a copy of the shipped `crew/` directory.
- `expected.json`: the resolver's stdout object with every `message` removed, plus `"exit"` (the process exit code). Exit 0 has `members` and `warnings`. Exit 1 has `errors` and `warnings`.

Run a case by mapping each `layers/<label>/` directory onto its layer. In Commodore's resolver that is `crew.py resolve [--admiral] --layer <label>=<dir> ...`. In Admiral, the layers map to these inputs:

- `fleet`: `ADMIRAL_CREW_DIR`, the fleet crew directory. Its `ad-hoc/` subdirectory holds ad hoc members and is not read as a layer.
- `run`: `ADMIRAL_RUN_CREW`, the run layer directory Admiral writes pins to.
- `user-global`: `${XDG_CONFIG_HOME:-~/.config}/commodore/crew/`, read only outside Admiral.
- `repo`: `<repo>/.commodore/crew/`.
- `built-in`: the built-in members the resolver ships with.

Inside Admiral (`admiral: true`) the `user-global` layer is ignored. Outside it (`admiral: false`) the `fleet` layer is ignored. Some cases put a member in the ignored layer on purpose, so a resolver handed an ignored layer's directory must ignore it. Commodore's explicit `--layer` mode rejects an ignored label with exit 5, so its eval leaves those directories out there and covers them through `--run`.

## Comparing results

Parse both JSON objects, drop every `message` field from your output's `errors` and `warnings`, then compare the structures and the exit code. Don't compare bytes: whitespace, key order and message text are free to differ.

## Symlinks

Some cases hold committed git symlinks (for example `error-outside-layer`). Check out or copy a case with symlinks kept, or those cases give the wrong result.

## Generated inputs

Inputs that can't be committed safely aren't fixtures: non-UTF-8 content, a byte order mark and CRLF line endings. `evals/commodore/test_crew_resolution.py` generates those files at run time. Cover them in your own tests.

## Markdown lint

`cases/.markdownlint-cli2.jsonc` turns markdownlint off under `cases/`, because the error cases hold invalid frontmatter on purpose. This README is still linted.
