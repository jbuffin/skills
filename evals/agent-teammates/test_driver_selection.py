"""Tests for which driver the agent-teammates scripts pick (team-env.zsh): the admiral driver inside an Admiral
ship, drivers/<HARNESS> everywhere else.

Seam: retask.sh, launch-teammate.sh and close-teammate.sh as subprocesses against a temp team dir. retask.sh shows
the choice without a launch: the claude driver declares SEND=tool (exit 4), the admiral driver SEND=script (a
`crew send` on the fake admiral). The fakes and the scrubbed environment come from admiral_world.py.

Run from the repo root: python3 -m unittest evals/agent-teammates/test_driver_selection.py -v
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import SCRIPTS, SHIP, WorldCase, boat, rfc3339

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
    """u2 overturns u1's decision 6: inside a ship the admiral driver is chosen for every HARNESS (decision 3), except
    under ADMIRAL_AUTOPILOT=1 with a harness other than claude (decision 2), which keeps drivers/<HARNESS>."""

    def test_codex_selects_the_admiral_driver(self):
        self.w.write_team_env(harness="codex", extra=[f"ADMIRAL_SHIP={SHIP}"])
        self.assertAdmiral(self.retask())

    def test_copilot_selects_the_admiral_driver(self):
        self.w.write_team_env(harness="copilot")
        self.assertAdmiral(self.retask())

    def test_a_ship_from_team_env_alone_selects_it_for_codex(self):
        self.w.write_team_env(harness="codex", extra=[f"ADMIRAL_SHIP={SHIP}"])
        self.assertAdmiral(self.retask(ship=None))

    def forget_admiral_calls(self):
        (self.w.ctl / "admiral.log").unlink(missing_ok=True)

    def test_codex_and_copilot_outside_a_ship_keep_their_own_driver(self):
        for harness in ("codex", "copilot"):
            with self.subTest(harness=harness):
                self.w.write_team_env(harness=harness)
                self.assertAdmiral(self.retask())  # inside the ship the same team goes through Admiral
                self.forget_admiral_calls()
                done = self.retask(ship=None)
                self.assertNotEqual(done.code, OK)
                self.assertIn(harness, done.text.lower())
                self.assertEqual(self.w.admiral(), [])

    def test_autopilot_keeps_the_harness_driver_for_codex_and_copilot(self):
        for harness in ("codex", "copilot"):
            with self.subTest(harness=harness):
                self.w.write_team_env(harness=harness)
                self.assertAdmiral(self.retask())  # without autopilot the same team goes through Admiral
                self.forget_admiral_calls()
                done = self.retask(ADMIRAL_AUTOPILOT="1")
                # the harness driver has no session for alpha, which is how the choice shows
                self.assertNotEqual(done.code, OK)
                self.assertIn(harness, done.text.lower())
                self.assertEqual(self.w.admiral(), [])

    def test_autopilot_launch_runs_the_harness_driver_not_a_crew_boat(self):
        for harness in ("codex", "copilot"):
            with self.subTest(harness=harness):
                self.w.write_team_env(harness=harness)
                self.w.prompt("beta")
                self.w.prompt("gamma")
                self.w.boats(boat("beta", last_activity=rfc3339(time.time())))
                opts = ("--role", "test-writer", self.w.team, "beta", self.w.work)
                done = self.w.run(LAUNCH, *opts)
                self.assertEqual(done.code, OK, done.text)
                self.assertEqual(len(self.w.crew_calls("launch")), 1, "without autopilot a writer is a crew boat")
                self.forget_admiral_calls()
                done = self.w.run(LAUNCH, *opts[:2], self.w.team, "gamma", self.w.work, ADMIRAL_AUTOPILOT="1")
                self.assertEqual(self.w.crew_calls("launch"), [])
                self.assertEqual(done.code, OK, done.text)
                self.assertTrue(self.w.wait_finished(harness), done.text)
                self.assertEqual(len(self.w.calls(harness)), 1)
                (self.w.ctl / f"{harness}.finished").unlink()
                (self.w.ctl / f"{harness}.log").unlink()


if __name__ == "__main__":
    unittest.main()
