---
"jasonbuffin-skills": minor
---

Commodore gains crew members: Markdown member files layered as built-in, fleet, user-global, repo and run. The nine built-in members ship in `crew/`, and `scripts/crew.py resolve` reads the layers as text (python3 stdlib, never running or sourcing a file) and prints the resolved members, errors and warnings as JSON. Shared cases for the resolver live in `fixtures/crew-resolution/`.
