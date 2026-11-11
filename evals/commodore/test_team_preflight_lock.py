"""team-preflight.sh with a harness lock: the locked harness's preflight, the advisor skip and the cast failure."""

import shutil
import subprocess
import tempfile
import unittest

from crew_world import BASE_PATH, World

FAKE_CLAUDE = '#!/bin/sh\n[ "$1" = agents ] && echo "[]"\nexit 0\n'


def script(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


class LockWorld:
    """A crew world whose implementer and fix-checker are locked to a fake codex driver that logs each call."""

    def __init__(self, root):
        self.w = World(root)
        repo = str(self.w.repo)
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
        for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
            subprocess.run(["git", "-C", repo, "config", key, value], check=True)
        self.log = self.w.root / "calls.log"
        self.bin = self.w.root / "bin"
        script(self.bin / "claude", FAKE_CLAUDE)
        self.probe = script(
            self.w.root / "probe", f'#!/bin/sh\necho "probe $2" >> "{self.log}"\necho "ADVISOR ON $2"\n'
        )
        self.locked_driver()
        script(
            self.w.drivers / "admiral" / "preflight",
            f'#!/bin/sh\necho "admiral-preflight" >> "{self.log}"\necho "OK    admiral"\n',
        )
        self.w.write_member("repo", "lock-impl", "implementer", extra="harness: codex\n", model="gpt-5.5")
        self.w.team_env(
            lines=[
                "MODE=single",
                "ADVISOR=opus",
                "MODEL=sonnet",
                "MODEL_IMPLEMENTER=gpt-5.5",
                "MODEL_FIX_CHECKER=gpt-5.5",
                "HARNESS_IMPLEMENTER=codex",
                "HARNESS_FIX_CHECKER=codex",
            ]
        )

    def locked_driver(self, preflight_lines=("OK    codex CLI found",), preflight_rc=0, avail_reason=None):
        d = self.w.drivers / "codex"
        self.w.stub_driver("codex", prefix="$")
        (d / "driver.env").write_text("LIVE_MESSAGING=0\nSEND=script\nSKILL_PREFIX=$\n")
        printed = "".join(f"echo '{ln}'\n" for ln in preflight_lines)
        script(d / "preflight", f'#!/bin/sh\necho "codex-preflight $1" >> "{self.log}"\n{printed}exit {preflight_rc}\n')
        answer = f"echo '{avail_reason}'\nexit 1\n" if avail_reason else "echo 'WARN  stub dock note'\nexit 0\n"
        script(d / "available", f'#!/bin/sh\necho "codex-available $TEAMMATE_HARNESS" >> "{self.log}"\n{answer}')

    def preflight(self, **extra):
        env = self.w.env(PATH=f"{self.bin}:{BASE_PATH}", CLAUDECODE="1", ADVISOR_PROBE=str(self.probe), **extra)
        return self.w.sh([self.w.scripts / "team-preflight.sh", self.w.run], env=env)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class TestPassingLock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(prefix="crew-world-")
        cls.addClassCleanup(shutil.rmtree, tmp, True)
        cls.world = LockWorld(tmp)
        cls.done = cls.world.preflight()
        cls.out = cls.done.stdout.splitlines()
        cls.calls = cls.world.calls()

    def test_the_locked_harnesss_own_preflight_runs_once_with_a_prefix_and_the_admirals_does_not(self):
        self.assertEqual(
            [c for c in self.calls if c.startswith("codex-preflight")], [f"codex-preflight {self.world.w.run}"]
        )
        self.assertIn("[codex] OK    codex CLI found", self.out, self.done.stdout)
        self.assertNotIn("admiral-preflight", self.calls)
        self.assertNotIn("locked harness", self.done.stdout)

    def test_harness_available_runs_in_preflight_and_its_lines_carry_the_prefix(self):
        self.assertIn("[codex] WARN  stub dock note", self.out, self.done.stdout)

    def test_a_locked_roles_model_is_not_probed_and_is_reported_na(self):
        self.assertEqual([c for c in self.calls if c.startswith("probe")], ["probe sonnet"], self.calls)
        self.assertIn("ADVISOR n/a (implementer locked to codex)", self.done.stdout)
        self.assertIn("ADVISOR n/a (fix-checker locked to codex)", self.done.stdout)


class TestOtherRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="crew-world-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.world = LockWorld(tmp)

    def test_inside_a_ship_the_admiral_preflight_still_does_not_run(self):
        done = self.world.preflight(ADMIRAL_SHIP="ship-1")
        self.assertIn(f"codex-preflight {self.world.w.run}", self.world.calls())
        self.assertIn("[codex] OK    codex CLI found", done.stdout.splitlines(), done.stdout)
        self.assertNotIn("admiral-preflight", self.world.calls())

    def test_a_failing_preflight_prints_the_decision_batch_fail_line(self):
        self.world.locked_driver(("FAIL  codex login missing",), preflight_rc=1)
        done = self.world.preflight()
        self.assertEqual(done.returncode, 1, done.stdout)
        out = done.stdout.splitlines()
        self.assertIn("[codex] FAIL  codex login missing", out, done.stdout)
        fails = [ln for ln in out if ln.startswith("FAIL  locked harness codex (roles: ")]
        self.assertEqual(len(fails), 1, done.stdout)
        self.assertEqual(fails[0].split("(roles: ")[1].split(")")[0], "implementer, fix-checker")

    def test_an_unavailable_lock_fails_the_crew_line(self):
        self.world.locked_driver(avail_reason="codex CLI not found on PATH")
        done = self.world.preflight()
        self.assertEqual(done.returncode, 1, done.stdout)
        crew = [ln for ln in done.stdout.splitlines() if ln.startswith("FAIL  crew:")]
        self.assertEqual(len(crew), 1, done.stdout)
        for name in ("implementer", "lock-impl", "codex"):
            self.assertIn(name, crew[0])


if __name__ == "__main__":
    unittest.main()
