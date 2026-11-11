#!/usr/bin/env python3
"""Resolve crew members: layered Markdown member files, read as text only.

    crew.py resolve [--admiral] [--layer <label>=<dir> ...]
    crew.py resolve --run <run-dir>

Prints one JSON object on stdout. Exit 0 with {"members", "warnings"}, exit 1 with {"errors", "warnings"},
exit 5 on a bad call. The rules are in references/crew-members.md. A member file is never run, sourced or imported.
"""

import json
import os
import re
import sys
from pathlib import Path

LAYERS = ["built-in", "fleet", "user-global", "repo", "run"]
ROLES = [
    "implementer",
    "test-writer",
    "reviewer",
    "security-reviewer",
    "brief-checker",
    "triager",
    "target-steward",
    "scribe",
    "fix-checker",
]
HARNESSES = ["claude", "codex", "copilot"]
KNOWN_FIELDS = {"name", "role", "pick-me-when", "model", "harness", "ad-hoc", "ad-hoc-run", "based-on", "skills"}
MAX_BYTES = 65536
MIN_QUOTED = 2
SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
KEY = re.compile(r"^([a-z][a-z0-9-]*):(.*)$")
ITEM = re.compile(r"^ +-( .*)?$")
SKILL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
USAGE = (
    "usage: crew.py resolve [--admiral] [--layer <label>=<dir> ...]\n"
    "       crew.py resolve --run <run-dir>\n"
    "labels: " + ", ".join(LAYERS) + "\n"
    "--admiral only selects which labels are allowed: fleet with it, user-global without it.\n"
)


class Unreadable(Exception):
    """The file can't be read as a member: becomes an error with `code`."""

    def __init__(self, code, field=None, message=""):
        super().__init__(message)
        self.code = code
        self.field = field
        self.message = message or code


def bad(message):
    return Unreadable("bad-frontmatter", None, message)


# ------------------------------------------------------------------------------------------------ frontmatter
def parse_quoted(text):
    """Parse a leading quoted scalar; return (string, rest after the closing quote)."""
    quote = text[0]
    out = []
    i = 1
    while i < len(text):
        c = text[i]
        if quote == '"' and c == "\\" and i + 1 < len(text) and text[i + 1] in '"\\':
            out.append(text[i + 1])
            i += 2
        elif quote == "'" and c == "'" and text[i + 1 : i + 2] == "'":
            out.append("'")
            i += 2
        elif c == quote:
            return "".join(out), text[i + 1 :]
        else:
            out.append(c)
            i += 1
    raise bad("unclosed quote")


def parse_scalar(text):
    text = text.strip(" \t")
    if text[:1] in ('"', "'"):
        value, rest = parse_quoted(text)
        if rest.strip(" \t"):
            raise bad("text after a closing quote")
        return value
    return text


def parse_item(text):
    """A list item: a plain or quoted scalar, never empty and never a nested list."""
    text = text.strip(" \t")
    if text == "":
        raise bad("empty list item")
    if text[0] == "[":
        raise bad("nested list")
    return parse_scalar(text)


def parse_flow_list(text):
    if not text.endswith("]"):
        raise bad("unclosed flow list")
    inner = text[1:-1]
    if not inner.strip(" \t"):
        return []
    items = []
    for piece in inner.split(","):
        item = parse_item(piece)
        if piece.strip(" \t")[:1] in ('"', "'") and re.search(r"[\[\]]", item):
            raise bad("quoted list item holds a bracket")
        items.append(item)
    return items


def parse_value(text):
    text = text.strip(" \t")
    if text == "":
        return None
    if text[0] == "[":
        return parse_flow_list(text)
    if text in ("true", "false"):
        return text == "true"
    return parse_scalar(text)


