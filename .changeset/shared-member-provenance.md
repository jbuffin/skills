---
"jasonbuffin-skills": minor
---

Commodore's crew resolver now reads the provenance sidecar (`<member>.shared.json`) Admiral writes beside a shared member. `crew.py resolve` gives every member a `shared` field (`null`, or the owner, repo, commit, tag and whether the member was edited here), a bad sidecar warns `shared-unreadable` without failing the member, and `crew.py cast` shows `fleet (shared by owner/repo@abc1234)` in the Source column. The schema is documented in `references/crew-members.md`.
