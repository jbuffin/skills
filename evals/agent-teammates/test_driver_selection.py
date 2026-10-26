"""Tests for which driver the agent-teammates scripts pick (team-env.zsh): the admiral driver inside an Admiral
ship, drivers/<HARNESS> everywhere else.

Seam: retask.sh, launch-teammate.sh and close-teammate.sh as subprocesses against a temp team dir. retask.sh shows
the choice without a launch: the claude driver declares SEND=tool (exit 4), the admiral driver SEND=script (a
`crew send` on the fake admiral). The fakes and the scrubbed environment come from admiral_world.py.

Run from the repo root: python3 -m unittest evals/agent-teammates/test_driver_selection.py -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import SCRIPTS, SHIP, WorldCase

LAUNCH = SCRIPTS / "launch-teammate.sh"
RETASK = SCRIPTS / "retask.sh"
CLOSE = SCRIPTS / "close-teammate.sh"

OK = 0
SEND_IS_A_TOOL = 4


class SelectionCase(WorldCase):
    def setUp(self):
        super().setUp()
        self.w.register("alpha")
        self.msg = self.w.message()

    def retask(self, **kw):
        return self.w.run(RETASK, self.w.team, "alpha", self.msg, **kw)

    def sent_through_admiral(self):
        return [a for a in self.w.admiral() if a[:3] == ["crew", "send", "alpha"]]

    def assertAdmiral(self, done):
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(len(self.sent_through_admiral()), 1, self.w.admiral())

    def assertNotAdmiral(self, done):
        self.assertEqual(done.code, SEND_IS_A_TOOL, done.text)
        self.assertEqual(self.w.admiral(), [])


class TestInsideAdmiral(SelectionCase):
    """decision 1 and ac9's setting: ADMIRAL_SHIP non-empty selects the admiral driver."""

    def test_ship_in_the_callers_environment_selects_the_admiral_driver(self):
        self.assertAdmiral(self.retask())

    def test_ship_in_team_env_alone_selects_it(self):
        self.w.write_team_env(extra=[f"ADMIRAL_SHIP={SHIP}"])
        self.assertAdmiral(self.retask(ship=None))

    def test_harness_from_the_callers_environment_is_ignored(self):
        self.w.write_team_env(harness=None)
        self.assertAdmiral(self.retask(HARNESS="copilot"))


class TestOutsideAdmiral(SelectionCase):
    """ac6-outside: with ADMIRAL_SHIP empty or unset, drivers/<HARNESS> is chosen and nothing changes."""

    def test_unset_ship_selects_the_harness_driver(self):
        self.assertNotAdmiral(self.retask(ship=None))

    def test_empty_ship_in_the_environment_selects_the_harness_driver(self):
        self.assertNotAdmiral(self.retask(ship=""))

    def test_empty_ship_in_team_env_selects_the_harness_driver(self):
        self.w.write_team_env(extra=["ADMIRAL_SHIP="])
        self.assertNotAdmiral(self.retask(ship=None))

    def test_launch_starts_a_background_claude_session(self):
        self.w.prompt("beta")
        done = self.w.run(LAUNCH, "--role", "test-writer", self.w.team, "beta", self.w.work, ship=None)
        self.assertEqual(done.code, OK, done.text)
        self.assertIn("launched beta as background session fake-claude-id", done.out)
        (bg,) = [c["argv"] for c in self.w.calls("claude") if "--bg" in c["argv"]]
        self.assertEqual(bg[bg.index("-n") : bg.index("-n") + 2], ["-n", "beta"])
        self.assertEqual(self.w.admiral(), [])

    def test_close_stops_the_session_through_claude(self):
        done = self.w.run(CLOSE, self.w.team, "alpha", ship=None)
        self.assertEqual(done.code, OK, done.text)
        self.assertIn(["stop", "alpha"], [c["argv"] for c in self.w.calls("claude")])
        self.assertEqual(self.w.admiral(), [])


class TestOtherHarnessesInsideAdmiral(SelectionCase):
    """decision 6: until u2, a HARNESS other than claude keeps drivers/<HARNESS> inside Admiral."""

    def test_codex_keeps_its_own_driver(self):
        self.w.write_team_env(harness="codex", extra=[f"ADMIRAL_SHIP={SHIP}"])
        done = self.retask()
        self.assertNotEqual(done.code, OK)
        self.assertIn("codex", done.text.lower())
        self.assertEqual(self.sent_through_admiral(), [])
        self.assertEqual([a for a in self.w.admiral() if a[:2] == ["crew", "launch"]], [])

    def test_copilot_keeps_its_own_driver(self):
        self.w.write_team_env(harness="copilot")
        done = self.retask()
        self.assertNotEqual(done.code, OK)
        self.assertIn("copilot", done.text.lower())
        self.assertEqual(self.w.admiral(), [])


if __name__ == "__main__":
    unittest.main()
