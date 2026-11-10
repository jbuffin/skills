"""Tests for the harness lock in `crew.py cast` (issue #199, unit u3; docs/adr/0008 and the u3 spec section 7).

Seam: `crew.py cast --run <run>` as a subprocess in a temp world (crew_world.py) whose codex and copilot drivers are
fakes: a `driver.env` with SEND=script, a `has-skill` that answers from installed.txt, and an `available` that logs
its call and answers as the test says. cast runs the real `harness-available.sh` from the copied skills, so a test that
needs it stays red until the script exists. Assert on stdout (the table), stderr (WARN and UNAVAILABLE lines), the exit
code (0, 1, 4, 5) and the files cast writes (cast.json, team.env). Expected values come from the spec, never from code.
What it catches: a lock ignored by skills, availability, unlock, save or the fix checker. What it misses: the real
codex and copilot drivers' own `available` (test_harness_available.py) and team-preflight (test_team_preflight_lock.py).

Run from the repo root: python3 -m unittest discover -s evals/commodore -p 'test_crew_cast_lock.py' -v
"""

import re
import unittest

from crew_world import WorldCase, parse_table, zsh_value

HARNESS_CELL = 6


class LockCase(WorldCase):
    def setUp(self):
        super().setUp()
        self.avail_log = self.w.root / "available.log"
        self.driver("codex", "$")
        self.driver("copilot", "/")

    def driver(self, name, prefix, reason=None, out=""):
        """A fake drivers/<name>: SEND=script, has-skill from installed.txt, `available` logging its harness."""
        self.w.stub_driver(name, prefix=prefix)
        d = self.w.drivers / name
        (d / "driver.env").write_text(f"LIVE_MESSAGING=0\nSEND=script\nSKILL_PREFIX={prefix}\n")
        answer = f"echo '{reason}'\nexit 1\n" if reason else (f"echo '{out}'\n" if out else "") + "exit 0\n"
        stub = d / "available"
        stub.write_text(f'#!/bin/sh\necho "$TEAMMATE_HARNESS" >> "{self.avail_log}"\n{answer}')
        stub.chmod(0o755)

    def member(self, role, name, harness="codex", model=None, **kw):
        extra = f"harness: {harness}\n" if harness else ""
        return self.w.write_member("repo", name, role, extra=extra, model=model, **kw)

    def checked(self):
        return self.avail_log.read_text().split() if self.avail_log.exists() else []

    def team_env(self):
        return (self.w.run / "team.env").read_text()

    def harness_lines(self):
        return [ln for ln in self.team_env().splitlines() if ln.startswith("HARNESS_")]


class TestSkillsAndCell(LockCase):
    def test_a_locked_members_skills_are_checked_and_prefixed_through_its_own_driver(self):
        self.w.install("code-review")
        self.member("implementer", "lock-impl", skills=["code-review", "nope"], model="gpt-5.5")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["implementer"][3], "`$code-review`")
        self.assertEqual(rows["implementer"][HARNESS_CELL], "codex")
        self.assertIn("WARN  implementer: skill $nope is not available on codex; dropped", done.stderr.splitlines())
        self.assertEqual(rows["reviewer"][HARNESS_CELL], "-")

    def test_an_unlocked_member_keeps_the_run_harness_prefix(self):
        self.w.install("code-review")
        self.w.write_member("repo", "plain", "reviewer", skills=["code-review"])
        self.member("implementer", "lock-impl", skills=["code-review"], model="gpt-5.5")
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["reviewer"][3], "`/code-review`")
        self.assertEqual(rows["implementer"][3], "`$code-review`")


class TestAvailability(LockCase):
    def test_an_unavailable_lock_exits_4_after_the_table_and_saves_nothing(self):
        self.driver("codex", "$", reason="codex CLI not found on PATH")
        self.member("implementer", "lock-impl", model="gpt-5.5")
        self.member("reviewer", "lock-rev", model="gpt-5.5")
        before = self.team_env()
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 4, done.stderr)
        self.assertIn(
            "UNAVAILABLE implementer: lock-impl is locked to codex: codex CLI not found on PATH",
            done.stderr.splitlines(),
        )
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["implementer"][HARNESS_CELL], "codex (unavailable)")
        self.assertEqual(rows["reviewer"][HARNESS_CELL], "codex (unavailable)")
        self.assertEqual(self.team_env(), before)
        self.assertFalse((self.w.run / "cast.json").exists())
        self.assertEqual(self.checked(), ["codex"])  # one availability check per harness, not per role

    def test_an_available_lock_is_checked_once_and_a_script_warn_passes_through(self):
        self.driver("codex", "$", out="WARN  can't confirm a codex dock for ship s1")
        self.member("implementer", "lock-impl", model="gpt-5.5")
        self.member("reviewer", "lock-rev", model="gpt-5.5")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("WARN  can't confirm a codex dock for ship s1", done.stderr.splitlines())
        self.assertEqual(self.checked(), ["codex"])


