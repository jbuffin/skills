"""Codex and Copilot teammates in an Admiral ship: writers are crew boats, read-only teammates run headless."""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import ADMIRAL_DRIVER, SCRIPTS, WorldCase, boat, rfc3339, split_launch

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

COPILOT_TOOLS = ["bash", "view", "edit", "create", "glob", "grep"]
COPILOT_DENIES = [
    "shell(git push:*)",
    "shell(gh pr merge:*)",
    "shell(gh pr create:*)",
    "shell(gh api:*)",
    "shell(gh issue:*)",
]


def unquoted(value):
    """A -c value as codex reads it: TOML, or the raw string when that fails, so quotes don't matter."""
    return value.replace('"', "")


def flag_groups(args):
    """{flag: [values]} for an --arg list: a token that starts with '-' opens a group, the tokens after it fill it."""
    groups, order, current = {}, [], None
    for token in args:
        if token.startswith("-"):
            current = token
            order.append(token)
            groups.setdefault(token, [])
            groups[token].append([])
        else:
            groups[current][-1].append(token)
    return groups, order


class LaunchCase(WorldCase):
    """A harness's launch inside the ship; the boat it starts is already active (launch waits for the first hook)."""

    harness = "codex"

    def setUp(self):
        super().setUp()
        self.w.write_team_env(harness=self.harness, extra=self.team_extra())
        self.w.prompt("alpha")
        self.w.boats(boat("alpha", last_activity=rfc3339(time.time())))

    def team_extra(self):
        return []

    def launch(self, *opts, name="alpha", **env):
        return self.w.run(LAUNCH, *opts, self.w.team, name, self.w.work, **env)

    def crew_launched(self, *opts, **env):
        done = self.launch(*opts, **env)
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        calls = self.w.crew_calls("launch")
        self.assertEqual(len(calls), 1, self.w.admiral())
        flags, args = split_launch(self, calls[0], "alpha")
        return done, calls[0], flags, args


class TestCodexWriterLaunch(LaunchCase):
    """A Codex writer is a crew boat; the --arg values are the interactive flags, in order."""

    harness = "codex"

    def test_arg_values_in_order_without_an_effort(self):
        self.w.write_team_env(harness="codex", extra=["MODEL_TEST_WRITER=gpt-5.5"])
        _, _, _, args = self.crew_launched("--role", "test-writer")
        self.assertEqual(
            args,
            [
                "-s",
                "workspace-write",
                "-c",
                "sandbox_workspace_write.network_access=true",
                "--add-dir",
                f"{self.w.team}/reports",
                "-m",
                "gpt-5.5",
                "-a",
                "never",
            ],
        )
        self.assertEqual(self.w.calls("codex"), [])
        self.assertEqual([self.w.registry()[-1][i] for i in (0, 1, 3)], ["alpha", "alpha", "-"])
        self.assertFalse((self.w.team / "admiral-delegated").exists())

    def test_arg_values_in_order_with_an_effort(self):
        self.w.write_team_env(harness="codex", extra=["MODEL_TEST_WRITER=gpt-5.5", "EFFORT_TEST_WRITER=high"])
        _, _, _, args = self.crew_launched("--role", "test-writer")
        self.assertEqual(
            [unquoted(a) for a in args],
            [
                "-s",
                "workspace-write",
                "-c",
                "sandbox_workspace_write.network_access=true",
                "--add-dir",
                f"{self.w.team}/reports",
                "-m",
                "gpt-5.5",
                "-c",
                "model_reasoning_effort=high",
                "-a",
                "never",
            ],
        )


