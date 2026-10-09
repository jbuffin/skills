#!/usr/bin/env python3
"""Check that every relative Markdown link in the repo points at a file or directory that exists.

usage: check-links.py [root]

Skips URLs, in-page anchors, placeholder targets like <path>, and anything inside fenced code blocks.
Prints one line per broken link and exits 1 if there are any.
"""

import re
import subprocess
import sys
from pathlib import Path

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def tracked_markdown(root: Path) -> list[Path]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "*.md"], capture_output=True, text=True, check=True)
    return [root / line for line in out.stdout.splitlines() if line]


def broken_links(path: Path) -> list[str]:
    problems = []
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for target in LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#") or "<" in target:
                continue
            file_part = target.split("#", 1)[0]
            if file_part and not (path.parent / file_part).exists():
                problems.append(f"{path}:{number}: broken link {target}")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    problems = [problem for path in tracked_markdown(root) for problem in broken_links(path)]
    for problem in problems:
        print(problem.replace(f"{root}/", ""))
    if problems:
        return 1
    print("ok: all relative links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
