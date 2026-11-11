"""Review round 2 is a fix check run by a read-only fix-checker role."""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "evals" / "agent-teammates"))

import crew_world as cw  # noqa: E402
from admiral_world import SCRIPTS as AT_SCRIPTS  # noqa: E402
from admiral_world import WorldCase  # noqa: E402

COMMODORE = REPO / "skills" / "engineering" / "commodore"
CO_SCRIPTS = COMMODORE / "scripts"
REVIEW_ROUND = CO_SCRIPTS / "review-round.sh"
TEAM_INIT = CO_SCRIPTS / "team-init.sh"
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
            "only a HIGH the fixes introduced is new blocking work",
            "status=open",
            "Don't re-task anyone for a fix-check result",
        ):
            self.assertIn(needle, out)

    def test_third_call_is_refused_with_exit_1(self):
        self.round()
        self.round()
        done = self.round()
        self.assertEqual(done.returncode, 1)
        self.assertTrue(done.stdout.startswith("CAP u1: 2 review rounds done"), done.stdout)


class TestFixCheckerCast(cw.WorldCase):
    """The fix-checker row of `crew.py cast`, ported from the deleted role-skills.sh: the role never has skills or
    instructions, and a member that names it is dropped with a warning."""

    LAYERS = ("user", "repo", "run")

    def row(self, done, role="fix-checker"):
        _, _, rows, _ = cw.parse_table(done.stdout)
        return rows.get(role)

    def test_fix_checker_has_no_skills_even_with_a_reviewer_member(self):
        self.w.install("code-review")
        for layer in self.LAYERS:
            with self.subTest(layer=layer):
                path = self.w.write_member(layer, "reviewer", skills=["code-review"])
                done = self.w.cast()
                self.assertEqual(done.returncode, 0, done.stderr)
                cells = self.row(done)
                self.assertIsNotNone(cells, f"no fix-checker row:\n{done.stdout}")
                self.assertEqual(cells[3], "none")
                self.assertEqual(cells[4], "-")
                self.assertNotIn("fallback", "|".join(cells))
                self.assertEqual(cells[7], "built-in")
                path.unlink()

    def test_member_for_fix_checker_is_dropped_with_a_warning(self):
        self.w.install("code-review")
        for layer, source in (("user", "user-global"), ("repo", "repo"), ("run", "run (pinned)")):
            with self.subTest(layer=layer):
                path = self.w.write_member(layer, "fix-checker", skills=["code-review"], body="be thorough")
                done = self.w.cast()
                self.assertEqual(done.returncode, 0, done.stderr)
                cells = self.row(done)
                self.assertIsNotNone(cells, f"no fix-checker row:\n{done.stdout}")
                self.assertEqual(cells[3:5], ["none", "-"])
                self.assertNotIn("code-review", "|".join(cells))
                self.assertNotIn("be thorough", "|".join(cells))
                self.assertNotIn("fallback", "|".join(cells))
                self.assertEqual(cells[7], source)  # the layer that held the dropped entry, not "built-in"
                self.assertTrue([w for w in self.warns(done) if "fix-checker" in w], done.stderr)
                path.unlink()


class TestFixCheckerDraft(cw.WorldCase):
    """The fix-checker cases of the deleted roles-draft.sh, on crew-draft.sh."""

    def setUp(self):
        super().setUp()
        self.git_init(self.w.repo)
        self.draft_sh = self.w.skills / "setup-commodore" / "scripts" / "crew-draft.sh"

    def draft(self, *args):
        return self.w.sh([self.draft_sh, *args], cwd=self.w.repo)

    def init(self):
        done = self.draft("init", "user", "claude")
        self.assertEqual(done.returncode, 0, done.stderr)
        return Path(done.stdout.splitlines()[0])

    def test_empty_draft_has_no_unset_line_for_fix_checker(self):
        run_dir = self.init()
        done = self.draft("check", run_dir)
        self.assertEqual(done.returncode, 0, done.stderr)
        # the role exists in the cast table: it is excluded from UNSET, not absent
        self.assertIn("| fix-checker |", done.stdout)
        out = done.stdout + done.stderr
        self.assertNotIn("UNSET fix-checker", out)
        self.assertIn("UNSET reviewer:", out)  # the other roles are still reported

    def test_draft_naming_fix_checker_does_not_read_as_clean(self):
        run_dir = self.init()
        (run_dir / "draft" / "fix-checker.md").write_text(
            cw.member_text("fix-checker", "fix-checker", skills=["code-review"])
        )
        done = self.draft("check", run_dir)
        self.assertEqual(done.returncode, 0, done.stderr)
        warns = [ln for ln in done.stderr.splitlines() if ln.startswith("WARN") and "fix-checker" in ln]
        self.assertTrue(warns, done.stderr)
        self.assertNotIn("CLEAN", done.stdout.splitlines())

    def test_fix_checker_is_not_offered_as_a_role_to_configure(self):
        run_dir = self.init()
        self.assertIn("| fix-checker |", self.draft("check", run_dir).stdout)
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

    def test_no_bg_retries_once_then_skips_and_the_unit_can_finish(self):
        skip = self.line(self.build, "exits 2 (`NO_BG`)")
        self.assertIn("retry the launch once", skip)
        self.assertIn("status=human", skip)
        self.assertIn("or the skip above", self.line(self.build, "Done when round 2's report"))

    def test_the_contract_pasted_into_the_brief_has_no_coordinator_rule(self):
        section = self.roles.split("## Fix checker", 1)[1].split("## Security reviewer", 1)[0]
        self.assertNotIn("NO_BG", section)

    def test_a_break_the_fixes_caused_counts_as_introduced(self):
        self.assertIn("A break the fixes caused goes here, even in code they didn't touch", self.roles)


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
