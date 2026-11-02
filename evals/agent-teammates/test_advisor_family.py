"""Tests for the same-family advisor rule (issue #168): a Claude teammate gets `--advisor $ADVISOR` only when its model
and ADVISOR are in different families, on both Claude launch paths and in the direct advisor probe.

Families are opus, sonnet, haiku and fable, matched as a case-insensitive substring ("sonnet[1m]" and "claude-opus-5.5"
both resolve). An unrecognised family on either side keeps the flag; ADVISOR=none leaves it out. Expected values come
from the Agent Brief on #168, not from the code.

Seams (all subprocesses against a temp team dir, with a fake `claude` and `admiral` first on PATH):
- launch-teammate.sh with no ship: the argv the fake `claude --bg` recorded (the claude driver).
- launch-teammate.sh inside a ship: the argv of the fake `admiral crew launch` (the admiral driver, Claude arm).
- commodore's advisor-probe.sh, the claude driver's advisor-probe and the admiral driver's advisor-probe.

Every "flag left out" and "no probe started" assertion has a companion that shows the launch or the probe ran (the
`--bg` call with its `--model`, the admiral call with its `--model` arg, the printed result line).

Run from the repo root: python3 -m unittest evals/agent-teammates/test_advisor_family.py -v
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import CLAUDE_DRIVER, REPO, SCRIPTS, WorldCase, boat, rfc3339, split_launch

LAUNCH = SCRIPTS / "launch-teammate.sh"
CO_PROBE = REPO / "skills" / "engineering" / "commodore" / "scripts" / "advisor-probe.sh"
ADMIRAL_DRIVER = SCRIPTS / "drivers" / "admiral"

OK = 0

# (teammate model, ADVISOR, the flag is passed?)
FAMILY_CASES = [
    ("opus", "opus", False),
    ("sonnet", "sonnet", False),
    ("haiku", "haiku", False),
    ("fable", "fable", False),
    ("sonnet[1m]", "sonnet", False),
    ("claude-opus-5.5", "opus", False),
    ("claude-opus-5.5", "claude-opus-5.5", False),
    ("Opus", "opus", False),
    ("OPUS", "Opus", False),
    ("Claude-Sonnet-5.5", "SONNET", False),
    ("sonnet", "opus", True),
    ("haiku", "opus", True),
    ("claude-sonnet-5.5", "claude-opus-5.5", True),
    ("sonnet[1m]", "opus", True),
    # "Different family doesn't mean stronger": the flag is still passed, the preflight warns as today.
    ("opus", "haiku", True),
    ("opus", "sonnet", True),
    # A Fable teammate with ADVISOR=opus is a different family: the harness refuses it, the flag stays.
    ("fable", "opus", True),
    ("opus", "fable", True),
    # An unrecognised family on either side keeps the flag, even when the two strings are equal.
    ("gpt-9", "opus", True),
    ("opus", "mystery", True),
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
                # companion: the launch ran and chose this model
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

    def test_advisor_none_with_a_recognised_model_never_counts_as_same_family(self):
        # whatever the family check does with "none", the result is the same: no flag, and no stray "none" value
        argv = self.launch("opus", "none")
        self.assertEqual(value_after(self, argv, "--model"), "opus")
        self.assertNotIn("--advisor", argv)

    def test_same_family_launch_keeps_every_other_flag(self):
        argv = self.launch("opus", "opus")
        self.assertEqual(value_after(self, argv, "--permission-mode"), "auto")
        self.assertEqual(value_after(self, argv, "-n"), "alpha")
        self.assertNotIn("--advisor", argv)
        self.assertEqual(argv.count("opus"), 1, argv)  # the model's value only, no leftover advisor value

    def test_read_only_same_family_launch_leaves_the_flag_out_and_keeps_the_deny_list(self):
        self.w.write_team_env(extra=["ADVISOR=opus"])
        done = self.w.run(LAUNCH, "--read-only", "--model", "opus", self.w.team, "alpha", self.w.work, ship="")
        self.assertEqual(done.code, OK, done.text)
        argv = bg_call(self)
        self.assertIn("--disallowedTools", argv)
        self.assertEqual(value_after(self, argv, "--model"), "opus")
        self.assertNotIn("--advisor", argv)

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
        # companion: the launch ran, for this model, on the claude harness
        self.assertEqual(flags["--harness"], ["claude"])
        self.assertEqual(args[args.index("--model") + 1], "opus")
        self.assertNotIn("--advisor", args)
        self.assertEqual(args.count("opus"), 1, args)  # the model's value only, no leftover advisor value

    def test_sonnet_teammate_keeps_both_advisor_values_as_separate_arg_values(self):
        _, args = self.launch("sonnet", "opus")
        self.assertEqual(args[args.index("--advisor") + 1], "opus")
        self.assertEqual(args[args.index("--model") + 1], "sonnet")

    def test_admiral_argv_pairs_each_advisor_token_with_its_own_arg(self):
        self.launch("sonnet", "opus")
        argv = self.w.crew_calls("launch")[0]
        i = argv.index("--advisor")
        self.assertEqual(argv[i - 1], "--arg")
        self.assertEqual(argv[i + 1], "--arg")
        self.assertEqual(argv[i + 2], "opus")

    def test_admiral_argv_for_an_opus_teammate_has_no_advisor_token_at_all(self):
        self.launch("opus", "opus")
        argv = self.w.crew_calls("launch")[0]
        self.assertIn("--model", argv)
        self.assertNotIn("--advisor", argv)

    def test_family_rule_in_the_admiral_arm(self):
        for model, advisor, passed in FAMILY_CASES:
            with self.subTest(model=model, advisor=advisor):
                self.setUp()
                _, args = self.launch(model, advisor)
                self.assertEqual(args[args.index("--model") + 1], model)
                if passed:
                    self.assertEqual(args[args.index("--advisor") + 1], advisor)
                else:
                    self.assertNotIn("--advisor", args)

    def test_advisor_none_leaves_the_flag_out(self):
        _, args = self.launch("opus", "none")
        self.assertEqual(args[args.index("--model") + 1], "opus")
        self.assertNotIn("--advisor", args)

    def test_fable_teammate_with_advisor_opus_keeps_the_flag(self):
        _, args = self.launch("fable", "opus")
        self.assertEqual(args[args.index("--advisor") + 1], "opus")

    def test_read_only_same_family_launch_keeps_the_deny_list_and_drops_the_flag(self):
        _, args = self.launch("opus", "opus", "--read-only")
        self.assertIn("--disallowedTools", args)
        self.assertEqual(args[args.index("--model") + 1], "opus")
        self.assertNotIn("--advisor", args)


class ProbeCase(WorldCase):
    """The advisor probe, run for a model with ADVISOR in team.env. The fake claude records every call."""

    def probe(self, script, model, advisor="opus", *, trusted_dir=False, **env):
        self.w.write_team_env(extra=[f"ADVISOR={advisor}"])
        # World creates reports/ up front; take it away so the "no reports/ left behind" check means something.
        (self.w.team / "reports").rmdir()
        if trusted_dir:
            (self.w.team / "worktrees.tsv").write_text(f"u1 branch {self.w.work}\n")
        env.setdefault("ADVISOR_PROBE_TIMEOUT", "1")
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

    def test_claude_driver_probe_reports_same_family_without_a_session(self):
        self.assert_same_family(self.probe(CLAUDE_DRIVER / "advisor-probe", "opus"), "opus")

    def test_admiral_driver_probe_reports_same_family_without_a_session(self):
        self.assert_same_family(self.probe(ADMIRAL_DRIVER / "advisor-probe", "opus"), "opus")

    def test_the_check_comes_before_the_trusted_directory_lookup(self):
        # no worktrees.tsv and no WORKTREES_DIR: the lookup would print ADVISOR OFF if it ran first
        self.assert_same_family(self.probe(CO_PROBE, "opus", trusted_dir=False), "opus")

    def test_a_trusted_directory_does_not_start_a_session_either(self):
        self.assert_same_family(self.probe(CO_PROBE, "opus", trusted_dir=True), "opus")

    def test_the_model_is_echoed_as_given_for_a_suffixed_name(self):
        self.assert_same_family(self.probe(CO_PROBE, "sonnet[1m]", advisor="sonnet"), "sonnet[1m]")

    def test_the_model_is_echoed_as_given_for_a_full_name_in_mixed_case(self):
        self.assert_same_family(self.probe(CO_PROBE, "Claude-Opus-5.5", advisor="OPUS"), "Claude-Opus-5.5")

    def test_a_haiku_model_matches_its_own_family(self):
        self.assert_same_family(self.probe(CO_PROBE, "haiku", advisor="haiku"), "haiku")

    def test_a_fable_model_matches_its_own_family(self):
        self.assert_same_family(self.probe(CO_PROBE, "fable", advisor="fable"), "fable")


class TestDirectProbeOtherCases(ProbeCase):
    """Behaviour that must stay as it is: a different family, an unrecognised family and ADVISOR=none still probe."""

    def assert_not_same_family(self, done):
        self.assertEqual(done.code, OK, done.text)
        self.assertNotIn("SAME-FAMILY", done.out)
        # a probe result line of the existing kind
        self.assertRegex(done.out.splitlines()[-1], r"^ADVISOR (ON|OFF) ")

    def test_different_family_without_a_trusted_directory_still_reports_off(self):
        done = self.probe(CO_PROBE, "sonnet", advisor="opus")
        self.assert_not_same_family(done)
        self.assertTrue(done.out.splitlines()[-1].startswith("ADVISOR OFF sonnet: probe session couldn't start"))

    def test_different_family_with_a_trusted_directory_starts_a_session_with_the_advisor(self):
        done = self.probe(CO_PROBE, "sonnet", advisor="opus", trusted_dir=True)
        self.assert_not_same_family(done)
        bg = [c["argv"] for c in self.w.calls("claude") if "--bg" in c["argv"]]
        self.assertTrue(bg, "the probe started no session")
        self.assertEqual(value_after(self, bg[0], "--advisor"), "opus")
        self.assertEqual(value_after(self, bg[0], "--model"), "sonnet")

    def test_fable_model_with_advisor_opus_still_probes(self):
        done = self.probe(CO_PROBE, "fable", advisor="opus", trusted_dir=True)
        self.assert_not_same_family(done)
        self.assertTrue([c for c in self.w.calls("claude") if "--bg" in c["argv"]])

    def test_unrecognised_model_still_probes(self):
        done = self.probe(CO_PROBE, "mystery", advisor="opus", trusted_dir=True)
        self.assert_not_same_family(done)
        self.assertTrue([c for c in self.w.calls("claude") if "--bg" in c["argv"]])

    def test_advisor_none_is_not_a_same_family_match(self):
        done = self.probe(CO_PROBE, "opus", advisor="none", trusted_dir=True)
        self.assert_not_same_family(done)
        bg = [c["argv"] for c in self.w.calls("claude") if "--bg" in c["argv"]]
        self.assertTrue(bg)
        self.assertNotIn("--advisor", bg[0])


if __name__ == "__main__":
    unittest.main()
