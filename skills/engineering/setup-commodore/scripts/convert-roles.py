#!/usr/bin/env python3
"""Convert a legacy roles.json into crew member files, never changing or deleting roles.json."""

import json
import os
import re
import sys
from pathlib import Path

ROLES = [
    "implementer",
    "test-writer",
    "reviewer",
    "security-reviewer",
    "brief-checker",
    "triager",
    "target-steward",
    "scribe",
]
SKILL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*")
KEYS = {"skills", "instructions"}
MAX_BODY = 65536
USAGE_ARGS = 2


def warn(text):
    sys.stderr.write(f"WARN  {text}\n")


def refuse(text):
    sys.stderr.write(f"ERROR {text}\n")
    return 1


def entry_skills(role, value):
    """The bare skill names the old resolver kept, or None when the entry's skills are unusable."""
    if value is None or value is False:  # the old resolver read `skills // []`
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None
    kept = []
    for item in value:
        name = item[1:] if isinstance(item, str) and item[:1] in "/$" else item
        if not (isinstance(name, str) and SKILL.fullmatch(name)):
            warn(f"{role}: skill {json.dumps(item)} is not a skill name; dropped")
        elif name not in kept:
            kept.append(name)
    return kept


def trim_blank_lines(text):
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def member_file(role, skills, body, source):
    head = [f"name: {role}", f"role: {role}", f"pick-me-when: Converted from {source}."]
    if skills:
        head.append(f"skills: [{', '.join(skills)}]")
    elif skills is not None:
        head.append("skills: []")
    return "---\n" + "\n".join(head) + "\n---\n" + (f"\n{body}\n" if body else "")


def build(data, source):
    """Return {role: file text} for the entries worth writing, or an error message."""
    files = {}
    for role, entry in data.items():
        if role not in ROLES:
            warn(f"{role}: not a role that takes skills; skipped")
            continue
        if not isinstance(entry, dict):
            warn(f"{role}: the entry is not an object; skipped")
            continue
        for key in sorted(set(entry) - KEYS):
            warn(f"{role}: unknown key {json.dumps(key)} dropped")
        skills = None
        if "skills" in entry:
            skills = entry_skills(role, entry["skills"])
            if skills is None:
                warn(f"{role}: skills is neither a list nor a string; skipped")
                continue
        body = ""
        if entry.get("instructions") is not None:
            if isinstance(entry["instructions"], str):
                body = trim_blank_lines(entry["instructions"])
            else:
                warn(f"{role}: instructions is not a string; ignored")
        if len(body.encode("utf-8")) > MAX_BODY:
            return f"{role}: instructions are over {MAX_BODY} bytes"
        files[role] = member_file(role, skills, body, source)
    return files


def main(argv):  # noqa: PLR0911
    if len(argv) != USAGE_ARGS:
        sys.stderr.write("usage: convert-roles.py <roles.json> <crew-dir>\n")
        return 5
    roles_json, crew_dir = Path(argv[0]), Path(argv[1])
    source = f"{roles_json.resolve().parent.name}/roles.json"
    if "\n" in source or "\r" in source:
        return refuse(f"{roles_json} has a line break in its directory name")
    try:
        data = json.loads(roles_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return refuse(f"{roles_json} can't be read as JSON: {err}")
    if not isinstance(data, dict):
        return refuse(f"{roles_json} is not a JSON object")
    files = build(data, source)
    if isinstance(files, str):
        return refuse(files)
    if os.path.islink(crew_dir):
        return refuse(f"{crew_dir} is a symlink; nothing written")
    taken = [role for role in files if os.path.lexists(crew_dir / f"{role}.md")]  # a dangling symlink counts
    if taken:
        return refuse(f"{crew_dir / (taken[0] + '.md')} already exists; nothing written")
    if not files:
        return 0
    crew_dir.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    for role, text in files.items():
        target = crew_dir / f"{role}.md"
        with os.fdopen(os.open(target, flags, 0o644), "w", encoding="utf-8") as out:
            out.write(text)
        sys.stdout.write(f"WROTE {target}\n")
    sys.stdout.write(f"NEXT delete {roles_json} once the members resolve\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
