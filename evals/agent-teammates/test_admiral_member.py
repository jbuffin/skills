"""Tests for launching a teammate as an Admiral crew member with launch-teammate.sh --member."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import USAGE_NO_MEMBER
from test_admiral_driver import FAILED, OK, USAGE, LaunchCase

# Admiral puts the last --arg right before the prompt, so a flag that takes several values must not end the list.
MULTI_VALUE_FLAGS = ("--disallowedTools", "--available-tools", "--deny-tool")


class MemberCase(LaunchCase):
    def refused(self, *opts, usage=False, **env):
        """A launch that exits 5 before Admiral launches anything, and before any harness runs."""
        done = self.launch(*opts, **env)
        self.assertEqual(done.code, USAGE, done.text)
        # the script's usage text is for a bad command line only; every other refusal says why
        self.assertEqual("usage:" in done.out, usage, done.text)
        self.assertEqual(self.w.crew_calls("launch"), [], self.w.admiral())
        for harness in ("claude", "codex", "copilot"):
            self.assertEqual(self.w.calls(harness), [], harness)
        self.assertEqual(self.w.registry(), [])
        return done

    def assert_ends_on_a_single_value_flag(self, args):
        flags = [i for i, a in enumerate(args) if a.startswith("-")]
        self.assertTrue(flags, args)
        self.assertEqual(len(args) - flags[-1], 2, f"the last flag must take one value: {args}")
        self.assertNotIn(args[flags[-1]], MULTI_VALUE_FLAGS, args)


class TestMemberArgv(MemberCase):
    def test_the_member_is_passed_to_admiral_and_no_model_is_named(self):
        _, _, flags, args = self.launched("--member", "crew-lead")
        self.assertEqual(flags["--member"], ["crew-lead"])
        self.assertNotIn("--role", flags)
        self.assertNotIn("--model", args)
        self.assertNotIn("--advisor", args)
        # the rest of the claude launch is as without a member
        self.assertEqual(self.value(args, "--permission-mode"), "auto")

    def test_the_team_wide_model_is_not_used_for_a_member(self):
        self.w.write_team_env(extra=["MODEL=opus"])
        _, _, _, args = self.launched("--member", "crew-lead")
        self.assertNotIn("--model", args)
        self.assertNotIn("opus", args)

    def test_an_explicit_model_is_kept_with_its_advisor(self):
        _, _, flags, args = self.launched("--member", "crew-lead", "--model", "haiku")
        self.assertEqual(flags["--member"], ["crew-lead"])
        self.assertEqual(self.value(args, "--model"), "haiku")
        self.assertEqual(self.value(args, "--advisor"), "opus")

    def test_member_with_a_role_passes_both_and_names_no_model_when_the_role_has_none(self):
        _, _, flags, args = self.launched("--member", "crew-lead", "--role", "scribe")
        self.assertEqual((flags["--member"], flags["--role"]), (["crew-lead"], ["scribe"]))
        self.assertNotIn("--model", args)

    def test_member_with_a_role_that_has_a_model_still_names_no_model(self):
        _, _, flags, args = self.launched("--member", "crew-lead", "--role", "test-writer")
        self.assertEqual(flags["--role"], ["test-writer"])
        self.assertNotIn("--model", args)
        self.assertNotIn("sonnet", args)

    def test_member_with_a_role_and_a_model_passes_the_model(self):
        _, _, _, args = self.launched("--member", "crew-lead", "--role", "test-writer", "--model", "haiku")
        self.assertEqual(self.value(args, "--model"), "haiku")

    def test_a_member_alone_satisfies_require_role(self):
        self.w.write_team_env(extra=["REQUIRE_ROLE=1"])
        done = self.launch("--member", "crew-lead")
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        self.assertEqual(len(self.w.crew_calls("launch")), 1)

    def test_a_member_in_the_callers_environment_is_not_inherited(self):
        self.w.write_team_env(extra=["REQUIRE_ROLE=0"])
        _, argv, _, _ = self.launched("--role", "test-writer", TEAMMATE_MEMBER="stale")
        self.assertNotIn("--member", argv)
        self.assertNotIn("stale", argv)

    def test_codex_without_a_model_passes_no_m(self):
        self.w.write_team_env(harness="codex")
        _, _, flags, args = self.launched("--member", "crew-lead")
        self.assertEqual(flags["--harness"], ["codex"])
        self.assertNotIn("-m", args)

    def test_copilot_without_a_model_passes_no_model_and_ends_on_a_single_value_flag(self):
        self.w.write_team_env(harness="copilot")
        _, _, flags, args = self.launched("--member", "crew-lead")
        self.assertEqual(flags["--harness"], ["copilot"])
        self.assertNotIn("--model", args)
        self.assert_ends_on_a_single_value_flag(args)

    def test_claude_read_only_under_autopilot_without_a_model_ends_on_a_single_value_flag(self):
        self.w.write_team_env(extra=["EFFORT_SCRIBE=high"])
        _, _, _, args = self.launched(
            "--member", "crew-lead", "--role", "scribe", "--read-only", ADMIRAL_AUTOPILOT="1"
        )
        self.assertIn("--disallowedTools", args)
        self.assertNotIn("--model", args)
        self.assertEqual(self.value(args, "--effort"), "high")
        self.assert_ends_on_a_single_value_flag(args)

    def test_claude_read_only_under_autopilot_without_a_model_or_effort_exits_5_naming_the_need(self):
        done = self.refused("--member", "crew-lead", "--read-only", ADMIRAL_AUTOPILOT="1")
        self.assertIn("--effort", done.out)


class TestMemberRefusals(MemberCase):
    def test_a_member_value_that_is_missing_empty_or_a_flag_prints_the_usage_and_exits_5(self):
        for value in ("", "-x"):
            with self.subTest(value=value):
                done = self.refused("--member", value, usage=True)
                self.assertIn("usage:", done.out)
                self.assertIn("--member", done.out)
        self.assertEqual(self.w.admiral(), [])

    def test_a_member_name_outside_admirals_rule_exits_5_before_any_launch(self):
        # a trailing '-' is fine for a role and not for a member
        for member in ("Lead_X", "lead-"):
            with self.subTest(member=member):
                self.refused("--member", member)

    def test_outside_a_ship_exits_5_naming_the_flag(self):
        done = self.refused("--member", "crew-lead", ship=None)
        self.assertIn("--member", done.out)
        self.assertEqual(self.w.admiral(), [])

    def test_a_codex_or_copilot_teammate_under_autopilot_exits_5_naming_the_flag(self):
        for harness in ("codex", "copilot"):
            with self.subTest(harness=harness):
                self.w.write_team_env(harness=harness)
                done = self.refused("--member", "crew-lead", ADMIRAL_AUTOPILOT="1")
                self.assertIn("--member", done.out)

    def test_a_read_only_codex_or_copilot_teammate_exits_5_naming_the_flag(self):
        for harness in ("codex", "copilot"):
            with self.subTest(harness=harness):
                self.w.write_team_env(harness=harness)
                done = self.refused("--member", "crew-lead", "--read-only")
                self.assertIn("--member", done.out)
        self.assertFalse((self.w.team / "admiral-delegated").exists())

    def test_an_admiral_without_member_exits_5_naming_the_flag_before_any_launch(self):
        self.w.ctl_write("usage.txt", USAGE_NO_MEMBER)
        done = self.refused("--member", "crew-lead")
        self.assertIn("--member", done.out)

    def test_an_admiral_without_member_still_launches_without_one(self):
        self.w.ctl_write("usage.txt", USAGE_NO_MEMBER)
        done = self.launch("--role", "test-writer")
        self.assertEqual((done.code, done.err), (OK, ""), done.text)

    def test_an_admiral_refusal_exits_1_with_admirals_message(self):
        self.w.ctl_write("launch.rc", "1")
        self.w.ctl_write("launch.msg", "admiral: crew member nobody not found\n")
        done = self.launch("--member", "nobody")
        self.assertEqual(done.code, FAILED, done.text)
        self.assertIn("crew member nobody not found", done.text)
        self.assertEqual(self.w.registry(), [])


if __name__ == "__main__":
    unittest.main()