def parse_frontmatter(lines):
    fields = {}
    open_key = None  # the key directly above, while it holds no value yet or only block list items
    for line in lines:
        if line.strip(" \t") == "" or line.lstrip(" ").startswith("#"):
            continue
        if re.match(r" *\t", line):
            raise bad("tab in indentation")
        item = ITEM.match(line)
        if item:
            if open_key is None:
                raise bad("list item without an empty key above it")
            if fields[open_key] is None:
                fields[open_key] = []
            fields[open_key].append(parse_item(item.group(1) or ""))
            continue
        key = KEY.match(line)
        if not key:
            raise bad("not a key or a list item")
        name, rest = key.groups()
        if name in fields:
            raise bad(f"repeated key {name}")
        fields[name] = parse_value(rest)
        open_key = name if fields[name] is None else None
    return fields


def parse_member(raw):
    """Return (fields, instructions) from file bytes, or raise Unreadable."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise bad("not valid UTF-8") from None
    if text.startswith("\ufeff"):
        raise bad("starts with a byte order mark")
    lines = text.replace("\r\n", "\n").split("\n")
    if lines[0] != "---":
        raise bad("line 1 is not ---")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise bad("no closing ---") from None
    fields = parse_frontmatter(lines[1:end])
    body = lines[end + 1 :]
    while body and body[0].strip(" \t") == "":
        body.pop(0)
    while body and body[-1].strip(" \t") == "":
        body.pop()
    return fields, "\n".join(body)


# ------------------------------------------------------------------------------------------------ one member file
def is_slug(value):
    return isinstance(value, str) and SLUG.match(value) is not None


def check_fields(fields, stem):
    """Apply the field table in order; raise Unreadable on the first error."""
    name = fields.get("name")
    if name is None:
        raise Unreadable("missing-field", "name", "name is required")
    if not is_slug(name):
        raise Unreadable("bad-name", "name", "name must be a lowercase slug of at most 64 characters")
    if name != stem:
        raise Unreadable("name-mismatch", "name", f"name {name} does not match the file name {stem}")
    role = fields.get("role")
    if role is None:
        raise Unreadable("missing-field", "role", "role is required")
    if not is_slug(role):
        raise Unreadable("bad-field", "role", "role must be a lowercase slug")
    pick = fields.get("pick-me-when")
    if pick is None or (isinstance(pick, str) and not pick.strip(" \t")):
        raise Unreadable("missing-field", "pick-me-when", "pick-me-when is required")
    if not isinstance(pick, str):
        raise Unreadable("bad-field", "pick-me-when", "pick-me-when must be a string")
    check_optional_fields(fields)


def check_optional_fields(fields):
    model = fields.get("model")
    if model is not None and not isinstance(model, str):
        raise Unreadable("bad-field", "model", "model must be a string")
    harness = fields.get("harness")
    if harness is not None:
        if not isinstance(harness, str):
            raise Unreadable("bad-field", "harness", "harness must be a string")
        if harness not in HARNESSES:
            raise Unreadable("bad-harness", "harness", f"harness must be one of {', '.join(HARNESSES)}")
    if fields.get("ad-hoc") is not None and not isinstance(fields["ad-hoc"], bool):
        raise Unreadable("bad-field", "ad-hoc", "ad-hoc must be true or false")
    if fields.get("ad-hoc-run") is not None and not isinstance(fields["ad-hoc-run"], str):
        raise Unreadable("bad-field", "ad-hoc-run", "ad-hoc-run must be a string")
    skills = fields.get("skills")
    if skills is not None and not isinstance(skills, (str, list)):
        raise Unreadable("bad-field", "skills", "skills must be a list of strings or one string")


def clean_skills(skills, warn):
    if skills is None:
        skills = []
    elif isinstance(skills, str):
        skills = [skills]
    kept = []
    for skill in skills:
        cleaned = skill[1:] if skill[:1] in ("/", "$") else skill
        if not SKILL.match(cleaned):
            warn("bad-skill", "skills", f"skill {skill!r} is not a valid skill name, dropped")
        elif cleaned not in kept:
            kept.append(cleaned)
    return kept


def review_fields(fields, body):
    """Run the warning checks; return (warnings, kept skills, body, refused)."""
    warnings = []

    def warn(code, field, message):
        warnings.append({"code": code, "field": field, "message": message})

    for key in fields:
        if key not in KNOWN_FIELDS:
            warn("unknown-field", key, f"unknown field {key}, ignored")
    kept = clean_skills(fields.get("skills"), warn)
    role = fields["role"]
    based_on = fields.get("based-on")
    if role == "fix-checker":
        if kept:
            warn("fix-checker-skills", "skills", "the fix checker takes no role skills, dropped")
            kept = []
        if body:
            warn("fix-checker-instructions", None, "the fix checker takes no instructions, dropped")
            body = ""
    refused = False
    if role in ROLES:
        if based_on is not None:
            warn("bad-based-on", "based-on", "a built-in role takes no based-on, member refused")
            refused = True
    elif not (isinstance(based_on, str) and based_on in ROLES and based_on != "fix-checker"):
        warn("bad-based-on", "based-on", "a custom role needs based-on naming one of the roles but fix-checker")
        refused = True
    if fields.get("ad-hoc") is True:
        warn("misplaced-ad-hoc", "ad-hoc", "ad hoc members live only in ad-hoc/, member refused")
        refused = True
    return warnings, kept, body, refused


def read_member(path, layer_real, layer, stem):
    """Return (member, warnings, refused); raise Unreadable for an error."""
    try:
        if os.stat(path).st_size > MAX_BYTES:
            raise Unreadable("too-large", None, f"file is over {MAX_BYTES} bytes")
        real = os.path.realpath(path)
        if os.path.commonpath([real, layer_real]) != layer_real:
            raise Unreadable("outside-layer", None, "file resolves outside its layer directory")
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as err:
        raise Unreadable("unreadable", None, f"file can't be read: {err.strerror or err}") from None
    fields, body = parse_member(raw)
    check_fields(fields, stem)

    warnings, kept, body, refused = review_fields(fields, body)
    role = fields["role"]
    based_on = fields.get("based-on")
    member = {
        "name": fields["name"],
        "role": role,
        "based-on": based_on if isinstance(based_on, str) else None,
        "skills": kept,
        "model": fields.get("model"),
        "harness": fields.get("harness"),
        "pick-me-when": fields["pick-me-when"],
        "ad-hoc": fields.get("ad-hoc") is True,
        "ad-hoc-run": fields.get("ad-hoc-run"),
        "instructions": body,
        "layer": layer,
        "file": f"{stem}.md",
    }
    for item in warnings:
        item["layer"], item["file"] = layer, member["file"]
    return member, warnings, refused


# ------------------------------------------------------------------------------------------------ resolution
def usable_name(name):
    """A member file name: lowercase .md, not a dotfile, valid UTF-8."""
    if not name.endswith(".md") or name.startswith("."):
        return False
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def member_files(directory):
    """Sorted member file names. A missing directory is empty; one that can't be listed raises OSError."""
    try:
        names = os.listdir(directory)
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(
        (n for n in names if usable_name(n) and os.path.isfile(os.path.join(directory, n))),
        key=lambda n: n.encode("utf-8"),
    )


