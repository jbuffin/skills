#!/usr/bin/env bash
# A local repo with a docs folder and a checklist: no issue to build, no PR to review, no feedback to answer.
set -euo pipefail
git init -q .
mkdir -p docs
cat > CHECKLIST.md <<'CHECK'
# Docs checklist

1. Every page starts with a one-line summary.
2. Every command shown in a code block names the directory to run it from.
3. No page links to a page that doesn't exist.
4. Every page ends with a "Last reviewed" date.
CHECK
cat > docs/install.md <<'PAGE'
# Install

Install the tool.

```
make install
```
PAGE
printf '# Usage\n\nSee [the guide](guide.md) and [the FAQ](faq.md).\n\nLast reviewed: 2026-01-04\n' > docs/usage.md
printf '# Guide\n\nRun the tool from the repo root.\n\nLast reviewed: 2025-11-30\n' > docs/guide.md
git add .
git -c user.name=eval -c user.email=eval@example.com commit -q -m "Add docs and checklist"