class TestCopilotWriterLaunch(LaunchCase):
    """A Copilot writer is a crew boat; the list ends on --model, a single-value flag, before the prompt."""

    harness = "copilot"

    def groups(self, *opts, **env):
        _, _, _, args = self.crew_launched("--role", "test-writer", *opts, **env)
        return args, *flag_groups(args)

    def test_the_writer_flags_without_an_effort(self):
        self.w.write_team_env(harness="copilot", extra=["MODEL_TEST_WRITER=gpt-5.5"])
        args, groups, _ = self.groups()
        self.assertEqual(
            sorted(groups),
            ["--add-dir", "--allow-all-tools", "--available-tools", "--deny-tool", "--model", "--no-ask-user"],
        )
        self.assertEqual(groups["--no-ask-user"], [[]])
        self.assertEqual(groups["--allow-all-tools"], [[]])
        self.assertEqual(groups["--available-tools"], [COPILOT_TOOLS])
        self.assertEqual(groups["--deny-tool"], [COPILOT_DENIES])
        self.assertEqual(groups["--model"], [["gpt-5.5"]])
        self.assertEqual(args[-2:], ["--model", "gpt-5.5"])
        self.assertEqual(self.w.calls("copilot"), [])

    def test_an_effort_adds_reasoning_effort(self):
        self.w.write_team_env(harness="copilot", extra=["MODEL_TEST_WRITER=gpt-5.5", "EFFORT_TEST_WRITER=high"])
        args, groups, _ = self.groups()
        self.assertEqual(groups["--reasoning-effort"], [["high"]])
        self.assertEqual(args[-2:], ["--model", "gpt-5.5"])

    def test_no_effort_passes_no_reasoning_effort(self):
        _, groups, _ = self.groups()
        self.assertNotIn("--reasoning-effort", groups)

    def test_add_dir_has_the_team_dir_and_the_scripts_dir_and_the_extra_dirs(self):
        extra = self.w.root / "preflight-scripts"
        extra.mkdir()
        self.w.write_team_env(harness="copilot", extra=[f"PREFLIGHT_SCRIPTS={extra}"])
        _, groups, _ = self.groups()
        dirs = [d for values in groups["--add-dir"] for d in values]
        self.assertEqual(len(dirs), len(set(dirs)), dirs)
        self.assertIn(str(self.w.team), dirs)
        self.assertIn(str(SCRIPTS), dirs)
        self.assertIn(str(extra), dirs)

    def test_an_effort_with_the_wrong_shape_exits_5_before_any_launch(self):
        self.w.write_team_env(harness="copilot", extra=["EFFORT_TEST_WRITER='hi gh'"])
        done = self.launch("--role", "test-writer")
        self.assertEqual(done.code, USAGE, done.text)
        self.assertEqual(self.w.crew_calls("launch"), [])


class ReadOnlyDelegation:
    """A read-only teammate on Codex or Copilot runs headless under its harness driver; `launch` records its id in
    <team>/admiral-delegated, and send, stop, status and tail route by that id."""

    harness = None

    def setUp(self):
        super().setUp()
        self.w.write_team_env(harness=self.harness, extra=["MODEL_REVIEWER=gpt-5.5", "EFFORT_REVIEWER=high"])
        self.w.prompt("alpha")
        self.w.boats()
        # a fake kept alive by <tool>.sleep must not outlive a test that failed before it stopped the teammate
        self.addCleanup(lambda: self.w.run(CLOSE, self.w.team, "alpha"))

    # per-harness knowledge
    def assert_headless_argv(self, argv):
        raise NotImplementedError

    def assert_resumed(self, argv, delegated_id):
        raise NotImplementedError

    @property
    def tool(self):
        return self.harness

    def delegate(self, name="alpha", **env):
        done = self.w.run(LAUNCH, "--read-only", "--role", "reviewer", self.w.team, name, self.w.work, **env)
        self.assertEqual(done.code, OK, done.text)
        delegated_id = self.w.registry()[-1][1]
        # the admiral driver's launch recorded the id it handed over
        self.assertEqual(self.delegated_file()[-1:], [delegated_id], self.delegated_file())
        return done, delegated_id

    def delegated_file(self):
        path = self.w.team / "admiral-delegated"
        return path.read_text().splitlines() if path.exists() else []

    def wait_idle(self, name="alpha"):
        """The run's own wrapper writes the report after the fake exits; wait for its marker and a `done` status."""
        self.assertTrue(self.w.wait_for(self.w.team / "reports" / f"{name}.done"), "no .done marker")
        delegated_id, deadline = self.delegated_file()[-1], time.time() + 10
        while self.status_rows().get(delegated_id, [None] * 3)[2] != "done" and time.time() < deadline:
            time.sleep(0.05)

    def status_rows(self):
        done = self.w.run(ADMIRAL_DRIVER / "status", self.w.team)
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        return {line.split()[0]: line.split() for line in done.out.splitlines()}

    def retask_when_idle(self, name="alpha"):
        msg = self.w.message("second job\n")
        for _ in range(40):
            done = self.w.run(RETASK, self.w.team, name, msg)
            if "still running" not in done.text:
                return done
            time.sleep(0.25)
        return done

    def test_launch_runs_the_harness_driver_headless_and_calls_admiral_for_nothing(self):
        done, delegated_id = self.delegate()
        self.assertEqual(self.w.admiral(), [])
        self.assertTrue(self.w.wait_finished(self.tool))
        (call,) = self.w.calls(self.tool)
        self.assert_headless_argv(call["argv"])
        self.assertIn("high", " ".join(call["argv"]))
        self.assertTrue(done.out.startswith(f"launched alpha as background session {delegated_id} in "), done.out)

    # send
    def test_send_goes_to_the_harness_driver_not_to_crew_send(self):
        _, delegated_id = self.delegate()
        self.wait_idle()
        done = self.retask_when_idle()
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(self.w.crew_calls("send"), [])
        self.assertTrue(self.w.wait_finished(self.tool, 2))
        self.assert_resumed(self.w.calls(self.tool)[1]["argv"], delegated_id)


