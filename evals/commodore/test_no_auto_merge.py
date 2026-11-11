"""Nothing in Commodore merges, and `ADMIRAL_LOW_STAKES` has no `never` value (issue #200, ADR 0009).

The seam is a text walk over every file under `skills/engineering/commodore/`. A line fails when it mentions
`merge --auto`, `auto-merge`, `auto_merge`, `ADMIRAL_AUTO_MERGE`, or `ADMIRAL_LOW_STAKES` together with `never`. This
file lives under `evals/`, so its own patterns never trip the walk; a test proves it stays out of that tree.

Run from the repo root: python3 -m unittest evals/commodore/test_no_auto_merge.py -v
"""

import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TREE = REPO / "skills" / "engineering" / "commodore"

BANNED = re.compile(r"merge --auto|auto-merge|auto_merge|ADMIRAL_AUTO_MERGE", re.IGNORECASE)
LOW_STAKES_NEVER = re.compile(r"ADMIRAL_LOW_STAKES.*\bnever\b|\bnever\b.*ADMIRAL_LOW_STAKES")

# Exact lines (stripped) that may match. Keep this empty unless a line has a real reason.
ALLOWED = frozenset()


def offending_lines():
    found = []
    for path in sorted(p for p in TREE.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if (BANNED.search(line) or LOW_STAKES_NEVER.search(line)) and line.strip() not in ALLOWED:
                found.append(f"{path.relative_to(REPO)}:{n}: {line.strip()[:100]}")
    return found


class NoAutoMerge(unittest.TestCase):
    def test_no_line_mentions_auto_merge_or_low_stakes_never(self):
        self.assertEqual(offending_lines(), [])

    def test_this_eval_is_not_under_the_commodore_tree(self):
        self.assertFalse(Path(__file__).resolve().is_relative_to(TREE))

    def test_the_tree_is_found_and_not_empty(self):
        self.assertTrue((TREE / "SKILL.md").is_file())

    def test_the_allowance_list_stays_short(self):
        self.assertLessEqual(len(ALLOWED), 2)


if __name__ == "__main__":
    unittest.main()
