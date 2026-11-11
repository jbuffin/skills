"""Tests for harness-available.sh and the drivers' optional `available` operation (issue #199, unit u3, spec section 7).

Seam: `harness-available.sh <team-dir> <harness>` as a subprocess in the admiral_world.py temp world, plus the drivers'
`available <team-dir>` called directly with TEAMMATE_HARNESS set. Exit 0 means available (an optional WARN line on
stdout), exit 1 means unavailable with one reason line on stdout, exit 5 a bad call. Expected values come from the
u3 spec.
What it catches: a CLI-missing, no-dock or can't-drive lock reported as available. What it misses: whether a real
`admiral` really can dock codex (the fake `admiral ships` and ~/.admiral/config.json stand in).

Run from the repo root: python3 -m unittest discover -s evals/agent-teammates -p 'test_harness_available.py' -v
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import ADMIRAL_DRIVER, SCRIPTS, SHIP, WorldCase

AVAILABLE = SCRIPTS / "harness-available.sh"


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
        for harness in ("claude", "codex", "copilot"):
            with self.subTest(harness=harness):
                self.assertEqual(self.check(harness, ship=None).code, 0)
                (self.w.bin / harness).rename(self.w.root / f"{harness}.away")
                done = self.check(harness, ship=None)
                self.assertEqual(done.code, 1, done.text)
                self.assertEqual(len(self.lines(done)), 1, done.out)
                self.assertIn(harness, done.out)
                (self.w.root / f"{harness}.away").rename(self.w.bin / harness)


class TestCantDrive(AvailableCase):
    def test_a_codex_lead_cannot_message_a_claude_teammate_outside_admiral(self):
        self.w.write_team_env(harness="codex")
        done = self.check("claude", ship=None)
        self.assertEqual(done.code, 1, done.text)
        self.assertIn("a codex lead can't message a claude teammate outside Admiral", done.out)

    def test_the_controls_are_available(self):
        self.assertEqual(self.check("codex", ship=None).code, 0)  # claude lead, codex teammate: SEND=script
        self.assertEqual(self.check("claude", ship=None).code, 0)  # claude lead, claude teammate
        self.w.write_team_env(harness="codex")
        for extra in ({}, {"ADMIRAL_AUTOPILOT": "1"}):
            self.assertEqual(self.check("claude", ship=SHIP, **extra).code, 0, extra)
        done = self.check("claude", ship=None)  # the case above, back outside, still fails
        self.assertEqual(done.code, 1, done.text)


class TestInsideAdmiral(AvailableCase):
    def test_codex_needs_the_fleets_codex_key(self):
        self.config({"work": {}})
        done = self.check("codex")
        self.assertEqual(done.code, 1, done.text)
        self.assertEqual(len(self.lines(done)), 1, done.out)
        self.config({"work": {"codex": {"command": "codex"}}})
        self.assertEqual(self.check("codex").code, 0)

    def test_codex_with_an_unreadable_fleet_or_config_warns_and_is_available(self):
        warn = f"WARN  can't confirm a codex dock for ship {SHIP}"
        self.config({"work": {}})
        self.w.ctl_write("ships.rc", "1")
        done = self.check("codex")
        self.assertEqual(done.code, 0, done.text)
        self.assertIn(warn, self.lines(done))
        self.w.ctl_write("ships.rc", "0")
        (self.w.home / ".admiral" / "config.json").write_text("{not json")
        done = self.check("codex")
        self.assertEqual(done.code, 0, done.text)
        self.assertIn(warn, self.lines(done))
        (self.w.home / ".admiral" / "config.json").unlink()
        self.assertIn(warn, self.lines(self.check("codex")))

    def test_copilot_always_warns_and_is_available(self):
        done = self.check("copilot")
        self.assertEqual(done.code, 0, done.text)
        self.assertIn(f"WARN  can't confirm a copilot dock for ship {SHIP}", self.lines(done))

    def test_claude_needs_only_admiral_on_the_path(self):
        self.assertEqual(self.check("claude").code, 0)
        (self.w.bin / "admiral").unlink()
        done = self.check("claude")
        self.assertEqual(done.code, 1, done.text)
        self.assertEqual(len(self.lines(done)), 1, done.out)

    def test_the_admiral_driver_answers_for_the_teammates_harness(self):
        self.config({"work": {}})
        done = self.w.run(ADMIRAL_DRIVER / "available", self.w.team, ship=SHIP, TEAMMATE_HARNESS="codex")
        self.assertEqual(done.code, 1, done.text)
        done = self.w.run(ADMIRAL_DRIVER / "available", self.w.team, ship=SHIP, TEAMMATE_HARNESS="claude")
        self.assertEqual(done.code, 0, done.text)


class TestDriversAndBadCalls(AvailableCase):
    def test_a_driver_without_available_counts_as_available_with_a_warning(self):
        scripts = self.w.root / "scripts"
        shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
        lonely = scripts / "drivers" / "lonely"
        lonely.mkdir()
        (lonely / "driver.env").write_text("SEND=script\nLIVE_MESSAGING=0\nSKILL_PREFIX=/\n")
        done = self.w.run(scripts / "harness-available.sh", self.w.team, "lonely", ship=None)
        self.assertEqual(done.code, 0, done.text)
        self.assertIn("WARN  harness lonely has no available operation", self.lines(done))

    def test_a_bad_call_exits_5(self):
        self.assertEqual(self.check("codex", ship=None).code, 0)  # control
        self.assertEqual(self.w.run(AVAILABLE, ship=None).code, 5)
        self.assertEqual(self.w.run(AVAILABLE, self.w.team, ship=None).code, 5)
        for bad in ("", "admiral", "Bad_Name", "nosuch"):
            with self.subTest(harness=bad):
                self.assertEqual(self.check(bad, ship=None).code, 5)

    def test_it_writes_nothing_beyond_what_team_env_creates(self):
        before = {p.name for p in self.w.team.iterdir()}
        self.assertEqual(self.check("codex", ship=None).code, 0)
        self.assertLessEqual({p.name for p in self.w.team.iterdir()} - before, {"reports", "teammates.tsv"})
        self.assertEqual(self.w.calls("codex"), [])


if __name__ == "__main__":
    unittest.main()
