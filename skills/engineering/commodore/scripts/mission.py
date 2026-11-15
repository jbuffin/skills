#!/usr/bin/env python3
"""List, validate and keep Markdown mission files, read as text only (references/mission-files.md)."""

import json
import os
import stat
import sys
from pathlib import Path

from crew import (
    ROLES,
    Refusal,
    Unreadable,
    create_file,
    inside_path,
    is_slug,
    make_directory,
    member_files,
    parse_member,
    read_team_env,
    real_target,
    setting,
)

MAX_BYTES = 65536
KNOWN_FIELDS = ["name", "pick-me-when", "source-of-truth", "task-force", "builder", "checker", "stop-rule", "delivery"]
ENGINEER = "engineer"
USAGE = (
    "usage: mission.py list [--dir <dir> | --repo-dir <dir>] [--summary]\n"
    "       mission.py validate <file> [<file> ...]\n"
    "       mission.py keep --run <run> --file <run>/missions/<name>.md --layer user-global|repo\n"
    "list reads every .md file directly in <dir>. Without --dir it resolves the built-in missions over the\n"
    "user-global (or fleet, inside Admiral) and repo layers; --repo-dir names the repo.\n"
    "--summary prints only each mission's name, pick-me-when, builder, checker, delivery and file.\n"
    "keep saves a run's validated ad hoc mission into a layer; it refuses inside Admiral and never overwrites.\n"
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


def read_regular(path):
    """The file's bytes; a non-regular file is unreadable, and one over MAX_BYTES is too-large."""
    # O_NONBLOCK so that opening a FIFO can't hang before fstat sees it.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Unreadable("unreadable", None, "file is not a regular file")
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise Unreadable("too-large", None, f"file is over {MAX_BYTES} bytes")
    return raw


def read_mission(path, filename, layer_real=None):
    """Return (mission, warnings) for one file; raise Unreadable. `layer_real` turns on the outside-layer check."""
    try:
        if layer_real is not None and os.path.commonpath([os.path.realpath(path), layer_real]) != layer_real:
            raise Unreadable("outside-layer", None, "file resolves outside its directory")
        raw = read_regular(path)
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


def list_entries(directory, required=True):
    """(entries, errors) for `directory`'s .md files; an unlistable (or, if `required`, missing) one is an error."""
    try:
        if required:
            os.listdir(directory)
        filenames = member_files(directory)
    except OSError as err:
        message = f"mission directory can't be listed: {err.strerror or err}"
        return [], [{"file": None, "code": "unreadable", "field": None, "message": message}]
    layer_real = os.path.realpath(directory)
    return [(os.path.join(directory, name), name, layer_real) for name in filenames], []


def emit(missions, errors, warnings):
    result = {"errors": errors, "warnings": warnings} if errors else {"missions": missions, "warnings": warnings}
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return 1 if errors else 0


SUMMARY_KEYS = ["name", "pick-me-when", "builder", "checker", "delivery", "file"]
LAYERS = ["built-in", "user-global", "fleet", "repo"]
BUILTIN_NAME = "builtin-name"


def parse_list_args(argv):
    directory, repo_dir, summary, args = None, None, False, iter(argv)
    for arg in args:
        if arg == "--summary":
            if summary:
                raise UsageError("--summary given twice")
            summary = True
            continue
        if arg not in ("--dir", "--repo-dir"):
            raise UsageError(f"unknown argument {arg}")
        value = next(args, "")
        if value == "":
            raise UsageError(f"{arg} needs a directory")
        if arg == "--dir":
            if directory is not None:
                raise UsageError("--dir given twice")
            directory = value
        else:
            if repo_dir is not None:
                raise UsageError("--repo-dir given twice")
            repo_dir = value
    if directory is not None and repo_dir is not None:
        raise UsageError("--dir and --repo-dir can't be combined")
    return directory, repo_dir, summary


def layer_dirs(repo_dir):
    """(label, directory, required) for each layer, in order; only the built-in layer is required."""
    layers = [("built-in", str(Path(os.path.realpath(__file__)).parent.parent / "missions"), True)]
    if os.environ.get("ADMIRAL_SHIP"):
        fleet = os.environ.get("ADMIRAL_MISSIONS_DIR")
        if fleet:
            layers.append(("fleet", fleet, False))
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        layers.append(("user-global", os.path.join(xdg, "commodore", "missions"), False))
    if repo_dir:
        layers.append(("repo", os.path.join(os.path.abspath(repo_dir), ".commodore", "missions"), False))
    return layers


def resolve_layers(repo_dir):
    """(missions, errors, warnings) over the layers. Saved missions add to the built-in ones and never replace them."""
    standing, all_errors, all_warnings, builtin_names = {}, [], [], set()
    for label, directory, required in layer_dirs(repo_dir):
        entries, errors = list_entries(directory, required)
        missions, found, warnings = read_all(entries)
        for mission in missions:
            mission["layer"], mission["path"] = label, os.path.join(directory, mission["file"])
            if label == "built-in":
                builtin_names.add(mission["name"])
            elif mission["name"] in builtin_names:
                message = f"name {mission['name']} is a built-in mission, so the saved file is ignored"
                warnings.append({"file": mission["file"], "code": BUILTIN_NAME, "field": None, "message": message})
                continue
            standing[mission["name"]] = mission
        for item in errors + found + warnings:
            item["layer"] = label
        all_errors += sorted(errors + found, key=order)
        all_warnings += sorted(warnings, key=order)
    # Each layer's items are already sorted, so a stable sort by layer keeps the per-layer order.
    rank = {label: index for index, label in enumerate(LAYERS)}
    return (
        sorted(standing.values(), key=lambda m: m["name"]),
        sorted(all_errors, key=lambda e: rank[e["layer"]]),
        sorted(all_warnings, key=lambda w: rank[w["layer"]]),
    )


def list_main(argv):
    try:
        directory, repo_dir, summary = parse_list_args(argv)
    except UsageError as err:
        return usage_error(str(err))
    keys = SUMMARY_KEYS
    if directory is None:
        missions, errors, warnings = resolve_layers(repo_dir)
        keys = [*SUMMARY_KEYS, "layer", "path"]
    else:
        entries, listing = list_entries(directory)
        missions, found, warnings = read_all(entries)
        errors = listing + found
    if summary:
        missions = [{key: mission[key] for key in keys} for mission in missions]
    return emit(missions, errors, warnings)


def validate_main(argv):
    if not argv or any(arg.startswith("-") for arg in argv):
        return usage_error("validate needs one or more files and takes no flags")
    entries = [(path, os.fsencode(os.path.basename(path)).decode("utf-8", "replace"), None) for path in argv]
    return emit(*read_all(entries))


def parse_keep_args(argv):
    values, args = {}, iter(argv)
    for arg in args:
        if arg not in ("--run", "--file", "--layer"):
            raise UsageError(f"unknown argument {arg}")
        if arg in values:
            raise UsageError(f"{arg} given twice")
        values[arg] = next(args, "")
        if values[arg] == "":
            raise UsageError(f"{arg} needs a value")
    for flag in ("--run", "--file", "--layer"):
        if flag not in values:
            raise UsageError(f"keep needs {flag}")
    if values["--layer"] not in ("user-global", "repo"):
        raise UsageError("--layer must be user-global or repo")
    return values["--run"], values["--file"], values["--layer"]


def keep_source(run_dir, path):
    """The mission file's text once it is inside <run>/missions/, regular and valid; raise Refusal otherwise."""
    missions = os.path.realpath(os.path.join(run_dir, "missions"))
    real = os.path.realpath(path)
    if real == missions or not inside_path(real, missions):
        raise Refusal(f"{path} is not a file in {missions}")
    entries = [(path, os.path.basename(path), None)]
    found, errors, _ = read_all(entries)
    if errors:
        raise Refusal(f"{path} is not a valid mission: {errors[0]['message']}")
    try:
        return read_regular(path).decode("utf-8"), found[0]["name"]
    except (OSError, Unreadable, UnicodeDecodeError) as err:
        raise Refusal(f"{path} can't be read as a mission file: {err}") from None


def keep_problem(directory, links, forbidden, inside_only):
    """Why the layer directory can't be written, or None. Run before and after the directory is created."""
    for link in links:
        if os.path.islink(link):
            return f"{link} is a symlink"
    real = real_target(directory)
    if inside_only is not None:
        if not inside_path(real, os.path.realpath(inside_only)):
            return f"{directory} is not inside {inside_only}"
        return None
    for root in forbidden:
        if inside_path(real, os.path.realpath(root)):
            return f"{directory} is inside {root}"
    if ".commodore" in real.split(os.sep):
        return f"{directory} is inside a .commodore directory"
    return None


def keep_target(team, layer):
    """(directory, symlink-checked paths, directories it may not be in, directory it must be in or None)."""
    repo, worktree = team.get("REPO", ""), team.get("WORKTREE", "")
    if layer == "repo":
        if not repo:
            raise Refusal("team.env has no REPO")
        top = os.path.join(repo, ".commodore")
        directory = os.path.join(top, "missions")
        return directory, [top, directory], [], repo
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    top = os.path.join(xdg, "commodore")
    directory = os.path.join(top, "missions")
    return directory, [top, directory], [root for root in (repo, worktree) if root], None


def keep_main(argv):
    try:
        run_dir, path, layer = parse_keep_args(argv)
    except UsageError as err:
        return usage_error(str(err))
    try:
        team = read_team_env(run_dir)
        if setting("ADMIRAL_SHIP", team):
            raise Refusal("inside Admiral a mission goes in the Admiral report, not a layer")
        text, name = keep_source(run_dir, path)
        builtin = layer_dirs(None)[0][1]
        if os.path.lexists(os.path.join(builtin, f"{name}.md")):
            raise Refusal(f"{name} is a built-in mission")
        directory, links, forbidden, inside_only = keep_target(team, layer)
        problem = keep_problem(directory, links, forbidden, inside_only)
        if problem:
            raise Refusal(problem)
        if os.path.lexists(os.path.join(directory, f"{name}.md")):
            raise Refusal(f"the {layer} layer already holds {name}")
        make_directory(directory)
        problem = keep_problem(directory, links, forbidden, inside_only)
        if problem:
            raise Refusal(problem)
        sys.stdout.write(f"wrote {create_file(directory, name, text)}\n")
    except Refusal as err:
        sys.stdout.write(f"ERROR {err}\n")
        return 1
    return 0


def main(argv):
    if argv and argv[0] == "keep":
        return keep_main(argv[1:])
    if argv and argv[0] == "list":
        return list_main(argv[1:])
    if argv and argv[0] == "validate":
        return validate_main(argv[1:])
    return usage_error("expected the list or validate subcommand")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
