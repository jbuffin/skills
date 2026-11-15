"""Tests for the built-in mission files: what `mission.py list` finds and what `validate.sh` enforces."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from crew_world import BASE_PATH

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MISSION_PY = REPO / "skills" / "engineering" / "commodore" / "scripts" / "mission.py"
BUILD_REL = Path("skills") / "engineering" / "commodore" / "missions" / "build.md"

BUILTIN = {
    "build": ("implementer", "reviewer"),
    "review": ("reviewer", "engineer"),
    "pr-feedback": ("implementer", "reviewer"),
}

NO_CHECKER = """---
name: build
pick-me-when: The engineer wants a change built.
source-of-truth: The issue's acceptance criteria.
task-force: [implementer, reviewer]
builder: implementer
stop-rule: The PR is open and CI is green.
delivery: A pull request.
---

## Phase 1

Read the issue.
"""


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    for entry in filter(None, out.split("\0")):
        meta, path = entry.split("\t", 1)
        yield meta.split()[0], path


def copy_tracked(dest):
    """Copy the tracked files without following symlinks, keeping executable bits."""
    for mode, rel in tracked_files():
        src, dst = REPO / rel, dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if mode == "120000":
            os.symlink(os.readlink(src), dst)
        else:
            shutil.copy2(src, dst)


class BuiltinMissionTests(unittest.TestCase):
    def test_list_with_no_dir_finds_exactly_the_built_in_missions(self):
        tmp = tempfile.mkdtemp(prefix="builtin-missions-")
        self.addCleanup(shutil.rmtree, tmp, True)
        proc = subprocess.run(
            [str(MISSION_PY), "list"],
            env={"PATH": BASE_PATH, "HOME": tmp, "LANG": "en_US.UTF-8", "XDG_CONFIG_HOME": tmp},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            cwd=tmp,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        missions = json.loads(proc.stdout)["missions"]
        self.assertEqual({m["name"] for m in missions}, set(BUILTIN))
        self.assertEqual(len(missions), len(BUILTIN))
        for mission in missions:
            self.assertEqual((mission["builder"], mission["checker"]), BUILTIN[mission["name"]])


class ValidateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="validate-copy-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.copy = Path(tmp).resolve()
        copy_tracked(self.copy)
        subprocess.run(["git", "init", "-q"], cwd=self.copy, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.copy, check=True)

    def validate(self):
        return subprocess.run(
            [str(self.copy / "scripts" / "validate.sh")],
            cwd=self.copy,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_passes_on_an_unchanged_copy(self):
        proc = self.validate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_fails_when_a_built_in_mission_has_no_checker(self):
        path = self.copy / BUILD_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(NO_CHECKER, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.copy, check=True)
        proc = self.validate()
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("skills/engineering/commodore/missions", proc.stderr)


if __name__ == "__main__":
    unittest.main()
