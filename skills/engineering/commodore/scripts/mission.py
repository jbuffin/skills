#!/usr/bin/env python3
"""List and validate Markdown mission files, read as text only (references/mission-files.md)."""

import json
import os
import sys
from pathlib import Path

from crew import ROLES, Unreadable, is_slug, member_files, parse_member

MAX_BYTES = 65536
KNOWN_FIELDS = ["name", "pick-me-when", "source-of-truth", "task-force", "builder", "checker", "stop-rule", "delivery"]
ENGINEER = "engineer"
USAGE = (
    "usage: mission.py list [--dir <dir>]\n"
    "       mission.py validate <file> [<file> ...]\n"
    "list reads every .md file directly in <dir>, by default the missions directory next to the scripts.\n"
)


class UsageError(Exception):
    pass


def usage_error(message):
    sys.stderr.write(f"mission.py: {message}\n{USAGE}")
    return 5


def blank(value):
    return value is None or (isinstance(value, str) and not value.strip(" \t"))


def required_string(fields, key):
    value = fields.get(key)
    if blank(value):
        raise Unreadable("missing-field", key, f"{key} is required")
    if not isinstance(value, str):
        raise Unreadable("bad-field", key, f"{key} must be a string")


def check_task_force(fields):
    force = fields.get("task-force")
    if force is None:
        raise Unreadable("missing-field", "task-force", "task-force is required")
    if not isinstance(force, list) or not force:
        raise Unreadable("bad-field", "task-force", "task-force must be a list of roles")
    if len(set(force)) != len(force):
        raise Unreadable("bad-field", "task-force", "task-force names a role twice")
    for role in force:
        if role not in ROLES:
            raise Unreadable("bad-field", "task-force", f"task-force item {role!r} is not one of the nine roles")
    return force


def check_builder(fields, force):
    builder = fields.get("builder")
    if blank(builder):
        raise Unreadable("missing-field", "builder", "builder is required")
    if not isinstance(builder, str) or builder not in force:
        raise Unreadable("bad-field", "builder", "builder must be a role in task-force")
    return builder


def check_checker(fields, force, builder):
    checker = fields.get("checker")
    if blank(checker):
        raise Unreadable("no-checker", "checker", "a mission needs a checker")
    if not isinstance(checker, str) or (checker != ENGINEER and checker not in force):
        raise Unreadable("bad-field", "checker", f"checker must be a role in task-force or {ENGINEER}")
    if checker == builder:
        raise Unreadable("checker-is-builder", "checker", "the checker can't be the builder")


def check_fields(fields, stem):
    """Apply the field table in order; raise Unreadable on the first error."""
    name = fields.get("name")
    if blank(name):
        raise Unreadable("missing-field", "name", "name is required")
    if not is_slug(name):
        raise Unreadable("bad-name", "name", "name must be a lowercase slug of at most 64 characters")
    if name != stem:
        raise Unreadable("name-mismatch", "name", f"name {name} does not match the file name {stem}")
    required_string(fields, "pick-me-when")
    required_string(fields, "source-of-truth")
    force = check_task_force(fields)
    builder = check_builder(fields, force)
    check_checker(fields, force, builder)
    required_string(fields, "stop-rule")
    required_string(fields, "delivery")


def read_mission(path, filename, layer_real=None):
    """Return (mission, warnings) for one file; raise Unreadable. `layer_real` turns on the outside-layer check."""
    try:
        if os.stat(path).st_size > MAX_BYTES:
            raise Unreadable("too-large", None, f"file is over {MAX_BYTES} bytes")
        if layer_real is not None and os.path.commonpath([os.path.realpath(path), layer_real]) != layer_real:
            raise Unreadable("outside-layer", None, "file resolves outside its directory")
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as err:
        raise Unreadable("unreadable", None, f"file can't be read: {err.strerror or err}") from None
    fields, body = parse_member(raw)
    check_fields(fields, filename[: -len(".md")])
    if not body:
        raise Unreadable("missing-field", "body", "the procedure after the frontmatter is empty")
    mission = {key: fields[key] for key in KNOWN_FIELDS}
    mission["file"], mission["procedure"] = filename, body
    warnings = [
        {"file": filename, "code": "unknown-field", "field": key, "message": f"unknown field {key}, ignored"}
        for key in fields
        if key not in KNOWN_FIELDS
    ]
    return mission, warnings


def order(item):
    return (
        item["file"] is not None,
        (item["file"] or "").encode("utf-8"),
        item["code"],
        item["field"] is not None,
        item["field"] or "",
        item["message"],
    )


def issue(filename, err):
    return {"file": filename, "code": err.code, "field": err.field, "message": err.message}


def read_all(entries):
    """(missions, errors, warnings) from (path, file name, layer real path or None) entries."""
    missions, errors, warnings = [], [], []
    for path, filename, layer_real in entries:
        try:
            mission, found = read_mission(path, filename, layer_real)
        except Unreadable as err:
            errors.append(issue(filename, err))
            continue
        missions.append(mission)
        warnings.extend(found)
    return sorted(missions, key=lambda m: m["name"]), sorted(errors, key=order), sorted(warnings, key=order)


def list_entries(directory):
    """(entries, errors) for the .md files directly in `directory`; a directory that can't be listed is one error."""
    try:
        os.listdir(directory)
        filenames = member_files(directory)
    except OSError as err:
        message = f"mission directory can't be listed: {err.strerror or err}"
        return [], [{"file": None, "code": "unreadable", "field": None, "message": message}]
    layer_real = os.path.realpath(directory)
    return [(os.path.join(directory, name), name, layer_real) for name in filenames], []


def emit(missions, errors, warnings):
    result = {"errors": errors, "warnings": []} if errors else {"missions": missions, "warnings": warnings}
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return 1 if errors else 0


def parse_list_args(argv):
    directory, args = None, iter(argv)
    for arg in args:
        if arg != "--dir":
            raise UsageError(f"unknown argument {arg}")
        if directory is not None:
            raise UsageError("--dir given twice")
        directory = next(args, "")
        if directory == "":
            raise UsageError("--dir needs a directory")
    return directory


def list_main(argv):
    try:
        directory = parse_list_args(argv)
    except UsageError as err:
        return usage_error(str(err))
    if directory is None:
        directory = str(Path(os.path.realpath(__file__)).parent.parent / "missions")
    entries, errors = list_entries(directory)
    missions, found, warnings = read_all(entries)
    return emit(missions, errors + found, warnings)


def validate_main(argv):
    if not argv or any(arg.startswith("-") for arg in argv):
        return usage_error("validate needs one or more files and takes no flags")
    entries = [(path, os.path.basename(path), None) for path in argv]
    return emit(*read_all(entries))


def main(argv):
    if argv and argv[0] == "list":
        return list_main(argv[1:])
    if argv and argv[0] == "validate":
        return validate_main(argv[1:])
    return usage_error("expected the list or validate subcommand")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
