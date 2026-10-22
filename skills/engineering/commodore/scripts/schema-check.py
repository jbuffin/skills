#!/usr/bin/env python3
r"""Check a JSON file against a JSON Schema (the draft 2020-12 keywords Commodore's Admiral schemas use).

usage: schema-check.py <schema.json> <instance.json>

Exit 0 if the instance is valid; 1 if it is invalid or isn't JSON (one reason per line on stderr, each naming the
offending field by its path); 2 if the check can't run (unreadable or malformed schema, unreadable instance, or a
schema keyword this script doesn't implement). Stdlib only, because `jsonschema` isn't installed.

Implemented: type, required, properties, additionalProperties, items, enum, const, pattern, allOf, if/then/else, not,
and boolean schemas. Annotations ($schema, $id, $comment, title, description, default, examples) are ignored. Any other
keyword exits 2, naming it, wherever it sits in the schema, so a schema can't silently stop asserting.

Strings are matched with an unanchored search, as JSON Schema says. `$` means end of string only (as in ECMA 262),
not "before a trailing newline" as in Python, and \d and \w stay ASCII.
"""

import json
import re
import sys

SHOWN = 60
ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description", "default", "examples"}


class CannotCheck(Exception):
    pass


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
    try:
        return re.compile(re.sub(r"(?<!\\)\$", r"\\Z", pattern), re.ASCII)
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
        if key == "pattern":
            regex(arg)
        for sub in children(key, arg):
            vet(sub, f"{where}/{key}")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv):
    if len(argv) != 3:  # noqa: PLR2004
        print("usage: schema-check.py <schema.json> <instance.json>", file=sys.stderr)
        return 2
    try:
        schema = load(argv[1])
        vet(schema)
    except (OSError, ValueError, CannotCheck) as e:
        print(f"can't use schema {argv[1]}: {e}", file=sys.stderr)
        return 2
    try:
        instance = load(argv[2])
    except OSError as e:
        print(f"can't read {argv[2]}: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"{argv[2]} isn't valid JSON: {e}", file=sys.stderr)
        return 1
    errors = check(schema, instance)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
