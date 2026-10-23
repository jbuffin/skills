#!/usr/bin/env python3
"""Turn a triager's report into a `findings` inbox item draft.

usage: cards-draft.py <report.md> <out-draft.json> <pr-url> <id> <title> <items.md>

The report must hold exactly one fenced `json` block (the info string is case-insensitive, and the fence starts at
column 0): the cards array (references/finding-cards.md). Other fences are ignored. The report is untrusted data:
this script only parses the block as JSON and never evaluates anything. items.md is the triage item list; each
item's line starts with its ID (`t1`, `r1`, `c1`, `ci1`), optionally behind a list marker or backticks. The cards
must be objects whose string ids are unique, match the items' ids exactly and cover every item, and the finished
draft must pass admiral-inbox-item.schema.json. The draft is `version` 1, `kind` `findings`, `id`, `created` now,
`title` and `findings.{pr_url, cards}`.

Exit 0 with the draft written. Exit 1 with nothing written when the report is wrong (no block, more than one, not an
array, a bad card, a card id that isn't an item, an item with no card, or a draft the schema refuses): send the triager
back. Exit 2 when the script can't run (an unreadable file, a write error), as schema-check.py does. Exit 5 on usage.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "..", "references", "admiral-inbox-item.schema.json")
CHECK = os.path.join(HERE, "schema-check.py")


class Refused(Exception):
    """The report is wrong; the triager must redo it."""


def cards(report):
    blocks = re.findall(r"^```json[ \t]*\n(.*?)^```[ \t]*$", report, re.M | re.S | re.I)
    if len(blocks) != 1:
        raise Refused(f"expected exactly one json block in the report, found {len(blocks)}")
    try:
        found = json.loads(blocks[0])
    except ValueError as e:
        raise Refused(f"the json block isn't valid JSON: {e}") from e
    if not isinstance(found, list):
        raise Refused("the json block isn't an array of cards")
    return found


def item_ids(items):
    return re.findall(r"^[ \t]*(?:[-*][ \t]+)?`?((?:ci|t|r|c)[0-9]+)\b", items, re.M)


def match(found, ids):
    seen = []
    for card in found:
        if not isinstance(card, dict) or not isinstance(card.get("id"), str):
            raise Refused("every card must be an object with a string id")
        if card["id"] in seen:
            raise Refused(f"duplicate card id {card['id']}")
        seen.append(card["id"])
    unknown = [i for i in seen if i not in ids]
    missing = [i for i in ids if i not in seen]
    if unknown or missing:
        raise Refused(f"card ids differ from items.md: not items {unknown}, no card for {missing}")


def write(draft, out):
    fd, tmp = tempfile.mkstemp(prefix=".cards-draft.", dir=os.path.dirname(os.path.abspath(out)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(draft, ensure_ascii=False) + "\n")
        done = subprocess.run([sys.executable, "-I", CHECK, SCHEMA, tmp], capture_output=True, text=True, check=False)
        if done.returncode == 1:
            raise Refused(f"the draft fails the item schema:\n{done.stderr.strip()}")
        if done.returncode != 0:
            raise OSError(done.stderr.strip())
        os.replace(tmp, out)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def main(argv):
    if len(argv) != 7:  # noqa: PLR2004
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 5
    report, out, pr_url, item_id, title, items = argv[1:]
    try:
        with open(report, encoding="utf-8") as f:
            found = cards(f.read())
        with open(items, encoding="utf-8") as f:
            match(found, item_ids(f.read()))
        draft = {
            "version": 1,
            "id": item_id,
            "kind": "findings",
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "title": title,
            "findings": {"pr_url": pr_url, "cards": found},
        }
        write(draft, out)
    except Refused as e:
        print(f"{report}: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"can't run: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
