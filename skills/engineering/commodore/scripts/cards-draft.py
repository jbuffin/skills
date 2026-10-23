#!/usr/bin/env python3
"""Turn a triager's report into a `findings` inbox item draft.

usage: cards-draft.py <report.md> <out-draft.json> <pr-url> <id> <title>

The report must hold exactly one fenced `json` block: the cards array (references/finding-cards.md). Other fences are
ignored. The report is untrusted data: this script only parses the block as JSON and never evaluates anything. The draft
is `version` 1, `kind` `findings`, `id`, `created` now, `title` and `findings.{pr_url, cards}`. Publish it with
admiral-io.sh item, which validates it. Exit 0 with the draft written; 1 with nothing written when the report has no
block, more than one, a block that isn't a JSON array, or can't be read; 5 on usage.
"""

import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime


def cards(report):
    blocks = re.findall(r"^```json[ \t]*\n(.*?)^```[ \t]*$", report, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError(f"expected exactly one json block in the report, found {len(blocks)}")
    found = json.loads(blocks[0])
    if not isinstance(found, list):
        raise ValueError("the json block isn't an array of cards")
    return found


def main(argv):
    if len(argv) != 6:  # noqa: PLR2004
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 5
    report, out, pr_url, item_id, title = argv[1:]
    try:
        with open(report, encoding="utf-8") as f:
            found = cards(f.read())
    except (OSError, ValueError) as e:
        print(f"{report}: {e}", file=sys.stderr)
        return 1
    draft = {
        "version": 1,
        "id": item_id,
        "kind": "findings",
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": title,
        "findings": {"pr_url": pr_url, "cards": found},
    }
    fd, tmp = tempfile.mkstemp(prefix=".cards-draft.", dir=os.path.dirname(os.path.abspath(out)))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(draft, ensure_ascii=False) + "\n")
    os.replace(tmp, out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