def resolve(layers):
    """layers: list of (label, dir) in layer order. Return (members, errors, warnings)."""
    standing, errors, warnings = {}, [], []
    for label, directory in layers:
        layer_real = os.path.realpath(directory)
        try:
            filenames = member_files(directory)
        except OSError as err:
            message = f"layer directory can't be listed: {err.strerror or err}"
            errors.append({"layer": label, "file": None, "code": "unreadable", "field": None, "message": message})
            continue
        for filename in filenames:
            path = os.path.join(directory, filename)
            stem = filename[: -len(".md")]
            try:
                member, found, refused = read_member(path, layer_real, label, stem)
            except Unreadable as err:
                errors.append(
                    {"layer": label, "file": filename, "code": err.code, "field": err.field, "message": err.message}
                )
                continue
            warnings.extend(found)
            earlier = standing.get(member["name"])
            if (
                earlier
                and not refused
                and (earlier["role"] != member["role"] or earlier["based-on"] != member["based-on"])
            ):
                field = "role" if earlier["role"] != member["role"] else "based-on"
                warnings.append(
                    {
                        "layer": label,
                        "file": filename,
                        "code": "role-change",
                        "field": field,
                        "message": f"{field} differs from the {earlier['layer']} member, member refused",
                    }
                )
                refused = True
            if not refused:
                standing[member["name"]] = member

    def order(item):
        return (
            LAYERS.index(item["layer"]),
            item["file"] is not None,
            (item["file"] or "").encode("utf-8"),
            item["code"],
            item["field"] is not None,
            item["field"] or "",
            item["message"],
        )

    members = sorted(standing.values(), key=lambda m: (m["role"], m["name"]))
    return members, sorted(errors, key=order), sorted(warnings, key=order)


