"""Tests for the fix checker (issue #169): review round 2 becomes a fix check run by a read-only `fix-checker` role.

Seams are the shipped scripts' command lines and the text of the shipped docs. Expected values come from the
issue's Agent Brief, not from the code. Some checks held on main already, so each is paired with an assertion that
fails without the change, except the named regression guards for round 1 and the round cap (no other eval covers
`review-round.sh`). `pr-ready.sh` needs no code change: test_pr_ready.py already pins an `open` finding (does not
leave the unit for a human) and a `human` finding (stops auto-merge); the test here is that mission-build.md
tells the coordinator to record fix-check notes as `open`.

Run from the repo root: python3 -m unittest discover -s evals/commodore -v
"""

import json
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

COMMODORE = REPO / "skills" / "engineering" / "commodore"
CO_SCRIPTS = COMMODORE / "scripts"
REVIEW_ROUND = CO_SCRIPTS / "review-round.sh"
ROLE_SKILLS = CO_SCRIPTS / "role-skills.sh"
TEAM_INIT = CO_SCRIPTS / "team-init.sh"
ROLES_DRAFT = REPO / "skills" / "engineering" / "setup-commodore" / "scripts" / "roles-draft.sh"
LAUNCH = AT_SCRIPTS / "launch-teammate.sh"
GLOSSARY = REPO / "GLOSSARY.md"
HARNESSES = ("claude", "codex", "copilot")


def text(path):
    return Path(path).read_text()


def sh_env(home, **extra):
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
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
    for line in text(path).splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def glossary_entry(term):
    m = re.search(rf"^\*\*{re.escape(term)}\*\*:.*$", text(GLOSSARY), re.M)
    return m.group(0) if m else None


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

    def test_round_1_output_is_unchanged(self):
        done = self.round()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            done.stdout.strip(),
            "round 1 of 2 for u1: full review. Launch u1-reviewer-1, and u1-security-reviewer-1 when the run has a "
            "security reviewer, on the unit's diff",
        )

    def test_round_2_names_the_fix_checker_and_no_reviewer(self):
        self.round()
        done = self.round()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("round 2 of 2 for u1", done.stdout)
        self.assertIn("u1-fix-checker", done.stdout)
        self.assertNotIn("uu1-fix-checker", done.stdout)
        self.assertNotIn("u1-reviewer-2", done.stdout)

    def test_round_2_does_not_send_everything_else_to_a_human(self):
        self.round()
        out = self.round().stdout
        self.assertIn("u1-fix-checker", out)
        self.assertNotIn("everything else goes to a human", out)

    def test_round_2_says_where_each_kind_of_finding_goes(self):
        self.round()
        out = self.round().stdout
        for needle in (
            "not fixed or partly fixed",
            "HIGH first",
            "status=human",
            "only a HIGH there is blocking",
            "status=open",
            "Re-task nobody",
        ):
            self.assertIn(needle, out)

    def test_third_call_is_refused_with_exit_1(self):
        self.round()
        self.round()
        done = self.round()
        self.assertEqual(done.returncode, 1)
        self.assertTrue(done.stdout.startswith("CAP u1: 2 review rounds done"), done.stdout)


