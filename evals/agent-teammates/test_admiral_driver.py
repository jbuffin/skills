"""Tests for the admiral driver (skills/engineering/agent-teammates/scripts/drivers/admiral/), Claude harness.

Seams: the shared scripts (launch-teammate.sh, retask.sh, watch-teammates.sh, close-teammate.sh, teammate-tail.sh)
and the driver's operations, run as subprocesses against a temp team dir. A fake `admiral` records its argv and stdin
and prints canned `crew list --json` and usage text; a fake `claude` keeps the real one out of reach. Expected argv
comes from Admiral's docs/cli.md at 992f678 and the engineer's decisions in u1-unit.md; the order of Admiral's own
flags (--name, --dir, --harness, --ship, --role) is left free because cli.md doesn't fix it.

Run from the repo root: python3 -m unittest evals/agent-teammates/test_admiral_driver.py -v
"""

import json
import os
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import ADMIRAL_DRIVER, SCRIPTS, SHIP, USAGE_OLD, WorldCase, boat

LAUNCH = SCRIPTS / "launch-teammate.sh"
RETASK = SCRIPTS / "retask.sh"
WATCH = SCRIPTS / "watch-teammates.sh"
CLOSE = SCRIPTS / "close-teammate.sh"
TAIL = SCRIPTS / "teammate-tail.sh"

OK = 0
FAILED = 1
USAGE = 5
NOT_LISTED = 3
FIELDS = 4


