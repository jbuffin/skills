"""A Claude teammate gets `--advisor` only when its model and ADVISOR are in different families."""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import REPO, SCRIPTS, WorldCase, boat, rfc3339, split_launch

LAUNCH = SCRIPTS / "launch-teammate.sh"
CO_PROBE = REPO / "skills" / "engineering" / "commodore" / "scripts" / "advisor-probe.sh"

OK = 0

# (teammate model, ADVISOR, the flag is passed?)
FAMILY_CASES = [
    ("opus", "opus", False),
    ("Claude-Opus-5.5", "opus", False),
    ("sonnet", "opus", True),
    ("mystery", "mystery", True),
]


def bg_call(case):
    """The argv of the single `claude --bg` call the fake recorded."""
    calls = [c["argv"] for c in case.w.calls("claude") if "--bg" in c["argv"]]
    case.assertEqual(len(calls), 1, f"expected one claude --bg call, got {calls}")
    return calls[0]


def value_after(case, argv, flag):
    case.assertIn(flag, argv)
    return argv[argv.index(flag) + 1]


class DirectLaunchCase(WorldCase):
    """launch-teammate.sh outside a ship: the claude driver starts the session."""

    def setUp(self):
        super().setUp()
        self.w.prompt("alpha")

    def launch(self, model, advisor):
        self.w.write_team_env(extra=[f"ADVISOR={advisor}"])
        done = self.w.run(LAUNCH, "--model", model, self.w.team, "alpha", self.w.work, ship="")
        self.assertEqual(done.code, OK, done.text)
        return bg_call(self)


class TestClaudeDriverFamilyRule(DirectLaunchCase):
    def test_flag_follows_the_family_rule(self):
        for model, advisor, passed in FAMILY_CASES:
            with self.subTest(model=model, advisor=advisor):
                self.setUp()  # a fresh world per case: each one counts the calls of one launch
                argv = self.launch(model, advisor)
                self.assertEqual(value_after(self, argv, "--model"), model)
                if passed:
                    self.assertEqual(value_after(self, argv, "--advisor"), advisor)
                else:
                    self.assertNotIn("--advisor", argv)

    def test_advisor_none_leaves_the_flag_out(self):
        argv = self.launch("sonnet", "none")
        self.assertEqual(value_after(self, argv, "--model"), "sonnet")
        self.assertNotIn("--advisor", argv)
        self.assertNotIn("none", argv)

    def test_role_model_decides_not_the_role_name(self):
        # a role on an Opus model drops the flag, a role on Sonnet keeps it, under the default ADVISOR=opus
        self.w.write_team_env(extra=["ADVISOR=opus", "MODEL_TRIAGER=opus"])
        done = self.w.run(LAUNCH, "--role", "triager", self.w.team, "alpha", self.w.work, ship="")
        self.assertEqual(done.code, OK, done.text)
        argv = bg_call(self)
        self.assertEqual(value_after(self, argv, "--model"), "opus")
        self.assertNotIn("--advisor", argv)
        self.w.ctl_write("claude.log", "")
        done = self.w.run(LAUNCH, "--role", "test-writer", self.w.team, "alpha", self.w.work, ship="")
        self.assertEqual(done.code, OK, done.text)
        argv = bg_call(self)
        self.assertEqual(value_after(self, argv, "--model"), "sonnet")
        self.assertEqual(value_after(self, argv, "--advisor"), "opus")


class AdmiralLaunchCase(WorldCase):
    def setUp(self):
        super().setUp()
        self.w.prompt("alpha")
        self.w.boats(boat("alpha", last_activity=rfc3339(time.time())))

    def launch(self, model, advisor, *opts):
        self.w.write_team_env(extra=[f"ADVISOR={advisor}"])
        done = self.w.run(LAUNCH, *opts, "--model", model, self.w.team, "alpha", self.w.work)
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        calls = self.w.crew_calls("launch")
        self.assertEqual(len(calls), 1, self.w.admiral())
        return split_launch(self, calls[0], "alpha")


class TestAdmiralClaudeArmFamilyRule(AdmiralLaunchCase):
    def test_opus_teammate_with_advisor_opus_gets_no_advisor_args(self):
        flags, args = self.launch("opus", "opus")
        self.assertEqual(flags["--harness"], ["claude"])
        self.assertEqual(args[args.index("--model") + 1], "opus")
        self.assertNotIn("--advisor", args)
        self.assertEqual(args.count("opus"), 1, args)  # the model's value only, no leftover advisor value

    def test_sonnet_teammate_keeps_both_advisor_values_as_separate_arg_values(self):
        _, args = self.launch("sonnet", "opus")
        self.assertEqual(args[args.index("--advisor") + 1], "opus")
        self.assertEqual(args[args.index("--model") + 1], "sonnet")


class ProbeCase(WorldCase):
    """The advisor probe, run for a model with ADVISOR in team.env. The fake claude records every call."""

    def probe(self, script, model, advisor="opus", *, trusted_dir=False, **env):
        self.w.write_team_env(extra=[f"ADVISOR={advisor}"])
        # World creates reports/ up front; take it away so the "no reports/ left behind" check means something.
        (self.w.team / "reports").rmdir()
        if trusted_dir:
            (self.w.team / "worktrees.tsv").write_text(f"slice branch {self.w.work}\n")
        env.setdefault("ADVISOR_PROBE_TIMEOUT", "1")
        env.setdefault("ADVISOR_PROBE_POLL", "0")
        return self.w.run(script, self.w.team, model, ship=None, **env)

    def assert_same_family(self, done, model):
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(done.out.splitlines()[-1], f"ADVISOR SAME-FAMILY {model}", done.out)
        self.assertNotIn("ADVISOR ON", done.out)
        self.assertNotIn("ADVISOR OFF", done.out)
        # starts no session: not even a `claude agents --json` listing
        self.assertEqual(self.w.calls("claude"), [])
        # leaves nothing behind from sourcing team-env.zsh
        self.assertFalse((self.w.team / "teammates.tsv").exists())
        self.assertFalse((self.w.team / "reports").exists())


class TestDirectProbeSameFamily(ProbeCase):
    def test_commodore_probe_reports_same_family_without_a_session(self):
        self.assert_same_family(self.probe(CO_PROBE, "opus"), "opus")

    def test_a_trusted_directory_does_not_start_a_session_either(self):
        self.assert_same_family(self.probe(CO_PROBE, "opus", trusted_dir=True), "opus")


class TestDirectProbeOtherCases(ProbeCase):
    def assert_not_same_family(self, done):
        self.assertEqual(done.code, OK, done.text)
        self.assertNotIn("SAME-FAMILY", done.out)
        # a probe result line of the existing kind
        self.assertRegex(done.out.splitlines()[-1], r"^ADVISOR (ON|OFF) ")

    def test_different_family_without_a_trusted_directory_still_reports_off(self):
        done = self.probe(CO_PROBE, "sonnet", advisor="opus")
        self.assert_not_same_family(done)
        self.assertTrue(done.out.splitlines()[-1].startswith("ADVISOR OFF sonnet"))

    def test_different_family_with_a_trusted_directory_starts_a_session_with_the_advisor(self):
        done = self.probe(CO_PROBE, "sonnet", advisor="opus", trusted_dir=True)
        self.assert_not_same_family(done)
        bg = [c["argv"] for c in self.w.calls("claude") if "--bg" in c["argv"]]
        self.assertTrue(bg, "the probe started no session")
        self.assertEqual(value_after(self, bg[0], "--advisor"), "opus")
        self.assertEqual(value_after(self, bg[0], "--model"), "sonnet")


if __name__ == "__main__":
    unittest.main()
