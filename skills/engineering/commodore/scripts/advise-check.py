#!/usr/bin/env python3
"""Check an advise draft's recommendation is one of its options, the rule its schema can't express."""

import importlib.util
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("schema_check", Path(__file__).with_name("schema-check.py"))
schema_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schema_check)


def main(argv):
    if len(argv) != 2:  # noqa: PLR2004
        print("usage: advise-check.py <draft.json>", file=sys.stderr)
        return 2
    try:
        draft = schema_check.load(argv[1])
    except (OSError, ValueError) as e:
        print(f"can't check: {e}", file=sys.stderr)
        return 2
    if isinstance(draft, dict) and draft.get("recommendation") not in draft.get("options", []):
        print("/recommendation: isn't one of the options", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