def rfc3339(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def first_prompt(name, prompt_file):
    return f"You are teammate {name}. Read {prompt_file} and do exactly what it says."


def split_launch(case, argv, name):
    """Admiral's own flags as a dict, the --arg values in order, and the prompt after the final `--`."""
    case.assertEqual(argv[:2], ["crew", "launch"])
    case.assertEqual(argv[-2], "--", argv)
    body, prompt = argv[2:-2], argv[-1]
    flags, args, i = {}, [], 0
    while i < len(body):
        case.assertTrue(body[i].startswith("--") and i + 1 < len(body), f"flag without a value at {i}: {argv}")
        (args if body[i] == "--arg" else flags.setdefault(body[i], [])).append(body[i + 1])
        i += 2
    case.assertEqual(prompt, first_prompt(name, case.w.team / "prompts" / f"{name}.md"))
    return flags, args


class LaunchCase(WorldCase):
    def setUp(self):
        super().setUp()
        self.w.prompt("alpha")
        # launch waits for the boat's first hook, so by default the boat it starts is already active
        self.w.boats(boat("alpha", last_activity=rfc3339(time.time())))

    def launch(self, *opts, name="alpha", **env):
        return self.w.run(LAUNCH, *opts, self.w.team, name, self.w.work, **env)

    def launched(self, *opts, **env):
        done = self.launch(*opts, **env)
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        calls = [a for a in self.w.admiral() if a[:2] == ["crew", "launch"]]
        self.assertEqual(len(calls), 1, self.w.admiral())
        flags, args = split_launch(self, calls[0], "alpha")
        return done, calls[0], flags, args

    def value(self, args, flag):
        """The value that follows `flag` as the next --arg."""
        self.assertIn(flag, args)
        return args[args.index(flag) + 1]


class TestLaunchArguments(LaunchCase):
    """ac1-launch, decisions 7, 8 and 10."""

    def test_admiral_flags_carry_name_dir_harness_ship_and_role(self):
        _, _, flags, _ = self.launched("--role", "test-writer")
        self.assertEqual(
            flags,
            {
                "--name": ["alpha"],
                "--dir": [str(self.w.work)],
                "--harness": ["claude"],
                "--ship": [SHIP],
                "--role": ["test-writer"],
            },
        )

    def test_ship_from_team_env_alone_still_names_the_ship(self):
        self.w.write_team_env(extra=[f"ADMIRAL_SHIP={SHIP}"])
        _, _, flags, _ = self.launched("--role", "test-writer", ship=None)
        self.assertEqual(flags["--ship"], [SHIP])

    def test_model_advisor_and_permission_mode_are_separate_arg_values(self):
        _, _, _, args = self.launched("--role", "test-writer")
        self.assertEqual(self.value(args, "--model"), "sonnet")
        self.assertEqual(self.value(args, "--advisor"), "opus")
        self.assertEqual(self.value(args, "--permission-mode"), "auto")
        self.assertEqual(len(args), 6, args)

    def test_model_flag_wins_over_the_role_model(self):
        _, _, _, args = self.launched("--role", "test-writer", "--model", "haiku")
        self.assertEqual(self.value(args, "--model"), "haiku")

    def test_advisor_none_leaves_out_the_advisor(self):
        self.w.write_team_env(extra=["ADVISOR=none"])
        _, _, _, args = self.launched("--role", "test-writer")
        self.assertNotIn("--advisor", args)
        self.assertNotIn("none", args)

    def test_configured_permission_mode_is_passed(self):
        self.w.write_team_env(extra=["PERMISSION_MODE=acceptEdits"])
        _, _, _, args = self.launched("--role", "test-writer")
        self.assertEqual(self.value(args, "--permission-mode"), "acceptEdits")

    def test_autopilot_leaves_out_the_permission_mode(self):
        _, _, _, args = self.launched("--role", "test-writer", ADMIRAL_AUTOPILOT="1")
        self.assertNotIn("--permission-mode", args)
        self.assertEqual(self.value(args, "--model"), "sonnet")

    def test_read_only_denies_edits_in_the_workdir_and_is_not_the_last_arg(self):
        _, _, _, args = self.launched("--read-only", "--role", "reviewer")
        denied = [f"Edit(/{self.w.work}/**)", f"NotebookEdit(/{self.w.work}/**)"]
        at = args.index("--disallowedTools")
        self.assertEqual(args[at + 1 : at + 3], denied)
        # Admiral puts the last --arg right before the prompt, so a flag has to follow the tool rules.
        self.assertGreater(len(args), at + 3, args)
        self.assertTrue(args[at + 3].startswith("-"), args)
        self.assertNotIn(args[-1], denied)

    def test_read_only_under_autopilot_still_ends_on_a_flag_value(self):
        _, _, _, args = self.launched("--read-only", "--role", "reviewer", ADMIRAL_AUTOPILOT="1")
        at = args.index("--disallowedTools")
        self.assertTrue(args[at + 3].startswith("-"), args)

    def test_launch_without_read_only_denies_nothing(self):
        _, _, _, args = self.launched("--role", "test-writer")
        self.assertNotIn("--disallowedTools", args)

    def test_prompt_follows_a_bare_double_dash_as_the_final_arguments(self):
        _, argv, _, _ = self.launched("--role", "test-writer")
        self.assertEqual(argv[-2:], ["--", first_prompt("alpha", self.w.team / "prompts/alpha.md")])
        self.assertEqual(argv.count("--"), 1)

    def test_no_background_flag_and_no_name_flag_for_the_harness(self):
        _, argv, _, _ = self.launched("--read-only", "--role", "reviewer")
        self.assertNotIn("--bg", argv)
        self.assertNotIn("-n", argv)

    def test_launch_without_role_passes_no_role(self):
        self.w.write_team_env(extra=["REQUIRE_ROLE=0"])
        _, argv, _, _ = self.launched()
        self.assertNotIn("--role", argv)

    def test_a_role_in_the_callers_environment_is_not_inherited(self):
        self.w.write_team_env(extra=["REQUIRE_ROLE=0"])
        _, argv, _, _ = self.launched(TEAMMATE_ROLE="stale")
        self.assertNotIn("--role", argv)
        self.assertNotIn("stale", argv)

    def test_driver_launch_reads_the_role_from_teammate_role(self):
        self.w.prompt("alpha")
        prompt = self.w.team / "prompts" / "alpha.md"
        done = self.w.run(
            ADMIRAL_DRIVER / "launch",
            self.w.team,
            "alpha",
            self.w.work,
            "sonnet",
            prompt,
            0,
            TEAMMATE_ROLE="test-writer",
        )
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(done.out.splitlines()[0], "alpha -")
        (call,) = [a for a in self.w.admiral() if a[:2] == ["crew", "launch"]]
        flags, _ = split_launch(self, call, "alpha")
        self.assertEqual(flags["--role"], ["test-writer"])

    def test_nothing_reaches_claude_or_a_viewer(self):
        self.launched("--role", "test-writer")
        self.assertEqual(self.w.calls("claude"), [])


class TestLaunchRegistration(LaunchCase):
    """decisions 7 and 9: the id is the crew name and there is no viewer."""

    def test_registry_row_uses_the_crew_name_as_session_id_and_no_viewer(self):
        done, _, _, _ = self.launched("--role", "test-writer")
        self.assertEqual([self.w.registry()[-1][i] for i in (0, 1, 3)], ["alpha", "alpha", "-"])
        self.assertTrue(done.out.startswith("launched alpha as background session alpha in "), done.out)
        self.assertNotIn("viewer", done.out)

    def test_tmux_and_cmux_viewers_are_ignored(self):
        for viewer in ("tmux", "cmux"):
            with self.subTest(viewer=viewer):
                self.w.write_team_env(extra=[f"VIEWER={viewer}"])
                self.launched(
                    "--role",
                    "test-writer",
                    TMUX="/tmp/tmux-0/default,1,0",
                    CMUX_WORKSPACE="workspace:1",
                    CMUX_BUNDLED_CLI_PATH=str(self.w.bin / "cmux"),
                )
                self.assertEqual(self.w.registry()[-1][3], "-")
                self.assertEqual(self.w.calls("tmux"), [])
                self.assertEqual(self.w.calls("cmux"), [])
                (self.w.ctl / "admiral.log").unlink()

    def test_a_refused_launch_registers_nothing(self):
        self.w.ctl_write("launch.rc", "1")
        done = self.launch("--role", "test-writer")
        self.assertEqual(done.code, FAILED)
        self.assertEqual(self.w.registry(), [])


class TestLaunchExitCodes(LaunchCase):
    """decision 11: Admiral's exit codes map to the contract's, and NO_BG never shows inside Admiral."""

    def refused(self, admiral_rc, message="admiral: boom\n"):
        self.w.ctl_write("launch.rc", str(admiral_rc))
        self.w.ctl_write("launch.msg", message)
        return self.launch("--role", "test-writer")

    def test_name_in_use_exits_5(self):
        done = self.refused(5, "admiral: crew boat alpha is in use\n")
        self.assertEqual(done.code, USAGE, done.text)

    def test_usage_error_or_no_ship_exits_5(self):
        done = self.refused(2, "admiral: not inside an Admiral ship\n")
        self.assertEqual(done.code, USAGE, done.text)

    def test_refusal_exits_1_with_admirals_message(self):
        done = self.refused(1, "admiral: --arg --settings is refused\n")
        self.assertEqual(done.code, FAILED, done.text)
        self.assertIn("--arg --settings is refused", done.text)

    def test_no_failure_prints_no_bg(self):
        for rc in (1, 2, 5):
            with self.subTest(admiral_rc=rc):
                done = self.refused(rc)
                self.assertEqual(len([a for a in self.w.admiral() if a[:2] == ["crew", "launch"]]), 1)
                self.assertNotIn("NO_BG", done.text)
                self.assertNotEqual(done.code, 2)
                (self.w.ctl / "admiral.log").unlink()

    def test_old_admiral_without_arg_refuses_with_5_and_names_the_version(self):
        self.w.ctl_write("usage.txt", USAGE_OLD)
        done = self.launch("--role", "test-writer")
        self.assertEqual(done.code, USAGE, done.text)
        self.assertIn("0.3.0", done.text)
        self.assertEqual([a for a in self.w.admiral() if a[:2] == ["crew", "launch"]], [])
        self.assertEqual(self.w.registry(), [])

    def test_names_outside_admirals_rule_exit_5_naming_the_rule(self):
        for bad in ("Alpha", "a_b", "a.b", "-alpha"):
            with self.subTest(name=bad):
                self.w.prompt(bad)
                done = self.launch("--role", "test-writer", name=bad)
                self.assertEqual(done.code, USAGE, done.text)
                self.assertIn("lowercase", done.text)
                self.assertEqual([a for a in self.w.admiral() if a[:2] == ["crew", "launch"]], [])

    def test_roles_outside_admirals_rule_exit_5_naming_the_rule(self):
        for bad in ("Test_Writer", "test.writer"):
            with self.subTest(role=bad):
                done = self.launch("--role", bad, "--model", "sonnet")
                self.assertEqual(done.code, USAGE, done.text)
                self.assertIn("lowercase", done.text)
                self.assertEqual([a for a in self.w.admiral() if a[:2] == ["crew", "launch"]], [])

    def test_the_driver_itself_refuses_a_bad_name(self):
        prompt = self.w.team / "prompts" / "alpha.md"
        done = self.w.run(ADMIRAL_DRIVER / "launch", self.w.team, "Bad_Name", self.w.work, "sonnet", prompt, 0)
        self.assertEqual(done.code, USAGE, done.text)
        self.assertIn("lowercase", done.text)


class TestLaunchWait(LaunchCase):
    """A launch reports success only after the boat's first hook (last_activity), as the claude driver fails fast on an
    untrusted folder."""

    def closes(self):
        return [a for a in self.w.admiral() if a[:2] == ["crew", "close"]]

    def test_waits_for_the_first_hook_then_succeeds(self):
        quiet, active = [boat("alpha")], [boat("alpha", last_activity=rfc3339(time.time()))]
        self.w.boats_over_time(quiet, active)
        done = self.launch("--role", "test-writer", LAUNCH_POLL="0")
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        self.assertEqual(done.out.splitlines()[0], "launched alpha as background session alpha in " + str(self.w.work))
        self.assertEqual(len([a for a in self.w.admiral() if a[:2] == ["crew", "list"]]), 2)
        self.assertEqual(self.closes(), [])

    def test_no_activity_in_time_closes_the_boat_and_exits_5(self):
        self.w.boats(boat("alpha"))
        done = self.launch("--role", "test-writer", LAUNCH_WAIT="0", LAUNCH_POLL="0")
        self.assertEqual(done.code, USAGE, done.text)
        self.assertIn("alpha showed no activity within 0s", done.text)
        self.assertIn("startup prompt", done.text)
        self.assertIn(f"Run the dock's harness once in {self.w.work}", done.text)
        self.assertEqual(len(self.closes()), 1)
        self.assertEqual(self.closes()[0][:3], ["crew", "close", "alpha"])
        self.assertEqual(self.w.registry(), [])
        self.assertNotIn("alpha -", done.out)

    def test_wait_settings_come_from_team_env(self):
        self.w.boats(boat("alpha"))
        self.w.write_team_env(extra=["LAUNCH_WAIT=0", "LAUNCH_POLL=0"])
        done = self.launch("--role", "test-writer")
        self.assertEqual(done.code, USAGE, done.text)

    def test_a_boat_that_exits_during_startup_closes_and_exits_1(self):
        self.w.boats(boat("alpha", "anchored"))
        done = self.launch("--role", "test-writer", LAUNCH_POLL="0")
        self.assertEqual(done.code, FAILED, done.text)
        self.assertIn("alpha exited during startup", done.text)
        self.assertEqual(len(self.closes()), 1)
        self.assertEqual(self.w.registry(), [])

    def test_a_boat_missing_from_the_listing_exits_1(self):
        self.w.boats()
        done = self.launch("--role", "test-writer", LAUNCH_POLL="0")
        self.assertEqual(done.code, FAILED, done.text)
        self.assertIn("exited during startup", done.text)


class TestSend(WorldCase):
    """ac2-send, decision 12."""

    def setUp(self):
        super().setUp()
        self.w.register("alpha", epoch=1000)
        self.msg = self.w.message("a long job\nwith lines\n")

    def retask(self):
        return self.w.run(RETASK, self.w.team, "alpha", self.msg)

    def sends(self):
        return [c for c in self.w.calls("admiral") if c["argv"][:2] == ["crew", "send"]]

    def test_sends_a_pointer_on_stdin_not_the_message_on_the_command_line(self):
        done = self.retask()
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        self.assertEqual(done.out.strip(), "alpha re-tasked (session alpha)")
        (call,) = self.sends()
        self.assertEqual(call["argv"][:3], ["crew", "send", "alpha"])
        extra = call["argv"][3:]
        self.assertIn(extra, ([], ["--ship", SHIP]))
        self.assertEqual(
            call["stdin"].rstrip("\n"), f"You are teammate alpha. Read {self.msg} and do exactly what it says."
        )
        self.assertNotIn("a long job", " ".join(call["argv"]))

    def test_a_successful_send_resets_the_watchdog_clock(self):
        before = int(time.time())
        self.retask()
        row = self.w.registry()[-1]
        self.assertEqual(row[:2], ["alpha", "alpha"])
        self.assertGreaterEqual(int(row[2]), before)

    def test_anchored_boat_exit_4_becomes_1_and_records_nothing(self):
        self.w.ctl_write("send.rc", "4")
        self.w.ctl_write("send.msg", "admiral: alpha is anchored\n")
        done = self.retask()
        self.assertEqual(done.code, FAILED, done.text)
        self.assertEqual(len(self.w.registry()), 1)

    def test_other_send_failures_exit_nonzero_and_record_nothing(self):
        self.w.ctl_write("send.rc", "1")
        done = self.retask()
        self.assertEqual(len(self.sends()), 1)
        self.assertNotEqual(done.code, OK)
        self.assertEqual(len(self.w.registry()), 1)

    def test_driver_send_maps_exit_4_to_1(self):
        self.w.ctl_write("send.rc", "4")
        done = self.w.run(ADMIRAL_DRIVER / "send", self.w.team, "alpha", self.msg)
        self.assertEqual(done.code, FAILED, done.text)


class TestStatus(WorldCase):
    """ac3-status, decision 13."""

    def status_lines(self):
        done = self.w.run(ADMIRAL_DRIVER / "status", self.w.team)
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        return {line.split()[0]: line.split() for line in done.out.splitlines()}

    def test_states_map_and_the_epoch_comes_from_last_activity(self):
        for name in ("a", "b", "c", "d"):
            self.w.register(name)
        self.w.boats(
            boat("a", "underway", last_activity="2026-10-25T10:00:00Z"),
            boat("b", "needs_you", last_activity="2026-10-25T10:00:00Z"),
            boat("c", "anchored", last_activity="2026-10-25T10:00:00Z"),
            boat("d", "underway", last_activity=None),
        )
        rows = self.status_lines()
        self.assertEqual([rows[n][0] for n in "abcd"], list("abcd"))
        self.assertEqual([rows[n][2] for n in "abcd"], ["working", "blocked", "stopped", "working"])
        self.assertEqual([rows[n][3] for n in "abcd"], ["1792922400"] * 3 + ["-"])
        self.assertTrue(all(len(r) == FIELDS for r in rows.values()), rows)

    def test_the_listing_asks_admiral_for_json(self):
        self.w.register("a")
        self.status_lines()
        listing = [a for a in self.w.admiral() if a[:2] == ["crew", "list"]]
        self.assertTrue(listing and "--json" in listing[0], self.w.admiral())

    def test_a_registered_boat_missing_from_the_listing_is_not_alive(self):
        self.w.register("gone")
        self.w.register("here")
        self.w.boats(boat("here", "underway"))
        rows = self.status_lines()
        self.assertEqual(rows["here"][2], "working")
        # missing is printed as `missing`, or not printed (the watchdog counts a missing row as missing)
        self.assertIn(rows.get("gone", [None, None, "missing"])[2], ("missing",))

    def test_a_failed_listing_exits_3_with_no_output(self):
        self.w.register("a")
        self.w.ctl_write("list.rc", "1")
        done = self.w.run(ADMIRAL_DRIVER / "status", self.w.team)
        self.assertEqual((done.code, done.out), (NOT_LISTED, ""))

    def test_unparseable_listing_exits_3_with_no_output(self):
        self.w.register("a")
        self.w.ctl_write("list.json", "this is not json")
        done = self.w.run(ADMIRAL_DRIVER / "status", self.w.team)
        self.assertEqual((done.code, done.out), (NOT_LISTED, ""))


class TestWatch(WorldCase):
    """ac3-status through watch-teammates.sh, one poll."""

    def watch(self):
        done = self.w.run(WATCH, "--until-event", 1, self.w.team)
        self.assertEqual(done.code, OK, done.text)
        return done.out.splitlines()

    def mark_done(self, name, mtime=None):
        marker = self.w.team / "reports" / f"{name}.done"
        marker.touch()
        if mtime is not None:
            os.utime(marker, (mtime, mtime))

    def test_done_marker_reports_done_even_though_the_boat_is_anchored(self):
        self.w.register("alpha", epoch=int(time.time()) - 600)
        self.w.boats(boat("alpha", "anchored"))
        self.mark_done("alpha")
        self.assertEqual(self.watch(), ["DONE alpha"])
        self.assertIn(["crew", "list"], [a[:2] for a in self.w.admiral()])

    def test_an_anchored_boat_without_a_marker_is_gone(self):
        self.w.register("alpha")
        self.w.boats(boat("alpha", "anchored"))
        self.assertEqual(self.watch(), ["GONE alpha alpha stopped"])

    def test_a_boat_missing_from_the_listing_is_gone(self):
        self.w.register("alpha")
        self.w.boats()
        self.assertEqual(self.watch(), ["GONE alpha alpha missing"])
        self.assertIn(["crew", "list"], [a[:2] for a in self.w.admiral()])

    def test_a_boat_that_needs_you_is_blocked_on_the_second_poll(self):
        self.w.register("alpha")
        self.w.boats(boat("alpha", "needs_you", last_activity=rfc3339(time.time() - 60)))
        self.assertEqual(self.watch(), ["WATCH timeout 1"])
        self.assertEqual(self.watch(), ["BLOCKED alpha alpha"])

    def test_a_quiet_working_boat_stalls(self):
        self.w.register("alpha")
        self.w.boats(boat("alpha", "underway", last_activity=rfc3339(time.time() - 30 * 60)))
        (line,) = self.watch()
        self.assertTrue(line.startswith("STALL alpha alpha "), line)

    def test_a_boat_with_no_hook_yet_never_stalls(self):
        self.w.register("alpha")
        self.w.boats(boat("alpha", "underway", last_activity=None))
        self.assertEqual(self.watch(), ["WATCH timeout 1"])

    def test_a_busy_boat_is_quiet(self):
        self.w.register("alpha")
        self.w.boats(boat("alpha", "underway", last_activity=rfc3339(time.time() - 30)))
        self.assertEqual(self.watch(), ["WATCH timeout 1"])


class TestStop(WorldCase):
    """ac4-stop, decision 14."""

    def setUp(self):
        super().setUp()
        self.w.register("alpha")

    def closes(self):
        return [a for a in self.w.admiral() if a[:2] == ["crew", "close"]]

    def stop(self):
        return self.w.run(ADMIRAL_DRIVER / "stop", self.w.team, "alpha")

    def test_close_teammate_lists_then_closes_the_boat(self):
        self.w.boats(boat("alpha", "underway"))
        done = self.w.run(CLOSE, self.w.team, "alpha")
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(done.out.splitlines()[0], "stopped alpha (alpha)")
        calls = self.w.admiral()
        kinds = [c[:2] for c in calls]
        self.assertEqual(kinds[:1] + kinds[-1:], [["crew", "list"], ["crew", "close"]], calls)
        self.assertEqual(self.closes()[0][:3], ["crew", "close", "alpha"])
        self.assertEqual(self.w.registry()[-1][2], "closed")

    def test_underway_and_needs_you_exit_0(self):
        for state in ("underway", "needs_you"):
            with self.subTest(state=state):
                self.w.boats(boat("alpha", state))
                self.assertEqual(self.stop().code, OK)
        self.assertEqual(len(self.closes()), 2)

    def test_an_anchored_boat_is_closed_but_exits_nonzero(self):
        self.w.boats(boat("alpha", "anchored"))
        self.assertNotEqual(self.stop().code, OK)
        self.assertEqual(len(self.closes()), 1)

    def test_close_teammate_still_marks_an_anchored_boat_closed(self):
        self.w.boats(boat("alpha", "anchored"))
        done = self.w.run(CLOSE, self.w.team, "alpha")
        self.assertIn("alpha (alpha) was not running", done.out)
        self.assertEqual(self.w.registry()[-1][2], "closed")

    def test_an_unlisted_boat_exits_nonzero_and_closes_nothing(self):
        self.w.boats(boat("someone-else", "underway"))
        self.assertNotEqual(self.stop().code, OK)
        self.assertIn(["crew", "list"], [a[:2] for a in self.w.admiral()])
        self.assertEqual(self.closes(), [])

    def test_nothing_reaches_claude(self):
        self.w.boats(boat("alpha", "underway"))
        self.assertEqual(self.stop().code, OK)
        self.assertEqual(self.w.calls("claude"), [])


class TestDeferred(WorldCase):
    """ac5-defer, decisions 15 and 16."""

    def transcript(self, lines):
        path = self.w.root / "cfg" / "projects" / "-some-project" / "sess-abc123.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return path

    @staticmethod
    def tool(command):
        return {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}]},
        }

    @staticmethod
    def said(text):
        return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}

    def test_tail_reads_the_transcript_the_listing_names(self):
        path = self.transcript([self.tool("ls one"), self.tool("ls two"), self.tool("ls three"), self.said("all done")])
        self.w.register("alpha")
        self.w.boats(boat("alpha", "underway", transcript=str(path)))
        done = self.w.run(TAIL, self.w.team, "alpha", 2)
        self.assertEqual(done.code, OK, done.text)
        lines = done.out.splitlines()
        self.assertTrue(lines[0].startswith(f"transcript: {path}"), lines)
        self.assertEqual(lines[1:], ["TOOL  Bash: ls two", "TOOL  Bash: ls three", "SAID  all done"])

    def test_tail_uses_the_transcripts_config_dir_not_the_one_in_team_env(self):
        path = self.transcript([self.tool("ls one"), self.said("all done")])
        other = self.w.root / "coordinator-cfg"
        (other / "projects").mkdir(parents=True)
        self.w.write_team_env(extra=[f"CLAUDE_CONFIG_DIR={other}"])
        self.w.register("alpha")
        self.w.boats(boat("alpha", "underway", transcript=str(path)))
        done = self.w.run(TAIL, self.w.team, "alpha", 2)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(done.out.splitlines()[1:], ["TOOL  Bash: ls one", "SAID  all done"])

    def test_tail_without_a_recorded_transcript_says_so_and_fails(self):
        self.w.register("alpha")
        self.w.boats(boat("alpha", "underway", transcript=None))
        done = self.w.run(TAIL, self.w.team, "alpha")
        self.assertIn(["crew", "list"], [a[:2] for a in self.w.admiral()])
        self.assertNotEqual(done.code, OK)
        self.assertIn("transcript", done.text.lower())

    def test_tail_of_an_unlisted_boat_fails(self):
        self.w.register("alpha")
        self.w.boats()
        done = self.w.run(TAIL, self.w.team, "alpha")
        self.assertIn(["crew", "list"], [a[:2] for a in self.w.admiral()])
        self.assertNotEqual(done.code, OK)

    def test_has_skill_and_list_skills_follow_the_claude_driver(self):
        skill = self.w.checkout / ".claude" / "skills" / "local-skill" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: local-skill\ndescription: x\n---\n")
        self.assertEqual(self.w.run(ADMIRAL_DRIVER / "has-skill", self.w.team, "local-skill").code, OK)
        self.assertEqual(self.w.run(ADMIRAL_DRIVER / "has-skill", self.w.team, "no-such-skill").code, FAILED)
        listed = self.w.run(ADMIRAL_DRIVER / "list-skills", self.w.team)
        self.assertEqual(listed.code, OK, listed.text)
        self.assertIn(f"local-skill\t{skill}", listed.out.splitlines())
        self.assertIn("simplify\t-", listed.out.splitlines())

    def test_advisor_probe_runs_the_claude_probe_which_gives_up_without_a_trusted_directory(self):
        done = self.w.run(ADMIRAL_DRIVER / "advisor-probe", self.w.team, "sonnet")
        self.assertEqual(done.code, OK, done.text)
        self.assertTrue(
            done.out.splitlines()[-1].startswith("ADVISOR OFF sonnet: probe session couldn't start"), done.out
        )
        self.assertEqual(self.w.admiral(), [])

    def test_driver_env_declares_live_messaging_and_script_send(self):
        env_file = ADMIRAL_DRIVER / "driver.env"
        self.assertTrue(env_file.is_file(), f"{env_file} is missing")
        declared = dict(
            line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line and not line.startswith("#")
        )
        self.assertEqual(declared["LIVE_MESSAGING"], "1")
        self.assertEqual(declared["SEND"], "script")
        self.assertIn(declared.get("SKILL_PREFIX", "/"), ("/",))


