"""harness-available.sh: exit 0 when a teammate harness can be driven, 1 with a reason when not, 5 on a bad call."""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import SCRIPTS, SHIP, WorldCase

AVAILABLE = SCRIPTS / "harness-available.sh"


def warns(done):
    return [line for line in done.out.splitlines() if line.startswith("WARN")]


class AvailableCase(WorldCase):
    def check(self, harness, **kw):
        return self.w.run(AVAILABLE, self.w.team, harness, **kw)

    def config(self, fleets):
        d = self.w.home / ".admiral"
        d.mkdir(exist_ok=True)
        (d / "config.json").write_text(json.dumps({"fleets": fleets}))

    def lines(self, done):
        return done.out.strip().splitlines()


class TestCliOnPath(AvailableCase):
    def test_a_missing_cli_is_unavailable_and_a_present_one_is_available(self):
        self.assertEqual(self.check("codex", ship=None).code, 0)
        (self.w.bin / "codex").unlink()
        done = self.check("codex", ship=None)
        self.assertEqual(done.code, 1, done.text)
        self.assertEqual(len(self.lines(done)), 1, done.out)
        self.assertIn("codex", done.out)


class TestCantDrive(AvailableCase):
    def test_a_codex_lead_cannot_message_a_claude_teammate_outside_admiral(self):
        self.w.write_team_env(harness="codex")
        done = self.check("claude", ship=None)
        self.assertEqual(done.code, 1, done.text)
        self.assertIn("codex", done.out)
        self.assertIn("claude", done.out)
        for extra in ({}, {"ADMIRAL_AUTOPILOT": "1"}):
            self.assertEqual(self.check("claude", ship=SHIP, **extra).code, 0, extra)
        self.w.write_team_env(harness="claude")
        self.assertEqual(self.check("claude", ship=None).code, 0)


class TestInsideAdmiral(AvailableCase):
    def test_codex_needs_the_fleets_codex_key(self):
        self.config({"work": {}})
        done = self.check("codex")
        self.assertEqual(done.code, 1, done.text)
        self.assertEqual(len(self.lines(done)), 1, done.out)
        self.config({"work": {"codex": {"command": "codex"}}})
        self.assertEqual(self.check("codex").code, 0)

    def test_codex_with_an_unreadable_fleet_or_config_warns_and_is_available(self):
        self.config({"work": {}})
        self.w.ctl_write("ships.rc", "1")
        done = self.check("codex")
        self.assertEqual(done.code, 0, done.text)
        self.assertTrue(warns(done), done.out)
        self.w.ctl_write("ships.rc", "0")
        (self.w.home / ".admiral" / "config.json").write_text("{not json")
        done = self.check("codex")
        self.assertEqual(done.code, 0, done.text)
        self.assertTrue(warns(done), done.out)

    def test_copilot_always_warns_and_is_available(self):
        done = self.check("copilot")
        self.assertEqual(done.code, 0, done.text)
        self.assertTrue(warns(done), done.out)

    def test_claude_needs_only_admiral_on_the_path(self):
        self.assertEqual(self.check("claude").code, 0)
        (self.w.bin / "admiral").unlink()
        done = self.check("claude")
        self.assertEqual(done.code, 1, done.text)
        self.assertEqual(len(self.lines(done)), 1, done.out)


class TestDriversAndBadCalls(AvailableCase):
    def test_a_driver_without_available_counts_as_available_with_a_warning(self):
        scripts = self.w.root / "scripts"
        shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
        lonely = scripts / "drivers" / "lonely"
        lonely.mkdir()
        (lonely / "driver.env").write_text("SEND=script\nLIVE_MESSAGING=0\nSKILL_PREFIX=/\n")
        done = self.w.run(scripts / "harness-available.sh", self.w.team, "lonely", ship=None)
        self.assertEqual(done.code, 0, done.text)
        self.assertTrue(warns(done), done.out)

    def test_a_bad_call_exits_5(self):
        self.assertEqual(self.check("codex", ship=None).code, 0)  # control
        self.assertEqual(self.w.run(AVAILABLE, ship=None).code, 5)
        self.assertEqual(self.w.run(AVAILABLE, self.w.team, ship=None).code, 5)
        for bad in ("admiral", "nosuch"):
            with self.subTest(harness=bad):
                self.assertEqual(self.check(bad, ship=None).code, 5)

    def test_it_writes_nothing_beyond_what_team_env_creates(self):
        before = {p.name for p in self.w.team.iterdir()}
        self.assertEqual(self.check("codex", ship=None).code, 0)
        self.assertLessEqual({p.name for p in self.w.team.iterdir()} - before, {"reports", "teammates.tsv"})
        self.assertEqual(self.w.calls("codex"), [])


if __name__ == "__main__":
    unittest.main()