class TestUnlock(LockCase):
    def setUp(self):
        super().setUp()
        self.member("implementer", "lock-impl", model="gpt-5.5")

    def test_unlock_drops_the_model_skips_the_availability_check_and_changes_the_cell(self):
        self.driver("codex", "$", reason="codex CLI not found on PATH")
        done = self.w.cast("--unlock", "implementer")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(
            'WARN  implementer: model "gpt-5.5" of lock-impl is for codex; the role keeps its default',
            done.stderr.splitlines(),
        )
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["implementer"][HARNESS_CELL], "claude (unlocked from codex)")
        self.assertEqual(rows["implementer"][5], "-")
        self.assertEqual(self.checked(), [])

    def test_a_saved_unlock_is_kept_by_a_later_call_and_writes_no_lock_lines(self):
        done = self.w.cast("--unlock", "implementer", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.w.read_json()["unlocks"], ["implementer"])
        self.assertEqual(self.harness_lines(), [])
        self.assertNotIn("MODEL_IMPLEMENTER", self.team_env())
        later = self.w.cast()
        _, _, rows, _ = parse_table(later.stdout)
        self.assertEqual(rows["implementer"][HARNESS_CELL], "claude (unlocked from codex)")

    def test_a_saved_unlock_for_a_role_no_longer_locked_is_dropped_with_a_warning(self):
        self.w.cast("--unlock", "implementer", "--save")
        self.member("implementer", "lock-impl", harness=None)
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue([w for w in self.warns(done) if "unlock" in w and "implementer" in w], done.stderr)
        self.assertEqual(self.w.read_json()["unlocks"], [])

    def test_bad_unlock_calls_exit_5(self):
        self.member("reviewer", "plain-rev", harness=None)
        self.assertEqual(self.w.cast("--unlock", "implementer").returncode, 0)  # control
        for args in (
            ("--unlock", "implementer", "--unlock", "implementer"),
            ("--unlock", "nosuch"),
            ("--unlock", "reviewer"),
            ("--unlock",),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.w.cast(*args).returncode, 5)


class TestSave(LockCase):
    def test_save_writes_harness_lines_after_the_model_lines_and_leaves_harness_alone(self):
        self.member("implementer", "lock-impl", model="gpt-5.5")
        self.member("reviewer", "lock-rev", harness="copilot", model="gpt-5")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = self.team_env()
        self.assertIn("HARNESS_IMPLEMENTER='codex'\n", text)
        self.assertIn("HARNESS_FIX_CHECKER='codex'\n", text)
        self.assertIn("HARNESS_REVIEWER='copilot'\n", text)
        self.assertLess(text.index("MODEL_FIX_CHECKER="), text.index("HARNESS_IMPLEMENTER="))
        self.assertEqual(
            zsh_value(self.w.run / "team.env", "HARNESS", "HARNESS_IMPLEMENTER", "HARNESS_FIX_CHECKER"),
            ["claude", "codex", "codex"],
        )
        self.assertEqual(text.count("HARNESS=claude"), 1)

    def test_a_second_save_removes_stale_harness_lines(self):
        self.member("implementer", "lock-impl", model="gpt-5.5")
        self.w.cast("--save")
        self.assertIn("HARNESS_IMPLEMENTER='codex'", self.team_env())
        self.member("implementer", "lock-impl", harness=None, model="sonnet")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.harness_lines(), [])
        self.assertIn("HARNESS=claude", self.team_env())

    def test_the_fix_checker_follows_the_implementers_harness_and_ignores_its_own(self):
        self.member("implementer", "lock-impl", model="gpt-5.5")
        self.member("fix-checker", "lock-fix", harness="copilot")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(
            "WARN  fix-checker: the fix checker runs on the implementer's harness; harness copilot of lock-fix ignored",
            done.stderr.splitlines(),
        )
        self.assertEqual(self.harness_lines(), ["HARNESS_IMPLEMENTER='codex'", "HARNESS_FIX_CHECKER='codex'"])

    def test_a_custom_role_member_writes_no_team_env_line(self):
        self.member("implementer", "lock-impl", model="gpt-5.5")
        self.member("docs-writer", "docs-writer", based_on="scribe")
        done = self.w.cast("--pick", "docs-writer=docs-writer", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.harness_lines()), 2, self.harness_lines())
        self.assertNotIn("DOCS_WRITER", self.team_env())


class TestNoModelWarning(LockCase):
    def test_a_locked_member_without_a_model_is_told_to_set_one(self):
        self.member("implementer", "lock-impl")
        self.member("reviewer", "lock-rev", harness="copilot")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stderr.splitlines()
        impl = [
            ln for ln in lines if ln.startswith("WARN  implementer: lock-impl is locked to codex and names no model")
        ]
        self.assertEqual(len(impl), 1, done.stderr)
        self.assertIn("set MODEL_IMPLEMENTER and EFFORT_IMPLEMENTER for codex", impl[0])
        self.assertTrue(impl[0].endswith("(and MODEL_FIX_CHECKER, EFFORT_FIX_CHECKER)"), impl[0])
        self.assertIn(
            "WARN  reviewer: lock-rev is locked to copilot and names no model; "
            "set MODEL_REVIEWER and EFFORT_REVIEWER for copilot",
            lines,
        )

    def test_a_model_or_the_runs_own_harness_gets_no_warning(self):
        self.member("implementer", "lock-impl", model="gpt-5.5")
        self.member("reviewer", "own-rev", harness="claude")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIsNone(re.search(r"names no model", done.stderr), done.stderr)
        self.assertIn("HARNESS_IMPLEMENTER='codex'", self.team_env())


if __name__ == "__main__":
    unittest.main()
