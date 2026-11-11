---
name: executable-body
role: scribe
pick-me-when: Pick $(touch crew-executed-marker).
---

#!/usr/bin/env python3
import os
os.system('touch crew-executed-marker')
$(touch crew-executed-marker)
`touch crew-executed-marker`
; echo not-a-command # text
