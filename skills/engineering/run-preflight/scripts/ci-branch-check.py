#!/usr/bin/env python3
r"""Check that a workflow's branch filters let PRs based on a given branch run.

usage: ci-branch-check.py <workflow.yml> <branch-name>

Exit 0 if a PR whose BASE is <branch-name> runs the workflow through pull_request or pull_request_target (a
trigger with no branch filter lets every PR run); exit 1 if the filters skip it; exit 2 if the workflow has no
pull_request trigger at all. Prints why. Stacked PRs target the branch below them, so a filter naming only the
trunk gives every PR above the bottom one no CI at all.
Reads both `branches:` and `branches-ignore:`, as block lists, flow lists, single values or a flow mapping on
the event's line. Uses PyYAML when it's installed, else a line parser. Understands GitHub's filter patterns:
* (no slash), ** (anything), ? (zero or one of the preceding character), + (one or more of it), [] (a character
class), \ (escape) and a leading ! (negation). Comments ignored. Runs on Python 3.9 and later.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

USAGE_EXIT = 5
MAX_EVENT_INDENT = 4
EVENT_RE = re.compile(r"^(\s*)(pull_request|pull_request_target|push)\s*:")
BRANCHES_RE = re.compile(r"^\s+(branches|branches-ignore)\s*:")
LIST_ITEM_RE = re.compile(r"^\s*-\s*(.+?)\s*$")
FLOW_FILTER_RE = re.compile(r"(branches-ignore|branches)\s*:\s*(\[[^\]]*\]|[^,}]+)")
ON_RE = re.compile(r"^['\"]?on['\"]?\s*:(.*)$")
PR_EVENTS = ("pull_request", "pull_request_target")
NO_PR_TRIGGER_EXIT = 2


def glob_re(pattern: str) -> re.Pattern[str]:
    """Translate a GitHub Actions branch filter pattern into a compiled regex."""
    atoms: list[str] = []  # one regex per pattern element, so ? and + can quantify the one before
    i = 0
    while i < len(pattern):
        c, step = pattern[i], 1
        end = pattern.find("]", i + 2) if c == "[" else -1
        if pattern.startswith("**", i):
            atoms.append(".*")
            step = 2
        elif c == "*":
            atoms.append("[^/]*")
        elif c in "?+" and atoms:
            atoms[-1] = f"(?:{atoms[-1]}){c}"
        elif end != -1:
            atoms.append("[" + pattern[i + 1 : end].replace("\\", "\\\\") + "]")
            step = end + 1 - i
        elif c == "\\" and i + 1 < len(pattern):
            atoms.append(re.escape(pattern[i + 1]))
            step = 2
        else:
            atoms.append(re.escape(c))
        i += step
    return re.compile("".join(atoms) + r"\Z")


def indent(line: str) -> int:
    """Return the number of leading whitespace characters."""
    return len(line) - len(line.lstrip())


def block_list(lines: list[str], start: int, parent_indent: int) -> list[str]:
    """Collect the YAML block-list items that follow a key at lines[start - 1]."""
    items = []
    for nxt in lines[start:]:
        if not nxt.strip():
            continue
        if indent(nxt) <= parent_indent and not nxt.lstrip().startswith("-"):
            break
        m = LIST_ITEM_RE.match(nxt)
        if not m:
            break
        items.append(m.group(1).strip("'\""))
    return items


def inline_patterns(value: str) -> list[str]:
    """Parse a flow list (`[a, b]`) or a single scalar into patterns."""
    value = value.strip()
    if value.startswith("["):
        return [x.strip().strip("'\"") for x in value.strip("[]").split(",") if x.strip()]
    return [value.strip("'\"")] if value else []


Filters = dict[str, "tuple[str, list[str]] | None"]  # event -> (kind, patterns), or None for no branch filter


def yaml_filters(text: str) -> Filters | None:
    """Read the filters with PyYAML, or return None when it isn't installed or can't parse the file."""
    try:
        import yaml  # noqa: PLC0415 -- optional dependency
    except ImportError:
        return None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict):
        return None
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` key as True
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return {str(event): None for event in on}
    filters: Filters = {}
    if isinstance(on, dict):
        for event, cfg in on.items():
            filters[str(event)] = None
            for kind in ("branches", "branches-ignore"):
                if isinstance(cfg, dict) and kind in cfg:
                    val = cfg[kind]
                    filters[str(event)] = (kind, [str(v) for v in val] if isinstance(val, list) else [str(val)])
    return filters


def branch_filters(text: str) -> Filters:
    """Map each trigger event to its filter kind (branches or branches-ignore) and patterns, or None if unfiltered."""
    parsed = yaml_filters(text)
    if parsed is not None:
        return parsed
    lines = [re.sub(r"(^|\s)#.*$", "", raw) for raw in text.splitlines()]
    filters: Filters = {}
    event, event_indent = None, -1
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        on = ON_RE.match(line)
        if on:  # on: pull_request / on: [push, pull_request] / on: followed by a block list of event names
            names = inline_patterns(on.group(1)) if on.group(1).strip() else block_list(lines, idx + 1, 0)
            filters.update({n: None for n in names if n in PR_EVENTS})
        # an event's block ends at the next key on its own indentation or shallower
        if event and indent(line) <= event_indent:
            event = None
        m = EVENT_RE.match(line)
        if m and len(m.group(1)) <= MAX_EVENT_INDENT:
            event, event_indent = m.group(2), len(m.group(1))
            filters.setdefault(event, None)
            rest = line.split(":", 1)[1].strip()
            if rest.startswith("{"):  # pull_request: {branches: [main]}
                f = FLOW_FILTER_RE.search(rest)
                if f:
                    filters[event] = (f.group(1), inline_patterns(f.group(2)))
                event = None
            continue
        b = BRANCHES_RE.match(line) if event else None
        if b:
            inline = line.split(":", 1)[1].strip()
            patterns = inline_patterns(inline) if inline else block_list(lines, idx + 1, indent(line))
            filters[event] = (b.group(1), patterns)
    return filters


def covers(kind: str, patterns: list[str], branch: str) -> bool:
    """Return whether a branches or branches-ignore filter lets a PR based on the branch run."""
    if kind == "branches-ignore":
        return not any(glob_re(p).match(branch) for p in patterns)
    ok = False
    for p in patterns:  # the last matching pattern wins, so a later ! pattern excludes again
        if glob_re(p.lstrip("!")).match(branch):
            ok = not p.startswith("!")
    return ok


def main(argv: list[str]) -> int:
    """Print whether PRs based on the branch get CI, and return the exit code."""
    if len(argv) != 3:  # noqa: PLR2004 -- program name plus two arguments
        print(__doc__.strip().split("\n\n")[1])
        return USAGE_EXIT
    path, branch = argv[1], argv[2]
    filters = branch_filters(Path(path).read_text())
    events = [e for e in PR_EVENTS if e in filters]
    if not events:
        print("no pull_request trigger: PRs get CI only if another trigger (such as push) covers their branches")
        return NO_PR_TRIGGER_EXIT
    for event in events:
        found = filters[event]
        if found is None:
            print(f"no {event} branch filter: every PR runs")
            return 0
        kind, patterns = found
        if covers(kind, patterns, branch):
            print(f"covered: PRs based on {branch} vs {event} {kind} {patterns}")
            return 0
    print(f"NOT covered: PRs based on {branch} vs " + "; ".join(f"{e} {filters[e][0]} {filters[e][1]}" for e in events))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
