---
"jasonbuffin-skills": patch
---

Teammates no longer run full test suites at the same time. agent-teammates' `evidence.sh` takes a team-wide lock while its command runs and logs how long it waited, and the teammate contract sends every full suite, type check and build through it. Commodore's test writer runs only its new tests, the implementer runs only the files it's changing until its proofs, and the profile caps each test command's workers. Two parallel Jest runs had used 10–15 GB and run an 18 GB Mac out of memory.
