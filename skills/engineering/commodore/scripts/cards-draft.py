#!/usr/bin/env python3
"""Turn a triager's report into a `findings` inbox item draft.

usage: cards-draft.py <report.md> <out-draft.json> <pr-url> <id> <title> <items.md>

The report must hold exactly one fenced `json` block (the info string is case-insensitive, and the fence starts at
column 0): the cards array (references/finding-cards.md). Other fences are ignored. The report is untrusted data:
this script only parses the block as strict JSON (a duplicate key is an error) and never evaluates anything. items.md
is the triage item list; each item's line starts with its ID (`t1`, `r1`, `c1`, `ci1`), optionally behind a list
marker, a table `|` or backticks, and holds the item's link (the first https URL on the line). The cards must be
objects whose string ids are unique and equal the items' ids in items.md's order. A `t` card's first `evidence` entry
is the item's link. A `rerun` proposal is allowed only on a `ci` card, with the item's link as its content. The
finished draft must pass admiral-inbox-item.schema.json. The draft is `version` 1, `kind` `findings`, `id`, `created`
now, `title` and `findings.{pr_url, cards}`.

Exit 0 with the draft written. Exit 1 with nothing written when the triager's report is wrong (no block, more than one,
not an array, a bad card, or a card the rules above or the schema refuse): send the triager back. Exit 2 with nothing
written when the coordinator or the environment is wrong (an unreadable or non-UTF-8 file, no item ids in items.md, a
bad id, pr-url or title argument, a write error): never send the triager back. Exit 5 on usage.
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


ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
ITEM_RE = re.compile(r"^[ \t]*(?:[-*|][ \t]+)?`?((?:ci|t|r|c)[0-9]+)\b(.*)$", re.M)
LINK_RE = re.compile(r"https://[^\s|)>\]]+")


class Refused(Exception):
    """The triager's report is wrong; the triager must redo it."""


class CannotRun(Exception):
    """The coordinator's input or the environment is wrong; the triager can't fix it."""


def no_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate key {key!r}")
        obj[key] = value
    return obj


def cards(report):
    blocks = re.findall(r"^```json[ \t]*\n(.*?)^```[ \t]*$", report, re.M | re.S | re.I)
    if len(blocks) != 1:
        raise Refused(f"expected exactly one json block in the report, found {len(blocks)}")
    try:
        found = json.loads(blocks[0], object_pairs_hook=no_duplicates)
    except ValueError as e:
        raise Refused(f"the json block isn't valid JSON: {e}") from e
    if not isinstance(found, list):
        raise Refused("the json block isn't an array of cards")
    return found


def items(text):
    """item id -> its link (None when the line has none), in items.md's order."""
    found = {}
    for item_id, rest in ITEM_RE.findall(text):
        link = LINK_RE.search(rest)
        found[item_id] = link.group(0) if link else None
    if not found:
        raise CannotRun("items.md holds no item ids")
    return found


def match(found, wanted):
    seen = []
    for card in found:
        if not isinstance(card, dict) or not isinstance(card.get("id"), str):
            raise Refused("every card must be an object with a string id")
        if card["id"] in seen:
            raise Refused(f"duplicate card id {card['id']}")
        seen.append(card["id"])
    unknown = [i for i in seen if i not in wanted]
    missing = [i for i in wanted if i not in seen]
    if unknown or missing:
        raise Refused(f"card ids differ from items.md: not items {unknown}, no card for {missing}")
    if seen != list(wanted):
        raise Refused(f"cards are out of order: items.md has {list(wanted)}, the report has {seen}")
    for card in found:
        link = wanted[card["id"]]
        proposal = card.get("proposal")
        kind = proposal.get("kind") if isinstance(proposal, dict) else None
        if kind == "rerun" and not (card["id"].startswith("ci") and link and proposal.get("content") == link):
            raise Refused(f"card {card['id']}: a rerun is only for a ci item, with that item's link as its content")
        evidence = card.get("evidence")
        if card["id"].startswith("t") and link and not (isinstance(evidence, list) and evidence[:1] == [link]):
            raise Refused(f"card {card['id']}: the first evidence entry must be the thread link {link}")


def write(draft, out):
    fd, tmp = tempfile.mkstemp(prefix=".cards-draft.", dir=os.path.dirname(os.path.abspath(out)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(draft, ensure_ascii=False) + "\n")
        done = subprocess.run([sys.executable, "-I", CHECK, SCHEMA, tmp], capture_output=True, text=True, check=False)
        if done.returncode == 1:
            raise Refused(f"the draft fails the item schema:\n{done.stderr.strip()}")
        if done.returncode != 0:
            raise CannotRun(done.stderr.strip())
        os.replace(tmp, out)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def main(argv):
    if len(argv) != 7:  # noqa: PLR2004
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 5
    report, out, pr_url, item_id, title, items_md = argv[1:]
    try:
        if not (ID_RE.match(item_id) and pr_url.startswith("https://") and title.strip() and "\n" not in title):
            raise CannotRun("the id, pr-url or title argument is bad")
        with open(report, encoding="utf-8") as f:
            found = cards(f.read())
        with open(items_md, encoding="utf-8") as f:
            match(found, items(f.read()))
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
    except (CannotRun, OSError, ValueError, RecursionError) as e:
        print(f"can't run: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