class TestCodexReadOnlyDelegation(ReadOnlyDelegation, WorldCase):
    harness = "codex"

    def assert_headless_argv(self, argv):
        self.assertEqual(argv[:1], ["exec"])
        self.assertIn("--json", argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertIn("--ignore-rules", argv)

    def assert_resumed(self, argv, delegated_id):
        self.assertEqual(argv[:2], ["exec", "resume"])
        self.assertIn(delegated_id, argv)

    def test_the_read_only_teammate_still_writes_its_report(self):
        self.delegate()
        self.wait_idle()
        self.assertEqual((self.w.team / "reports" / "alpha.md").read_text().strip(), f"{self.tool} report text")

    def test_a_name_and_role_admiral_would_refuse_still_launch(self):
        self.w.write_team_env(harness=self.harness, extra=["MODEL_ODD_ROLE=gpt-5.5"])
        self.w.prompt("Mixed_Case.1")
        done = self.w.run(LAUNCH, "--read-only", "--role", "Odd_Role", self.w.team, "Mixed_Case.1", self.w.work)
        self.assertEqual(done.code, OK, done.text)
        self.assertNotIn("lowercase", done.text)
        self.assertEqual(self.w.admiral(), [])
        self.assertEqual(self.delegated_file()[-1:], [self.w.registry()[-1][1]])

    def test_a_failed_harness_launch_records_nothing(self):
        _, first = self.delegate()
        self.w.prompt("beta")
        (self.w.bin / self.tool).unlink()
        done = self.w.run(LAUNCH, "--read-only", "--role", "reviewer", self.w.team, "beta", self.w.work)
        self.assertNotEqual(done.code, OK)
        self.assertEqual(self.delegated_file(), [first])
        self.assertEqual([row[0] for row in self.w.registry()], ["alpha"])

    def test_a_writer_launched_beside_it_is_not_delegated(self):
        _, delegated_id = self.delegate()
        self.w.prompt("beta")
        self.w.boats(boat("beta", last_activity=rfc3339(time.time())))
        done = self.w.run(LAUNCH, "--role", "test-writer", self.w.team, "beta", self.w.work)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(len(self.w.crew_calls("launch")), 1)
        self.assertEqual(self.delegated_file(), [delegated_id])

    def test_stop_and_close_go_to_the_harness_driver_and_close_no_boat(self):
        self.w.ctl_write(f"{self.tool}.sleep", "20")
        _, delegated_id = self.delegate()
        done = self.w.run(ADMIRAL_DRIVER / "stop", self.w.team, delegated_id)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(self.status_rows()[delegated_id][2], "stopped")
        done = self.w.run(CLOSE, self.w.team, "alpha")
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(self.w.crew_calls("close"), [])

    def test_status_prints_the_boats_and_then_the_delegated_teammate(self):
        _, delegated_id = self.delegate()
        self.w.register("beta")
        self.w.boats(boat("beta", "underway", last_activity="2026-10-25T10:00:00Z"))
        self.wait_idle()
        rows = self.status_rows()
        self.assertEqual(rows["beta"][2:], ["working", "1792922400"])
        self.assertEqual(rows[delegated_id][2], "done", rows)
        self.assertTrue(all(len(r) == FIELDS for r in rows.values()), rows)
        out = self.w.run(ADMIRAL_DRIVER / "status", self.w.team).out.splitlines()
        self.assertEqual(len([line for line in out if line.startswith(delegated_id)]), 1, out)

    def test_a_working_delegated_teammate_reads_as_working(self):
        self.w.ctl_write(f"{self.tool}.sleep", "20")
        _, delegated_id = self.delegate()
        self.w.boats()
        self.assertEqual(self.status_rows()[delegated_id][2], "working")
        self.w.run(CLOSE, self.w.team, "alpha")

    def test_a_delegated_id_is_never_missing_when_the_listing_lacks_it(self):
        _, delegated_id = self.delegate()
        self.w.boats(boat("someone-else"))
        self.assertNotEqual(self.status_rows()[delegated_id][2], "missing")

    def test_watch_does_not_call_a_working_delegated_teammate_gone(self):
        self.w.ctl_write(f"{self.tool}.sleep", "20")
        self.delegate()
        done = self.w.run(WATCH, "--until-event", 1, self.w.team)
        self.assertEqual(done.out.splitlines(), ["WATCH timeout 1"])
        self.w.run(CLOSE, self.w.team, "alpha")

    def test_status_with_a_failed_listing_exits_3_even_if_every_teammate_is_delegated(self):
        self.delegate()
        self.w.ctl_write("list.rc", "1")
        done = self.w.run(ADMIRAL_DRIVER / "status", self.w.team)
        self.assertEqual((done.code, done.out), (NOT_LISTED, ""))

    def test_stop_says_why_when_the_listing_is_down_and_stops_nothing(self):
        _, delegated_id = self.delegate()
        self.assertTrue(self.w.wait_finished(self.tool))
        self.w.ctl_write("list.rc", "1")
        done = self.w.run(ADMIRAL_DRIVER / "stop", self.w.team, delegated_id)
        self.assertNotEqual(done.code, OK)
        self.assertIn("nothing stopped", done.text)
        self.assertEqual(self.w.crew_calls("close"), [])

    def test_an_id_that_is_an_open_crew_boats_name_is_not_delegated(self):
        """A Copilot writer can write the team dir, so it could put a live boat's name in the file to steer `stop`."""
        _, delegated_id = self.delegate()
        self.assertTrue(self.w.wait_finished(self.tool))
        before = len(self.w.calls(self.tool))
        self.w.boats(boat(delegated_id, "underway"))
        done = self.w.run(ADMIRAL_DRIVER / "stop", self.w.team, delegated_id)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual([c[:3] for c in self.w.crew_calls("close")], [["crew", "close", delegated_id]])
        self.assertEqual(len(self.w.calls(self.tool)), before)

    def test_an_id_with_no_registry_row_is_not_delegated(self):
        _, delegated_id = self.delegate()
        self.assertTrue(self.w.wait_finished(self.tool))
        (self.w.team / "teammates.tsv").unlink()
        self.w.register("beta")
        msg = self.w.message()
        before = len(self.w.calls(self.tool))
        self.w.run(ADMIRAL_DRIVER / "send", self.w.team, delegated_id, msg)
        self.assertEqual(len(self.w.calls(self.tool)), before)
        self.assertEqual([c[:3] for c in self.w.crew_calls("send")], [["crew", "send", delegated_id]])

    def test_tail_is_the_codex_drivers_not_the_raw_one(self):
        self.delegate()
        self.wait_idle()
        done = self.w.run(TAIL, self.w.team, "alpha", 3)
        self.assertEqual(done.code, OK, done.text)
        lines = done.out.splitlines()
        self.assertTrue(lines[0].startswith("transcript: "), lines)
        self.assertEqual(lines[-1], "SAID  codex report text")
        self.assertEqual(self.w.crew_calls("close"), [])


class TestCopilotReadOnlyDelegation(ReadOnlyDelegation, WorldCase):
    harness = "copilot"

    def assert_headless_argv(self, argv):
        self.assertIn("-p", argv)
        self.assertIn("-s", argv)
        self.assertIn("--session-id", argv)
        self.assertIn("--no-ask-user", argv)

    def assert_resumed(self, argv, delegated_id):
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], delegated_id)

    def test_tail_is_the_copilot_drivers_not_the_raw_one(self):
        _, delegated_id = self.delegate()
        events = self.w.home / ".copilot" / "session-state" / delegated_id / "events.jsonl"
        events.parent.mkdir(parents=True)
        events.write_text(json.dumps({"type": "assistant.message", "data": {"content": "all done"}}) + "\n")
        done = self.w.run(TAIL, self.w.team, "alpha", 3)
        self.assertEqual(done.code, OK, done.text)
        lines = done.out.splitlines()
        self.assertTrue(lines[0].startswith(f"transcript: {events}"), lines)
        self.assertEqual(lines[-1], "SAID  all done")


