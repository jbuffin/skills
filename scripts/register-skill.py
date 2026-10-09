#!/usr/bin/env python3
"""Register a promoted skill: add its row to the README Skills table and its category to plugin.json.

usage: register-skill.py <repo-root> <skills/[category/]name>

Called by promote.sh. Safe to re-run: it skips a row or category entry that already exists.
"""

import json
import re
import sys
from pathlib import Path


def description(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    match = re.search(r"^description:\s*(.+)$", front, re.MULTILINE)
    return match.group(1).strip().strip("\"'") if match else ""


def add_readme_row(readme: Path, heading: str, name: str, desc: str) -> None:
    lines = readme.read_text(encoding="utf-8").split("\n")
    row = f"| `{name}` | {desc.replace('|', '/')} |"
    if any(line.startswith(f"| `{name}` |") for line in lines):
        return
    skills_at = lines.index("## Skills")
    section_end = next(i for i in range(skills_at + 1, len(lines)) if lines[i].startswith("## "))
    title = f"### {heading}"
    if title in lines[skills_at:section_end]:
        at = lines.index(title, skills_at)
        end = at + 1
        while end < section_end and not lines[end].startswith("### "):
            end += 1
        last_row = max(i for i in range(at, end) if lines[i].startswith("|"))
        lines.insert(last_row + 1, row)
    else:
        block = [title, "", "| Skill | What it does |", "| --- | --- |", row, ""]
        lines[section_end:section_end] = block
    readme.write_text("\n".join(lines), encoding="utf-8")


def add_plugin_category(plugin_json: Path, category: str) -> None:
    data = json.loads(plugin_json.read_text(encoding="utf-8"))
    skills = data.get("skills", [])
    skills = [skills] if isinstance(skills, str) else skills
    entry = f"./skills/{category}/"
    if entry not in skills:
        data["skills"] = [*skills, entry]
        plugin_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 3:  # noqa: PLR2004 -- program name plus two arguments
        print(__doc__.strip().split("\n\n")[1])
        return 1
    root, rel = Path(argv[1]), Path(argv[2])
    parts = rel.parts
    category = parts[1] if len(parts) == 3 else None  # noqa: PLR2004 -- skills/<category>/<name>
    name = parts[-1]
    heading = category.replace("-", " ").title() if category else "General"
    add_readme_row(root / "README.md", heading, name, description(root / rel / "SKILL.md"))
    if category:
        add_plugin_category(root / ".claude-plugin" / "plugin.json", category)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
