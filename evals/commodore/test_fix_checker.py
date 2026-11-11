"""Tests for the fix check: review-round.sh's round order, team-init.sh's fix-checker model and its launch."""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "evals" / "agent-teammates"))

from admiral_world import SCRIPTS as AT_SCRIPTS  # noqa: E402
from admiral_world import WorldCase  # noqa: E402
from crew_world import BASE_PATH  # noqa: E402

CO_SCRIPTS = REPO / "skills" / "engineering" / "commodore" / "scripts"
REVIEW_ROUND = CO_SCRIPTS / "review-round.sh"
TEAM_INIT = CO_SCRIPTS / "team-init.sh"
LAUNCH = AT_SCRIPTS / "launch-teammate.sh"


def sh_env(home, **extra):
    return {
        "PATH": BASE_PATH,
        "HOME": str(home),
        "LANG": "en_US.UTF-8",
        "XDG_CONFIG_HOME": str(Path(home) / "xdg"),
        **extra,
    }


def run(cmd, env, **kw):
    return subprocess.run(
        [str(c) for c in cmd],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        **kw,
    )


def parse_env(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


class TmpCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()


class TestReviewRound(TmpCase):
    def setUp(self):
        super().setUp()
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        (self.run_dir / "team.env").write_text("HARNESS=claude\n")

    def round(self):
        return run([REVIEW_ROUND, self.run_dir, "u1"], sh_env(self.home))

    def test_round_2_is_a_fix_check_and_a_third_round_is_capped(self):
        self.round()
        second = self.round()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("round 2 of 2 for u1", second.stdout)
        self.assertIn("u1-fix-checker", second.stdout)
        self.assertNotIn("u1-reviewer-2", second.stdout)
        third = self.round()
        self.assertEqual(third.returncode, 1)
        self.assertTrue(third.stdout.startswith("CAP u1: 2 review rounds done"), third.stdout)


class TestTeamInit(TmpCase):
    def test_fix_checker_model_and_effort_are_the_implementers(self):
        teams = self.root / "teams"
        done = run(
            [TEAM_INIT, "fresh", self.checkout],
            sh_env(self.home, AGENT_TEAMS_DIR=str(teams), HARNESS="codex", CMUX_BUNDLED_CLI_PATH="/nonexistent"),
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        env = parse_env(teams / "fresh" / "team.env")
        self.assertTrue(env["MODEL_IMPLEMENTER"])
        self.assertEqual(env["MODEL_FIX_CHECKER"], env["MODEL_IMPLEMENTER"])
        self.assertEqual(env["EFFORT_IMPLEMENTER"], "medium")
        self.assertEqual(env["EFFORT_FIX_CHECKER"], "medium")


class TestLaunch(WorldCase):
    def test_read_only_fix_checker_launches_on_a_fresh_team_env(self):
        w = self.w
        (w.team / "team.env").unlink()
        env = w.env(ship=None, AGENT_TEAMS_DIR=str(w.root), HARNESS="claude", CMUX_BUNDLED_CLI_PATH="/nonexistent")
        init = run([TEAM_INIT, "team", w.checkout], env)
        self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
        w.prompt("alpha")
        done = w.run(LAUNCH, "--read-only", "--role", "fix-checker", w.team, "alpha", w.work, ship=None)
        self.assertEqual(done.code, 0, done.text)
        self.assertEqual([r[0] for r in w.registry()], ["alpha"])


if __name__ == "__main__":
    unittest.main()