class TestRoleSkills(TmpCase):
    def setUp(self):
        super().setUp()
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        (self.run_dir / "team.env").write_text(f"HARNESS=claude\nREPO={self.checkout}\n")

    def resolve(self):
        return run([ROLE_SKILLS, self.run_dir], sh_env(self.home))

    def row(self, out, role):
        rows = [ln for ln in out.splitlines() if ln.startswith(f"| {role} |")]
        return rows[0] if rows else None

    def layers(self):
        """Each layer file that can hold an override, as (name, path)."""
        return [
            ("user", self.home / "xdg" / "commodore" / "roles.json"),
            ("repo", self.checkout / ".commodore" / "roles.json"),
            ("run", self.run_dir / "roles.json"),
        ]

    def write_layer(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def test_fix_checker_has_no_skills_even_with_a_reviewer_override(self):
        for name, path in self.layers():
            with self.subTest(layer=name):
                self.write_layer(path, {"reviewer": {"skills": ["code-review"]}})
                done = self.resolve()
                self.assertEqual(done.returncode, 0, done.stderr)
                row = self.row(done.stdout, "fix-checker")
                self.assertIsNotNone(row, f"no fix-checker row:\n{done.stdout}")
                cells = [c.strip() for c in row.strip("|").split("|")]
                self.assertTrue(cells[1].startswith("none"), row)
                self.assertNotIn("fallback", row)
                self.assertEqual(cells[3], "built-in", row)
                path.unlink()

    def test_override_naming_fix_checker_is_dropped_with_a_warning(self):
        for name, path in self.layers():
            with self.subTest(layer=name):
                self.write_layer(path, {"fix-checker": {"skills": ["code-review"], "instructions": "be thorough"}})
                done = self.resolve()
                self.assertEqual(done.returncode, 0, done.stderr)
                row = self.row(done.stdout, "fix-checker")
                self.assertIsNotNone(row, f"no fix-checker row:\n{done.stdout}")
                self.assertNotIn("code-review", row)
                self.assertNotIn("be thorough", row)
                self.assertNotIn("fallback", row)
                self.assertIn("built-in", row)
                warns = [ln for ln in done.stderr.splitlines() if ln.startswith("WARN") and "fix-checker" in ln]
                self.assertTrue(warns, done.stderr)
                path.unlink()


class TestRolesDraft(TmpCase):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "-C", self.checkout, "init", "-q"], check=True)
        self.env = sh_env(self.home, TMPDIR=str(self.root))

    def init(self):
        done = run([ROLES_DRAFT, "init", "user", "claude"], self.env, cwd=self.checkout)
        self.assertEqual(done.returncode, 0, done.stderr)
        return Path(done.stdout.splitlines()[0])

    def check(self, run_dir):
        done = run([ROLES_DRAFT, "check", run_dir], self.env, cwd=self.checkout)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def resolved_table(self, run_dir):
        done = run([ROLE_SKILLS, run_dir], self.env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_empty_draft_has_no_unset_line_for_fix_checker(self):
        run_dir = self.init()
        # the role exists in the resolved table: it is excluded from UNSET, not absent
        self.assertIn("| fix-checker |", self.resolved_table(run_dir))
        out = self.check(run_dir)
        self.assertNotIn("UNSET fix-checker", out)
        self.assertIn("UNSET reviewer:", out)  # the other roles are still reported

    def test_draft_naming_fix_checker_does_not_read_as_clean(self):
        run_dir = self.init()
        (run_dir / "draft.json").write_text(json.dumps({"fix-checker": {"skills": ["code-review"]}}))
        # the role is known, so the warning is the drop rule's, not "unknown role"
        self.assertIn("| fix-checker |", self.resolved_table(run_dir))
        out = self.check(run_dir)
        warns = [ln for ln in out.splitlines() if ln.startswith("WARN  draft: ") and "fix-checker" in ln]
        self.assertTrue(warns, out)
        self.assertRegex(warns[0], r"ignored|dropped|skipped")
        self.assertNotIn("unknown role", warns[0])
        self.assertIn("NOT CLEAN", out)
        self.assertNotIn("\nCLEAN", "\n" + out)

    def test_fix_checker_is_not_offered_as_a_role_to_configure(self):
        run_dir = self.init()
        self.assertIn("| fix-checker |", self.resolved_table(run_dir))
        skill = text(REPO / "skills" / "engineering" / "setup-commodore" / "SKILL.md")
        self.assertNotIn("fix-checker", skill)


class TestTeamInit(TmpCase):
    def init(self, harness):
        teams = self.root / "teams"
        done = run(
            [TEAM_INIT, f"fresh-{harness}", self.checkout],
            sh_env(self.home, AGENT_TEAMS_DIR=str(teams), HARNESS=harness, CMUX_BUNDLED_CLI_PATH="/nonexistent"),
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return parse_env(teams / f"fresh-{harness}" / "team.env")

    def test_fix_checker_model_is_the_implementers_on_every_harness(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                env = self.init(harness)
                self.assertTrue(env["MODEL_IMPLEMENTER"])
                self.assertIn("MODEL_FIX_CHECKER", env)
                self.assertEqual(env["MODEL_FIX_CHECKER"], env["MODEL_IMPLEMENTER"])

    def test_fix_checker_effort_is_the_implementers_where_the_harness_writes_effort(self):
        expected = {"claude": None, "codex": "medium", "copilot": ""}
        for harness, effort in expected.items():
            with self.subTest(harness=harness):
                env = self.init(harness)
                if effort is None:
                    self.assertNotIn("EFFORT_IMPLEMENTER", env)
                    self.assertNotIn("EFFORT_FIX_CHECKER", env)
                else:
                    self.assertEqual(env["EFFORT_IMPLEMENTER"], effort)
                    self.assertIn("EFFORT_FIX_CHECKER", env)
                    self.assertEqual(env["EFFORT_FIX_CHECKER"], env["EFFORT_IMPLEMENTER"])


class LaunchFixChecker:
    """Mixin: one launch test per harness class below."""

    harness = None

    def test_read_only_fix_checker_launches_on_a_fresh_team_env(self):
        w = self.w
        (w.team / "team.env").unlink()
        env = w.env(ship=None, AGENT_TEAMS_DIR=str(w.root), HARNESS=self.harness, CMUX_BUNDLED_CLI_PATH="/nonexistent")
        init = run([TEAM_INIT, "team", w.checkout], env)
        self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
        w.prompt("alpha")
        done = w.run(LAUNCH, "--read-only", "--role", "fix-checker", w.team, "alpha", w.work, ship=None)
        if self.harness != "claude":
            w.wait_finished(self.harness)
        self.assertEqual(done.code, 0, done.text)
        self.assertEqual([r[0] for r in w.registry()], ["alpha"])


class TestLaunchClaude(LaunchFixChecker, WorldCase):
    harness = "claude"


class TestLaunchCodex(LaunchFixChecker, WorldCase):
    harness = "codex"


class TestLaunchCopilot(LaunchFixChecker, WorldCase):
    harness = "copilot"


class TestShippedText(unittest.TestCase):
    def setUp(self):
        self.skill = text(COMMODORE / "SKILL.md")
        self.roles = text(COMMODORE / "references" / "roles.md")
        self.build = text(COMMODORE / "references" / "mission-build.md")
        self.script = text(REVIEW_ROUND)

    def line(self, body, needle):
        found = [ln for ln in body.splitlines() if needle in ln]
        self.assertTrue(found, f"no line with {needle!r}")
        return found[0]

    def test_no_text_runs_a_reviewer_in_round_2(self):
        self.assertNotIn("Round 2 is the last, and your brief says when you're in it", self.roles)
        self.assertNotIn("and checks the fixes in round 2, fresh each round", self.build)
        self.assertNotIn("launch one fresh reviewer, `--read-only --role reviewer`, on the fix range", self.build)
        self.assertNotIn("one\n# reviewer on the fix range", self.script)
        self.assertIn("--read-only --role fix-checker", self.build)

    def test_round_2_is_described_as_a_fix_check(self):
        self.assertIn("fix check", self.line(self.skill, "A **review round**"))
        self.assertIn("## Fix checker", self.roles)
        self.assertRegex(self.roles, r"(?m)^\| Fix checker \|")
        self.assertRegex(self.build, r"(?m)^\| Fix checker \|")

    def test_only_a_range_introduced_high_blocks_in_round_2(self):
        line = self.line(self.skill, "A **blocking finding**")
        self.assertNotIn("or a HIGH finding in round 2", line)
        self.assertIn("introduced", line)

    def test_no_text_sends_a_fix_check_finding_back_to_the_implementer(self):
        self.assertNotIn("a round-2 finding, HIGH included", self.build)
        retask = self.line(self.build, "Every re-task of a live teammate")
        self.assertIn("fix check", retask.lower())
        close = self.line(self.build, "Close the implementer last")
        self.assertIn("fix check", close.lower())

    def test_notes_are_recorded_open_not_human(self):
        notes = [ln for ln in self.build.splitlines() if re.search(r"seen in passing|notes?\b", ln, re.I)]
        self.assertTrue(any(re.search(r"status=open|`open`", ln) for ln in notes), "no line records notes as open")
        step5 = self.line(self.build, "Done when round 2's report")
        self.assertNotRegex(step5, r"round-2 finding")


class TestGlossary(unittest.TestCase):
    def test_new_terms(self):
        self.assertIsNotNone(glossary_entry("Fix check"))
        self.assertIsNotNone(glossary_entry("Fix checker"))

    def test_review_round_and_blocking_finding_mention_the_fix_check(self):
        for term in ("Review round", "Blocking finding"):
            with self.subTest(term=term):
                self.assertIn("fix check", glossary_entry(term).lower())

    def test_non_blocking_finding_keeps_fix_check_notes_from_the_implementer(self):
        self.assertIn("fix check", glossary_entry("Non-blocking finding").lower())

    def test_role_skill_names_the_fix_checker_as_having_no_fallback(self):
        entry = glossary_entry("Role skill")
        self.assertIn("fix checker", entry.lower())


if __name__ == "__main__":
    unittest.main()