# ------------------------------------------------------------------------------------------------ run mode
def read_team_env(run_dir):
    values = {}
    try:
        text = Path(run_dir, "team.env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        match = ENV_LINE.match(line.strip())
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= MIN_QUOTED and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def setting(name, team):
    """The environment's value when it sets the variable (even empty), else team.env's, else empty."""
    return os.environ[name] if name in os.environ else team.get(name, "")


def run_layers(run_dir):
    team = read_team_env(run_dir)
    inside = bool(setting("ADMIRAL_SHIP", team))
    layers = [("built-in", str(Path(os.path.realpath(__file__)).parent.parent / "crew"))]
    repo = team.get("REPO") or team.get("WORKTREE") or ""
    repo_crew = os.path.join(repo, ".commodore", "crew") if repo else ""
    if inside:
        layers += [
            ("fleet", setting("ADMIRAL_CREW_DIR", team)),
            ("repo", repo_crew),
            ("run", setting("ADMIRAL_RUN_CREW", team)),
        ]
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        layers += [
            ("user-global", os.path.join(xdg, "commodore", "crew")),
            ("repo", repo_crew),
            ("run", os.path.join(run_dir, "crew")),
        ]
    return [(label, path) for label, path in layers if path]


# ------------------------------------------------------------------------------------------------ command line
def usage_error(message):
    sys.stderr.write(f"crew.py: {message}\n{USAGE}")
    return 5


class UsageError(Exception):
    pass


def add_layer(explicit, spec):
    label, equals, path = spec.partition("=")
    if not equals:
        raise UsageError("--layer needs <label>=<dir>")
    if label not in LAYERS:
        raise UsageError(f"unknown layer {label}")
    if label in explicit:
        raise UsageError(f"layer {label} given twice")
    explicit[label] = path


def parse_args(argv):
    """Return (admiral, explicit {label: dir}, run dir or None); raise UsageError for a bad call."""
    admiral, explicit, run_dir = False, {}, None
    args = iter(argv)
    for arg in args:
        if arg == "--admiral":
            admiral = True
        elif arg == "--layer":
            add_layer(explicit, next(args, ""))
        elif arg == "--run":
            if run_dir is not None:
                raise UsageError("--run given twice")
            run_dir = next(args, "")
            if run_dir == "":
                raise UsageError("--run needs a run directory")
        else:
            raise UsageError(f"unknown argument {arg}")
    if run_dir is not None and (explicit or admiral):
        raise UsageError("--run can't be combined with --layer or --admiral")
    if admiral and "user-global" in explicit:
        raise UsageError("user-global is ignored inside Admiral")
    if not admiral and "fleet" in explicit:
        raise UsageError("fleet is only read inside Admiral (--admiral)")
    return admiral, explicit, run_dir


def main(argv):
    if not argv or argv[0] != "resolve":
        return usage_error("expected the resolve subcommand")
    try:
        _, explicit, run_dir = parse_args(argv[1:])
    except UsageError as err:
        return usage_error(str(err))
    if run_dir is not None:
        layers = run_layers(run_dir)
    else:
        layers = [(label, explicit[label]) for label in LAYERS if label in explicit]
    members, errors, warnings = resolve(layers)
    result = {"errors": errors, "warnings": warnings} if errors else {"members": members, "warnings": warnings}
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
