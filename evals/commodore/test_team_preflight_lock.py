"""Tests for team-preflight.sh with a harness lock (issue #199, unit u3, spec section 7).

Seam: team-preflight.sh as a subprocess in the crew_world.py temp world (copied skills, fake drivers). The fake
drivers/codex has a `preflight` and an `available` that log each call; drivers/admiral/preflight is a logging fake too,
so a test can show the Admiral preflight never ran. ADVISOR_PROBE is a logging stub. CLAUDECODE=1 makes detect-harness
see a Claude run. Expected lines come from the spec: a locked harness's own preflight runs directly, its lines carry a
`[<h>] ` prefix, a FAIL becomes `FAIL  locked harness <h> (roles: ...) failed preflight: put it in the decision batch`,
the advisor probe skips locked roles with `ADVISOR n/a (<role> locked to <h>)`, and a cast exit 4 shows as
`FAIL  crew:`.
What it catches: a lock whose harness is never preflighted, a locked model probed through the run's advisor, a hidden
failure. What it misses: the real codex and copilot preflights, and the generic run-preflight checks (not asserted on).

Run from the repo root: python3 -m unittest discover -s evals/commodore -p 'test_team_preflight_lock.py' -v
"""

import unittest

from crew_world import WorldCase

FAKE_CLAUDE = '#!/bin/sh\n[ "$1" = agents ] && echo "[]"\nexit 0\n'


class PreflightLockCase(WorldCase):
    def setUp(self):
        super().setUp()
        self.git_init(self.w.repo)  # the generic checks FAIL on a checkout without user.email
        for key, value in (("user.email", "test@example.com"), ("user.name", "Test")):
            self.w.sh(["git", "-C", self.w.repo, "config", key, value])
        self.log = self.w.root / "calls.log"
        self.bin = self.w.root / "bin"
        self.bin.mkdir()
        self.script(self.bin / "claude", FAKE_CLAUDE)
        self.probe = self.script(
            self.w.root / "probe", f'#!/bin/sh\necho "probe $2" >> "{self.log}"\necho "ADVISOR ON $2"\n'
        )
        self.locked_driver("codex")
        self.script(
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

    @staticmethod
    def script(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o755)
        return path

    def locked_driver(self, name, preflight_lines=("OK    codex CLI found",), preflight_rc=0, avail_reason=None):
        """A fake drivers/<name> whose preflight prints `preflight_lines`, and whose `available` logs and answers."""
        self.w.stub_driver(name, prefix="$")
        d = self.w.drivers / name
        (d / "driver.env").write_text("LIVE_MESSAGING=0\nSEND=script\nSKILL_PREFIX=$\n")
        printed = "".join(f"echo '{ln}'\n" for ln in preflight_lines)
        self.script(
            d / "preflight", f'#!/bin/sh\necho "{name}-preflight $1" >> "{self.log}"\n{printed}exit {preflight_rc}\n'
        )
        answer = f"echo '{avail_reason}'\nexit 1\n" if avail_reason else "exit 0\n"
        self.script(d / "available", f'#!/bin/sh\necho "{name}-available $TEAMMATE_HARNESS" >> "{self.log}"\n{answer}')

    def preflight(self):
        env = self.w.env(
            PATH=f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
            CLAUDECODE="1",
            ADVISOR_PROBE=str(self.probe),
        )
        return self.w.sh([self.w.scripts / "team-preflight.sh", self.w.run], env=env)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def out(self, done):
        return done.stdout.splitlines()


class TestLockedHarnessPreflight(PreflightLockCase):
    def test_the_locked_harnesss_own_preflight_runs_with_a_prefix_and_the_admirals_does_not(self):
        done = self.preflight()
        self.assertIn(f"codex-preflight {self.w.run}", self.calls())
        self.assertIn("[codex] OK    codex CLI found", self.out(done), done.stdout)
        self.assertNotIn("admiral-preflight", self.calls())
        self.assertEqual(len([c for c in self.calls() if c.startswith("codex-preflight")]), 1)  # once for two roles
        self.assertNotIn("locked harness", done.stdout)  # a passing preflight adds no decision-batch FAIL

    def test_harness_available_runs_for_the_locked_harness(self):
        self.preflight()
        self.assertIn("codex-available codex", self.calls())

    def test_a_failing_preflight_prints_the_decision_batch_fail_line(self):
        self.locked_driver("codex", ("FAIL  codex login missing",), preflight_rc=1)
        done = self.preflight()
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("[codex] FAIL  codex login missing", self.out(done), done.stdout)
        self.assertIn(
            "FAIL  locked harness codex (roles: implementer, fix-checker) failed preflight: "
            "put it in the decision batch",
            self.out(done),
            done.stdout,
        )


class TestAdvisorProbeSkipsLockedRoles(PreflightLockCase):
    def test_a_locked_roles_model_is_not_probed_and_is_reported_na(self):
        done = self.preflight()
        self.assertEqual([c for c in self.calls() if c.startswith("probe")], ["probe sonnet"], self.calls())
        self.assertIn("ADVISOR n/a (implementer locked to codex)", done.stdout)
        self.assertIn("ADVISOR n/a (fix-checker locked to codex)", done.stdout)
        self.assertIn("advisor on for sonnet", done.stdout)  # companion: the probe for the run's own model still ran


class TestCastFailureShowsThrough(PreflightLockCase):
    def test_an_unavailable_lock_fails_the_crew_line(self):
        self.locked_driver("codex", avail_reason="codex CLI not found on PATH")
        done = self.preflight()
        self.assertEqual(done.returncode, 1, done.stdout)
        crew = [ln for ln in self.out(done) if ln.startswith("FAIL  crew:")]
        self.assertTrue(crew, done.stdout)
        self.assertIn("codex", crew[0])


if __name__ == "__main__":
    unittest.main()
