#!/usr/bin/env python3
r"""Check a JSON file against a JSON Schema (the draft 2020-12 keywords Commodore's Admiral schemas use).

usage: schema-check.py <schema.json> <instance.json> [--into <dir> | --to <file>]
       schema-check.py --json <file>

Exit 0 if the instance is valid; 1 if it is invalid or isn't JSON (one reason per line on stderr, each naming the
offending field by its path); 2 if the check can't run (unreadable or malformed schema, unreadable instance, a
schema keyword this script doesn't implement, or a failed publish). Stdlib only, because `jsonschema` isn't installed.

JSON is parsed strictly: a duplicate object key, NaN, Infinity and numbers that overflow to infinity are errors, so
every parser reads the same value. With --into <dir> a valid instance is published, re-serialised from the parsed
value, to <dir>/<its id>.json, and an existing entry there (file, directory or symlink) is an error. With --to <file> it
replaces <file>. Both go through a dot-prefixed temp file in the destination directory, and nothing is created for an
invalid instance. `--json <file>` only checks that the file is strict JSON (exit 0, else 1).

Implemented: type, required, properties, additionalProperties, items, enum, const, pattern, allOf, if/then/else, not,
and boolean schemas. Annotations ($schema, $id, $comment, title, description, default, examples) are ignored. Any other
keyword exits 2, naming it, wherever it sits in the schema, so a schema can't silently stop asserting.

Strings are matched with an unanchored search, as JSON Schema says. `$` means end of string only (as in ECMA 262),
not "before a trailing newline" as in Python, and \d and \w stay ASCII.
"""

import json
import math
import os
import re
import sys
import tempfile

SHOWN = 60
ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "default", "examples"}


class CannotCheck(Exception):
    pass


class Failed(Exception):
    """A result to report: the exit code, and the reasons as the message."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


TYPES = {
    "null": lambda v: v is None,
    "boolean": lambda v: isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, float) and v.is_integer()),
}


def same(a, b):
    """JSON equality: a boolean never equals a number, and 1 equals 1.0."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return False
    return a == b


def regex(pattern):
    # Rewrite each bare `$` (not an escaped one, not inside [...]) to \Z.
    ecma = re.sub(
        r"\\.|\[(?:\\.|[^\]\\])*\]|\$", lambda m: r"\Z" if m.group() == "$" else m.group(), pattern, flags=re.S
    )
    try:
        return re.compile(ecma, re.ASCII)
    except re.error as e:
        raise CannotCheck(f"invalid pattern {pattern!r}: {e}") from e


def short(value):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= SHOWN else text[: SHOWN - 3] + "..."


def kw_type(arg, value, path, _schema):
    names = arg if isinstance(arg, list) else [arg]
    for name in names:
        if name not in TYPES:
            raise CannotCheck(f"unknown type {name!r}")
    if any(TYPES[name](value) for name in names):
        return []
    return [f"{path or '(root)'}: {short(value)} is not of type {' or '.join(names)}"]


def kw_required(arg, value, path, _schema):
    if not isinstance(value, dict):
        return []
    return [f"{path or '(root)'}: missing required property '{name}'" for name in arg if name not in value]


def kw_properties(arg, value, path, _schema):
    if not isinstance(value, dict):
        return []
    return [e for name, sub in arg.items() if name in value for e in check(sub, value[name], f"{path}/{name}")]


def kw_additional(arg, value, path, schema):
    if not isinstance(value, dict):
        return []
    known = schema.get("properties", {})
    return [e for name in value if name not in known for e in check(arg, value[name], f"{path}/{name}")]


def kw_items(arg, value, path, _schema):
    if not isinstance(value, list):
        return []
    return [e for i, item in enumerate(value) for e in check(arg, item, f"{path}/{i}")]


def kw_enum(arg, value, path, _schema):
    if any(same(value, option) for option in arg):
        return []
    return [f"{path or '(root)'}: {short(value)} is not one of {short(arg)}"]


def kw_const(arg, value, path, _schema):
    return [] if same(value, arg) else [f"{path or '(root)'}: {short(value)} is not {short(arg)}"]


def kw_pattern(arg, value, path, _schema):
    if not isinstance(value, str) or regex(arg).search(value):
        return []
    return [f"{path or '(root)'}: {short(value)} doesn't match pattern {arg}"]


def kw_all_of(arg, value, path, _schema):
    return [e for sub in arg for e in check(sub, value, path)]


def kw_if(arg, value, path, schema):
    branch = "then" if not check(arg, value, path) else "else"
    return check(schema[branch], value, path) if branch in schema else []


def kw_not(arg, value, path, _schema):
    return [f"{path or '(root)'}: must not match {short(arg)}"] if not check(arg, value, path) else []