class TestHarnessAdmiral(LaunchCase):
    """`admiral` is a host driver, not a harness: HARNESS=admiral exits 5 at once instead of looping."""

    def setUp(self):
        super().setUp()
        self.w.write_team_env(harness="admiral")
        self.w.register("alpha")

    def refused(self, done):
        self.assertEqual(done.code, USAGE, done.text)
        self.assertIn("admiral is a host driver, not a harness", done.text)

    def test_launch_refuses(self):
        self.refused(self.launch("--role", "test-writer"))
        self.assertEqual([a for a in self.w.admiral() if a[:2] == ["crew", "launch"]], [])

    def test_deferred_operations_refuse(self):
        for op, args in (("has-skill", ("x",)), ("list-skills", ()), ("advisor-probe", ("sonnet",))):
            with self.subTest(op=op):
                self.refused(self.w.run(ADMIRAL_DRIVER / op, self.w.team, *args, timeout=20))

    def test_tail_refuses(self):
        self.refused(self.w.run(TAIL, self.w.team, "alpha", timeout=20))


class TestPreflight(WorldCase):
    """decision 17."""

    def preflight(self, **env):
        return self.w.run(ADMIRAL_DRIVER / "preflight", self.w.team, **env)

    def test_all_checks_pass_and_claudes_trust_warning_is_kept(self):
        done = self.preflight()
        self.assertEqual(done.code, OK, done.text)
        self.assertNotIn("FAIL", done.out)
        self.assertRegex(done.out, r"(?m)^OK +claude found")
        self.assertRegex(done.out, r"(?m)^WARN .*not marked trusted")

    def test_the_ship_is_checked_with_crew_list(self):
        self.preflight()
        listing = [a for a in self.w.admiral() if a[:2] == ["crew", "list"]]
        self.assertTrue(listing, self.w.admiral())
        argv = listing[-1]
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("--ship") + 1], SHIP)

    def test_claudes_agents_failure_is_not_reported(self):
        self.w.ctl_write("claude-agents.rc", "1")
        done = self.preflight()
        self.assertEqual(done.code, OK, done.text)
        self.assertNotIn("FAIL", done.out)
        self.assertNotIn("in-process", done.out)

    def test_old_admiral_fails_naming_the_version(self):
        self.w.ctl_write("usage.txt", USAGE_OLD)
        done = self.preflight()
        self.assertEqual(done.code, FAILED, done.text)
        self.assertRegex(done.out, r"(?m)^FAIL .*0\.3\.0")

    def test_an_unlistable_ship_fails(self):
        self.w.ctl_write("list.rc", "1")
        done = self.preflight()
        self.assertEqual(done.code, FAILED, done.text)
        self.assertRegex(done.out, r"(?m)^FAIL ")

    def test_admiral_missing_from_path_fails(self):
        (self.w.bin / "admiral").unlink()
        done = self.preflight()
        self.assertEqual(done.code, FAILED, done.text)
        self.assertRegex(done.out, r"(?m)^FAIL .*admiral")


if __name__ == "__main__":
    unittest.main()