class TestReadOnlyWithoutAHarnessDriver(WorldCase):
    def test_an_unknown_harness_read_only_launch_exits_5_with_a_message(self):
        self.w.write_team_env(harness="nosuch", extra=["MODEL_REVIEWER=x"])
        self.w.prompt("alpha")
        done = self.w.run(LAUNCH, "--read-only", "--role", "reviewer", self.w.team, "alpha", self.w.work)
        self.assertEqual(done.code, USAGE, done.text)
        self.assertIn("nosuch", done.text)
        self.assertEqual(self.w.admiral(), [])


class TestCodexRawTail(WorldCase):
    """For a writer boat, tail prints the transcript path and the last <n> lines raw, each cut to 300 characters."""

    CUT = 300

    def setUp(self):
        super().setUp()
        self.w.write_team_env(harness="codex")
        self.w.register("alpha")

    def transcript(self, lines):
        path = self.w.root / "transcripts" / "rollout-2026-10-25T10-00-00-abc.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(line + "\n" for line in lines))
        return path

    def tail(self, path, n):
        self.w.boats(boat("alpha", "underway", transcript=str(path)))
        return self.w.run(TAIL, self.w.team, "alpha", n)

    def test_prints_the_path_and_the_last_n_lines_raw(self):
        events = [json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "n": i}}) for i in range(25)]
        path = self.transcript(events)
        done = self.tail(path, 4)
        self.assertEqual(done.code, OK, done.text)
        lines = done.out.splitlines()
        self.assertIn(str(path), lines[0])
        self.assertTrue(lines[0].startswith("transcript:"), lines[0])
        self.assertEqual(lines[1:], events[-4:])

    def test_each_line_is_cut_to_300_characters(self):
        long = '{"type":"response_item","text":"' + "x" * 500 + '"}'
        short = '{"type":"event_msg","payload":{"type":"task_complete"}}'
        path = self.transcript([long, short])
        done = self.tail(path, 2)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(done.out.splitlines()[1:], [long[: self.CUT], short])
        self.assertEqual(len(done.out.splitlines()[1]), self.CUT)

    def test_the_cut_counts_characters_not_bytes(self):
        long = "é" * 400
        path = self.transcript([long])
        done = self.tail(path, 1)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(done.out.splitlines()[1:], [long[: self.CUT]])

    def test_only_newlines_split_lines(self):
        line = '{"text":"a\u2028b\u2029c"}'
        path = self.transcript([line, "next"])
        done = self.tail(path, 2)
        self.assertEqual(done.out.split("\n")[1:3], [line, "next"])

    def test_control_characters_are_blanked(self):
        path = self.transcript(["a\x1b[31mred\x07\x00b\ttab\x7f\x9bend"])
        done = self.tail(path, 1)
        self.assertEqual(done.out.split("\n")[1], "a [31mred  b\ttab  end")

    def test_a_null_transcript_exits_3(self):
        self.w.boats(boat("alpha", "underway", transcript=None))
        done = self.w.run(TAIL, self.w.team, "alpha", 5)
        self.assertEqual(done.code, NOT_LISTED, done.text)

    def test_an_unlisted_boat_exits_3(self):
        self.w.boats()
        done = self.w.run(TAIL, self.w.team, "alpha", 5)
        self.assertEqual(done.code, NOT_LISTED, done.text)
        self.assertEqual(len(self.w.crew_calls("list")), 1)

    def test_a_failed_listing_exits_3(self):
        self.w.ctl_write("list.rc", "1")
        done = self.w.run(TAIL, self.w.team, "alpha", 5)
        self.assertEqual(done.code, NOT_LISTED, done.text)
        self.assertEqual(len(self.w.crew_calls("list")), 1)


if __name__ == "__main__":
    unittest.main()
