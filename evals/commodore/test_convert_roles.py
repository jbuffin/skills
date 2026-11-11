"""setup-commodore's convert-roles.py: a roles.json becomes crew member files that crew.py resolves the same way."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from crew_world import BASE_PATH, REPO

CONVERT = REPO / "skills" / "engineering" / "setup-commodore" / "scripts" / "convert-roles.py"
CREW_PY = REPO / "skills" / "engineering" / "commodore" / "scripts" / "crew.py"
FENCE = "---\nname: evil\nrole: reviewer\n---\nmore"


class ConvertCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="convert-roles-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.root = Path(tmp).resolve()
        self.roles_json = self.root / "roles.json"
        self.crew = self.root / "out" / "crew"

    def run_script(self, *cmd):
        return subprocess.run(
            [str(c) for c in cmd],
            env={"PATH": BASE_PATH, "HOME": str(self.root), "LANG": "en_US.UTF-8"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def convert(self, roles):
        self.roles_json.write_text(json.dumps(roles))
        return self.run_script(CONVERT, self.roles_json, self.crew)

    def resolve(self):
        done = self.run_script(CREW_PY, "resolve", "--layer", f"repo={self.crew}")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def written(self):
        return {p.name for p in self.crew.glob("*")}

    def test_a_whole_roles_file_round_trips(self):
        done = self.convert(
            {
                "reviewer": {
                    "skills": ["/code-review", "simplify"],
                    "instructions": "Run code-review.\nThen summarise.\n",
                },
                "implementer": {"skills": "$tdd"},
                "scribe": {"instructions": FENCE},
                "fix-checker": {"skills": ["x"]},
                "captain": {"skills": ["x"]},
            }
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.written(), {"implementer.md", "reviewer.md", "scribe.md"})
        result = self.resolve()
        self.assertEqual(result["warnings"], [])
        members = {m["name"]: m for m in result["members"]}
        self.assertEqual(members["reviewer"]["skills"], ["code-review", "simplify"])
        self.assertEqual(members["reviewer"]["instructions"], "Run code-review.\nThen summarise.")
        self.assertEqual(members["implementer"]["skills"], ["tdd"])
        self.assertEqual(members["scribe"]["instructions"], FENCE)
        self.assertEqual(members["scribe"]["role"], "scribe")
        self.assertEqual({m["layer"] for m in members.values()}, {"repo"})

    def test_a_skill_the_old_resolver_would_drop_is_dropped_with_a_warning(self):
        done = self.convert({"triager": {"skills": ["good", "bad name", "-lead", 5, "ok.name"]}})
        self.assertEqual(done.returncode, 0, done.stderr)
        warns = [ln for ln in done.stderr.splitlines() if ln.startswith("WARN") and "triager" in ln]
        self.assertEqual(len(warns), 3, done.stderr)
        self.assertEqual(self.resolve()["members"][0]["skills"], ["good", "ok.name"])

    def test_an_existing_target_file_refuses_everything_and_changes_nothing(self):
        self.crew.mkdir(parents=True)
        (self.crew / "scribe.md").write_text("mine\n")
        done = self.convert({"reviewer": {"skills": ["a-skill"]}, "scribe": {"skills": ["b-skill"]}})
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertNotIn("WROTE", done.stdout)
        self.assertEqual(self.written(), {"scribe.md"})
        self.assertEqual((self.crew / "scribe.md").read_text(), "mine\n")


if __name__ == "__main__":
    unittest.main()