KEYWORDS = {
    "type": kw_type,
    "required": kw_required,
    "properties": kw_properties,
    "additionalProperties": kw_additional,
    "items": kw_items,
    "enum": kw_enum,
    "const": kw_const,
    "pattern": kw_pattern,
    "allOf": kw_all_of,
    "if": kw_if,
    "not": kw_not,
}
BRANCHES = {"then", "else"}


def check(schema, value, path=""):
    """Return the reasons `value` fails `schema`; empty if it passes."""
    if isinstance(schema, bool):
        return [] if schema else [f"{path or '(root)'}: not allowed"]
    errors = []
    for key, arg in schema.items():
        if key in KEYWORDS:
            errors += KEYWORDS[key](arg, value, path, schema)
    return errors


def children(key, arg):
    """The subschemas under one keyword."""
    if key == "properties":
        return list(arg.values())
    if key == "allOf":
        return list(arg)
    if key in {"additionalProperties", "items", "if", "not"} | BRANCHES:
        return [arg]
    return []


def strings(arg):
    return isinstance(arg, list) and all(isinstance(x, str) for x in arg)


ARGUMENTS = {
    "type": lambda a: isinstance(a, str) or strings(a),
    "required": strings,
    "properties": lambda a: isinstance(a, dict),
    "enum": lambda a: isinstance(a, list),
    "pattern": lambda a: isinstance(a, str),
    "allOf": lambda a: isinstance(a, list),
}


def vet(schema, where="#"):
    """Raise CannotCheck for anything in the schema this script wouldn't enforce."""
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise CannotCheck(f"{where}: a schema must be an object or a boolean")
    for key, arg in schema.items():
        if key in ANNOTATIONS:
            continue
        if key not in KEYWORDS and key not in BRANCHES:
            raise CannotCheck(f"unsupported schema keyword '{key}' at {where}")
        if key in ARGUMENTS and not ARGUMENTS[key](arg):
            raise CannotCheck(f"bad argument for '{key}' at {where}: {short(arg)}")
        if key == "pattern":
            regex(arg)
        for sub in children(key, arg):
            vet(sub, f"{where}/{key}")


def no_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate key {key!r}")
        obj[key] = value
    return obj


def refuse(name):
    raise ValueError(f"{name} isn't allowed in JSON")


def finite(text):
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"{text} is out of range")
    return number


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f, object_pairs_hook=no_duplicates, parse_constant=refuse, parse_float=finite)


def publish(instance, target, replace):
    """Write the value to target through a temp file next to it. Only replace may overwrite an existing file."""
    directory, name = os.path.split(target)
    if not name or name in {".", ".."}:
        raise CannotCheck(f"{target!r} has no file name")
    os.makedirs(directory or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{name}.tmp.", dir=directory or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(instance, ensure_ascii=False, allow_nan=False) + "\n")
        (os.replace if replace else os.link)(tmp, target)
    except OSError as e:
        raise CannotCheck(f"can't publish {target}: {e}") from e
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def destination(instance, mode, where):
    """(target, replace) for --into <dir> (<dir>/<id>.json, never replaced) or --to <file>."""
    if mode == "--to":
        return where, True
    name = instance.get("id") if isinstance(instance, dict) else None
    if not isinstance(name, str) or not name or "/" in name or name.startswith("."):
        raise CannotCheck("the instance has no usable id to name the file")
    return os.path.join(where, f"{name}.json"), False


def read(path, what):
    """Load a file, or raise Failed: 1 for an instance that isn't strict JSON, 2 for anything else that fails."""
    try:
        return load(path)
    except OSError as e:
        raise Failed(2, f"can't read {path}: {e}") from e
    except ValueError as e:
        raise Failed(1 if what == "instance" else 2, f"{path} isn't valid JSON: {e}") from e


def run(argv):
    if len(argv) == 3 and argv[1] == "--json":  # noqa: PLR2004
        read(argv[2], "instance")
        return
    if len(argv) not in {3, 5} or (len(argv) == 5 and argv[3] not in {"--into", "--to"}):  # noqa: PLR2004
        raise Failed(2, "usage: schema-check.py <schema.json> <instance.json> [--into <dir> | --to <file>]")
    schema = read(argv[1], "schema")
    vet(schema)
    instance = read(argv[2], "instance")
    errors = check(schema, instance)
    if errors:
        raise Failed(1, "\n".join(errors))
    if len(argv) == 5:  # noqa: PLR2004
        publish(instance, *destination(instance, argv[3], argv[4]))


def main(argv):
    try:
        run(argv)
        return 0
    except Failed as e:
        print(e, file=sys.stderr)
        return e.code
    except CannotCheck as e:
        print(f"can't check: {e}", file=sys.stderr)
    except Exception as e:
        print(f"can't check: {type(e).__name__}: {e}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
