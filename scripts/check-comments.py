#!/usr/bin/env python3
"""Check the comments and docstrings in the repo's scripts against the comment rule in AGENTS.md."""

import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

DIRS = ("skills", "incubator", "scripts", "evals")
SKIP = ("fixtures/", "templates/", "node_modules/", ".claude/")
SHELL_SHEBANG = re.compile(r"^#!.*\b(?:sh|bash|zsh)\b")
DIRECTIVE = re.compile(r"\b(?:noqa|shellcheck|pragma)\b|\b(?:ruff|type|fmt):|-\*- coding")

TEXT_RULES = [
    ("issue", re.compile(r"(?<![\w$&{\[])#\d+\b|\b(?:issue|PR|pull request)s? #?\d+\b", re.I)),
    ("unit-id", re.compile(r"\bu\d+\b|\bac\d+\b|-unit\.md\b")),
    ("spec-ref", re.compile(r"§|\bspec sections?\b|\bsections? \d|\b(?:decision|ruling)s? \d+|\bAgent Brief\b")),
    ("commit-sha", re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")),
    (
        "history",
        re.compile(
            r"\b(?:used to|no longer|previously|formerly|was changed|we changed|before the change|fails today"
            r"|on main already|red until|stays red)\b",
            re.I,
        ),
    ),
    ("marker", re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b")),
]
DIVIDER = re.compile(r"^\s*(?:#|//)\s*[-=*#]{10,}")
SED_RANGE = re.compile(r"sed -n '?(\d+)(?:,(\d+))?p'?\s+\"?\$\{?(?:0|SELF|ZSH_ARGZERO)\b")
HEREDOC = re.compile(r"(?<![<\d])<<(-?)\s*['\"]?([A-Za-z_]\w*)")
MAX_BLOCK = 2


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", *DIRS], capture_output=True, text=True, check=True)
    files = []
    for rel in out.stdout.splitlines():
        if any(part in rel for part in SKIP):
            continue
        path = root / rel
        if path.suffix in (".py", ".sh", ".zsh", ".mjs"):
            files.append(path)
        elif not path.suffix and path.is_file():
            with path.open("rb") as fh:
                if SHELL_SHEBANG.match(fh.readline().decode("utf-8", "replace")):
                    files.append(path)
    return files


def text_problems(line: int, text: str) -> list[tuple[int, str, str]]:
    if DIRECTIVE.search(text):
        return []
    return [(line, rule, text.strip()) for rule, pattern in TEXT_RULES if pattern.search(text)]


def block_problems(lines: dict[int, str], header_allowed) -> list[tuple[int, str, str]]:
    """Check runs of full-line comments: the leading header against header_allowed, the rest against MAX_BLOCK."""
    problems = []
    blocks: list[list[int]] = []
    for number in sorted(lines):
        if blocks and number == blocks[-1][-1] + 1:
            blocks[-1].append(number)
        else:
            blocks.append([number])
    for block in blocks:
        counted = [n for n in block if not DIRECTIVE.search(lines[n])]
        if not counted:
            continue
        verdict = header_allowed(block) if header_allowed else None
        if verdict is None and len(counted) > MAX_BLOCK:
            problems.append((block[0], "block", f"{len(counted)} comment lines; keep to {MAX_BLOCK}"))
        elif verdict:
            problems.append((block[0], "header", verdict))
    return problems


def header_check(source_lines: list[str], code: str):
    """Return a check for the header block: the lines the script prints as usage, or 2 lines if it prints none."""
    first = 1
    while first <= len(source_lines) and (
        not source_lines[first - 1].strip() or (first == 1 and source_lines[0].startswith("#!"))
    ):
        first += 1
    ranges = [(int(a), int(b or a)) for a, b in SED_RANGE.findall(code)]

    def check(block: list[int]):
        if block[0] != first:
            return None
        if ranges:
            start, end = min(r[0] for r in ranges), max(r[1] for r in ranges)
            if (block[0], block[-1]) != (start, end):
                return f"header is lines {block[0]}-{block[-1]} but the script prints {start}-{end} as usage"
            return ""
        if len(block) > MAX_BLOCK:
            return f"{len(block)}-line header in a script that prints none of it; keep to {MAX_BLOCK}"
        return ""

    return check


def check_python(path: Path, source: str) -> list[tuple[int, str, str]]:
    problems = []
    source_lines = source.splitlines()
    full: dict[int, str] = {}
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        if row == 1 and tok.string.startswith("#!"):
            continue
        if DIVIDER.match(tok.string):
            problems.append((row, "divider", tok.string))
        problems += text_problems(row, tok.string[1:])
        if not source_lines[row - 1][:col].strip():
            full[row] = tok.string
    problems += block_problems(full, header_check(source_lines, ""))

    tree = ast.parse(source)
    uses_doc = "__doc__" in source
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node)
        if doc is None:
            continue
        row = node.body[0].lineno
        for offset, text in enumerate(doc.splitlines()):
            problems += text_problems(row + offset, text)
        if len(doc.splitlines()) > 1 and not (isinstance(node, ast.Module) and uses_doc):
            kind = "module" if isinstance(node, ast.Module) else "function or class"
            problems.append((row, "docstring", f"{kind} docstring is {len(doc.splitlines())} lines; keep to 1"))
    return sorted(set(problems))


def trailing_comment(code: str) -> int:
    for match in re.finditer(r"\s#\s", code):
        before = code[: match.start()]
        if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
            return match.start() + 1
    return -1


def check_lines(source: str, comment: str) -> list[tuple[int, str, str]]:
    """Check a shell or JavaScript file line by line, skipping heredoc bodies."""
    problems = []
    source_lines = source.splitlines()
    full: dict[int, str] = {}
    code_lines = []
    pending: list[tuple[str, str]] = []
    heredoc = None
    for number, line in enumerate(source_lines, 1):
        if heredoc:
            dash, word = heredoc
            if (line.lstrip("\t") if dash else line) == word:
                heredoc = pending.pop(0) if pending else None
            continue
        if number == 1 and line.startswith("#!"):
            continue
        stripped = line.lstrip()
        if stripped.startswith(comment):
            text = stripped[len(comment) :]
            full[number] = text
            if DIVIDER.match(line):
                problems.append((number, "divider", line.strip()))
            problems += text_problems(number, text)
            continue
        cut = trailing_comment(line) if comment == "#" else line.find(" // ")
        code = line if cut < 0 else line[:cut]
        if cut >= 0:
            problems += text_problems(number, line[cut:].lstrip(" /#"))
        code_lines.append(code)
        if comment == "#":
            pending += [(dash, word) for dash, word in HEREDOC.findall(code)]
            if pending:
                heredoc = pending.pop(0)
    problems += block_problems(full, header_check(source_lines, "\n".join(code_lines)))
    return sorted(set(problems))


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    failures = 0
    for path in tracked_files(root):
        source = path.read_text(encoding="utf-8")
        if path.suffix == ".py":
            problems = check_python(path, source)
        else:
            problems = check_lines(source, "//" if path.suffix == ".mjs" else "#")
        for line, rule, text in problems:
            print(f"{path.relative_to(root)}:{line}: {rule}: {text}")
        failures += len(problems)
    if failures:
        return 1
    print("ok: comments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
