"""Tests for Codex and Copilot teammates inside an Admiral ship (u2 of #115): writers are crew boats, read-only
teammates stay headless and are handed to their harness driver by the admiral driver.

Seams: the shared scripts (launch-teammate.sh, retask.sh, watch-teammates.sh, close-teammate.sh, teammate-tail.sh) and
the admiral driver's operations, run as subprocesses against a temp team dir. A fake `admiral` records its argv and
stdin and prints canned `crew list --json`; fake `codex` and `copilot` log their argv and answer like the CLIs the
harness drivers start. The fakes may be called only by delegated operations (a read-only teammate's launch, send, stop,
status and tail); a writer's operations must never reach them. Expected values come from u2-unit.md (decisions 1-5, 7,
8) and Admiral's docs/cli.md at 992f678. The order of Admiral's own flags (--name, --dir, --harness, --ship, --role)
is left free, as in test_admiral_driver.py.

Run from the repo root: python3 -m unittest evals/agent-teammates/test_admiral_codex_copilot.py -v
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import ADMIRAL_DRIVER, SCRIPTS, SHIP, WorldCase, boat, rfc3339, split_launch

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
    """decision 4: a Codex writer is a crew boat; the --arg values are the interactive flags, in order."""

    harness = "codex"
    REFUSED = (
        "exec",
        "--json",
        "-o",
        "--skip-git-repo-check",
        "--ignore-rules",
        "--no-daemon",
        "-C",
        "-p",
        "--profile",
    )

    def test_admiral_flags_carry_name_dir_harness_ship_and_role(self):
        _, _, flags, _ = self.crew_launched("--role", "test-writer")
        self.assertEqual(
            flags,
            {
                "--name": ["alpha"],
                "--dir": [str(self.w.work)],
                "--harness": ["codex"],
                "--ship": [SHIP],
                "--role": ["test-writer"],
            },
        )

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

    def test_model_flag_wins_over_the_role_model(self):
        _, _, _, args = self.crew_launched("--role", "test-writer", "--model", "gpt-5.1")
        self.assertEqual(args[args.index("-m") + 1], "gpt-5.1")

    def test_the_last_arg_is_a_single_value_flag_so_the_prompt_is_not_read_as_its_value(self):
        _, argv, _, args = self.crew_launched("--role", "test-writer")
        self.assertEqual(args[-2:], ["-a", "never"])
        self.assertEqual(argv[-2], "--")

    def test_no_refused_or_exec_only_value_appears(self):
        _, _, _, args = self.crew_launched("--role", "test-writer")
        for bad in self.REFUSED:
            self.assertNotIn(bad, args)
        self.assertEqual([a for a in args if "trust" in a or "projects" in a], [])
        self.assertEqual([a for a in args if a.startswith(("hooks", "features", "profile"))], [])

    def test_the_prompt_is_the_first_message_after_a_bare_double_dash(self):
        _, argv, _, _ = self.crew_launched("--role", "test-writer")
        self.assertEqual(argv.count("--"), 1)

    def test_a_writer_launch_never_runs_codex_itself(self):
        self.crew_launched("--role", "test-writer")
        self.assertEqual(self.w.calls("codex"), [])

    def test_registry_row_uses_the_crew_name_and_no_viewer(self):
        done, _, _, _ = self.crew_launched("--role", "test-writer")
        self.assertEqual([self.w.registry()[-1][i] for i in (0, 1, 3)], ["alpha", "alpha", "-"])
        self.assertTrue(done.out.startswith("launched alpha as background session alpha in "), done.out)
        self.assertFalse((self.w.team / "admiral-delegated").exists())

    def test_names_outside_admirals_rule_exit_5_for_a_writer(self):
        self.w.prompt("Bad_Name")
        done = self.launch("--role", "test-writer", name="Bad_Name")
        self.assertEqual(done.code, USAGE, done.text)
        self.assertIn("lowercase", done.text)
        self.assertEqual(self.w.crew_calls("launch"), [])

    def test_a_missing_dock_fails_the_launch_with_admirals_message(self):
        self.w.ctl_write("launch.rc", "1")
        self.w.ctl_write("launch.msg", "admiral: fleet work has no codex dock\n")
        done = self.launch("--role", "test-writer")
        self.assertEqual(done.code, FAILED, done.text)
        self.assertIn("fleet work has no codex dock", done.text)
        self.assertNotIn("NO_BG", done.text)
        self.assertEqual(self.w.registry(), [])

    def test_a_boat_stuck_at_a_startup_prompt_is_closed_and_exits_5(self):
        self.w.boats(boat("alpha"))
        done = self.launch("--role", "test-writer", LAUNCH_WAIT="0", LAUNCH_POLL="0")
        self.assertEqual(done.code, USAGE, done.text)
        self.assertIn("startup prompt", done.text)
        self.assertEqual(len(self.w.crew_calls("close")), 1)
        self.assertEqual(self.w.registry(), [])


class TestCopilotWriterLaunch(LaunchCase):
    """decision 5: a Copilot writer is a crew boat; Admiral appends the prompt as --interactive, so the list ends on a
    single-value flag, --model, after the variadic --available-tools and --deny-tool."""

    harness = "copilot"
    REFUSED = (
        "-p",
        "-s",
        "--silent",
        "--session-id",
        "--resume",
        "--trust-folder",
        "--interactive",
        "-i",
        "--plugin-dir",
    )

    def groups(self, *opts, **env):
        _, _, _, args = self.crew_launched("--role", "test-writer", *opts, **env)
        return args, *flag_groups(args)

    def test_admiral_flags_carry_name_dir_harness_ship_and_role(self):
        _, _, flags, _ = self.crew_launched("--role", "test-writer")
        self.assertEqual(flags["--harness"], ["copilot"])
        self.assertEqual(flags["--role"], ["test-writer"])
        self.assertEqual(flags["--name"], ["alpha"])

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

    def test_the_model_flag_wins_over_the_role_model(self):
        args, _, _ = self.groups("--model", "gpt-5.1")
        self.assertEqual(args[-2:], ["--model", "gpt-5.1"])

    def test_no_prompt_mode_or_trust_flag_appears(self):
        args, _, _ = self.groups()
        for bad in self.REFUSED:
            self.assertNotIn(bad, args)
        self.assertEqual([a for a in args if a.startswith("--deny-tool=") or a.startswith("--allow-tool")], [])

    def test_a_writer_launch_never_runs_copilot_itself(self):
        self.groups()
        self.assertEqual(self.w.calls("copilot"), [])

    def test_a_boat_that_exits_during_startup_is_closed_and_exits_1(self):
        self.w.boats(boat("alpha", "anchored"))
        done = self.launch("--role", "test-writer", LAUNCH_POLL="0")
        self.assertEqual(done.code, FAILED, done.text)
        self.assertEqual(len(self.w.crew_calls("close")), 1)


class WritersAreCrewBoats:
    """decision 7: a writer's send, status and stop are u1's crew-boat code, on every harness."""

    harness = None

    def setUp(self):
        super().setUp()
        self.w.write_team_env(harness=self.harness)
        self.w.register("alpha", epoch=1000)

    def test_retask_sends_a_pointer_through_crew_send(self):
        msg = self.w.message("a long job\n")
        done = self.w.run(RETASK, self.w.team, "alpha", msg)
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        (call,) = [c for c in self.w.calls("admiral") if c["argv"][:3] == ["crew", "send", "alpha"]]
        self.assertEqual(call["stdin"].rstrip("\n"), f"You are teammate alpha. Read {msg} and do exactly what it says.")
        self.assertEqual(self.w.calls(self.harness), [])

    def test_watch_reads_a_boat_that_needs_you_as_blocked_on_the_second_poll(self):
        self.w.boats(boat("alpha", "needs_you", last_activity=rfc3339(time.time() - 60)))
        self.assertEqual(self.w.run(WATCH, "--until-event", 1, self.w.team).out.splitlines(), ["WATCH timeout 1"])
        self.assertEqual(self.w.run(WATCH, "--until-event", 1, self.w.team).out.splitlines(), ["BLOCKED alpha alpha"])
        self.assertEqual(self.w.calls(self.harness), [])

    def test_watch_stalls_a_quiet_underway_boat_by_its_last_activity(self):
        self.w.boats(boat("alpha", "underway", last_activity=rfc3339(time.time() - 30 * 60)))
        lines = self.w.run(WATCH, "--until-event", 1, self.w.team).out.splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("STALL alpha alpha "), lines)

    def test_close_closes_the_crew_boat(self):
        self.w.boats(boat("alpha", "underway"))
        done = self.w.run(CLOSE, self.w.team, "alpha")
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual([c[:3] for c in self.w.crew_calls("close")], [["crew", "close", "alpha"]])
        self.assertEqual(self.w.calls(self.harness), [])


class TestCodexWritersAreCrewBoats(WritersAreCrewBoats, WorldCase):
    harness = "codex"


class TestCopilotWritersAreCrewBoats(WritersAreCrewBoats, WorldCase):
    harness = "copilot"


class ReadOnlyDelegation:
    """decision 3: a read-only teammate on Codex or Copilot runs headless under its harness driver. `launch` hands it
    over before any Admiral rule or call and records its id in <team>/admiral-delegated; send, stop, status and tail
    route by that id."""

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
        """The report is written by the run's own wrapper after the fake exits; wait for its marker."""
        self.assertTrue(self.w.wait_for(self.w.team / "reports" / f"{name}.done"), "no .done marker")
        time.sleep(0.5)

    def retask_when_idle(self, name="alpha"):
        msg = self.w.message("second job\n")
        for _ in range(40):
            done = self.w.run(RETASK, self.w.team, name, msg)
            if "still running" not in done.text:
                return done
            time.sleep(0.25)
        return done

    # launch
    def test_launch_runs_the_harness_driver_headless_and_calls_admiral_for_nothing(self):
        done, delegated_id = self.delegate()
        self.assertEqual(self.w.admiral(), [])
        self.assertTrue(self.w.wait_finished(self.tool))
        (call,) = self.w.calls(self.tool)
        self.assert_headless_argv(call["argv"])
        self.assertTrue(done.out.startswith(f"launched alpha as background session {delegated_id} in "), done.out)
        self.assertIn("(read-only)", done.out.splitlines()[0])

    def test_launch_records_the_printed_id_once_in_the_delegated_file(self):
        _, delegated_id = self.delegate()
        self.assertNotEqual(delegated_id, "alpha")
        self.assertEqual(self.delegated_file(), [delegated_id])
        self.assertEqual(self.w.registry()[-1][:2], ["alpha", delegated_id])

    def test_the_read_only_teammate_still_writes_its_report(self):
        """ac8: a read-only teammate still produces a report, headless."""
        self.delegate()
        self.wait_idle()
        self.assertEqual((self.w.team / "reports" / "alpha.md").read_text().strip(), f"{self.tool} report text")

    def test_the_role_effort_reaches_the_harness_driver(self):
        self.delegate()
        self.assertTrue(self.w.wait_finished(self.tool))
        argv = " ".join(self.w.calls(self.tool)[0]["argv"])
        self.assertIn("high", argv)

    def test_a_name_and_role_admiral_would_refuse_still_launch(self):
        self.w.write_team_env(harness=self.harness, extra=["MODEL_ODD_ROLE=gpt-5.5"])
        self.w.prompt("Mixed_Case.1")
        done = self.w.run(LAUNCH, "--read-only", "--role", "Odd_Role", self.w.team, "Mixed_Case.1", self.w.work)
        self.assertEqual(done.code, OK, done.text)
        self.assertNotIn("lowercase", done.text)
        self.assertEqual(self.w.admiral(), [])
        self.assertEqual(self.delegated_file()[-1:], [self.w.registry()[-1][1]])

    def test_launch_needs_no_admiral_on_the_path(self):
        (self.w.bin / "admiral").unlink()
        done, delegated_id = self.delegate()
        self.assertTrue(done.out.startswith("launched alpha"), done.out)
        self.assertEqual(self.delegated_file(), [delegated_id])

    def test_launch_ignores_an_admiral_that_predates_arg(self):
        self.w.ctl_write("usage.txt", "admiral: usage: admiral crew launch --name <name> --dir <dir> -- <prompt>\n")
        done, _ = self.delegate()
        self.assertEqual(done.code, OK, done.text)

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

    # send
    def test_send_goes_to_the_harness_driver_not_to_crew_send(self):
        _, delegated_id = self.delegate()
        self.wait_idle()
        done = self.retask_when_idle()
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(self.w.crew_calls("send"), [])
        self.assertTrue(self.w.wait_finished(self.tool, 2))
        self.assert_resumed(self.w.calls(self.tool)[1]["argv"], delegated_id)

    def test_the_driver_send_routes_by_id_too(self):
        _, delegated_id = self.delegate()
        self.wait_idle()
        msg = self.w.message()
        for _ in range(40):
            done = self.w.run(ADMIRAL_DRIVER / "send", self.w.team, delegated_id, msg)
            if "still running" not in done.text:
                break
            time.sleep(0.25)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(self.w.crew_calls("send"), [])

    # stop
    def test_stop_goes_to_the_harness_driver_and_closes_no_boat(self):
        self.w.ctl_write(f"{self.tool}.sleep", "20")
        _, delegated_id = self.delegate()
        done = self.w.run(ADMIRAL_DRIVER / "stop", self.w.team, delegated_id)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(self.w.crew_calls("close"), [])
        self.assertEqual(self.status_rows()[delegated_id][2], "stopped")

    def test_close_teammate_stops_a_delegated_teammate_through_its_harness(self):
        self.w.ctl_write(f"{self.tool}.sleep", "20")
        self.delegate()
        done = self.w.run(CLOSE, self.w.team, "alpha")
        self.assertEqual(done.code, OK, done.text)
        self.assertIn("stopped alpha", done.out)
        self.assertEqual(self.w.crew_calls("close"), [])

    # status
    def status_rows(self):
        done = self.w.run(ADMIRAL_DRIVER / "status", self.w.team)
        self.assertEqual((done.code, done.err), (OK, ""), done.text)
        return {line.split()[0]: line.split() for line in done.out.splitlines()}

    def test_status_prints_the_boats_and_then_the_delegated_teammate(self):
        _, delegated_id = self.delegate()
        self.w.register("beta")
        self.w.boats(boat("beta", "underway", last_activity="2026-10-25T10:00:00Z"))
        self.wait_idle()
        deadline, rows = time.time() + 10, {}
        while time.time() < deadline:
            rows = self.status_rows()
            if rows.get(delegated_id, [None] * 3)[2] == "done":
                break
            time.sleep(0.25)
        self.assertEqual(rows["beta"][2:], ["working", "1792922400"])
        self.assertEqual(rows[delegated_id][2], "done", rows)
        self.assertTrue(all(len(r) == FIELDS for r in rows.values()), rows)
        self.assertNotIn("missing", [r[2] for r in rows.values()])
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

    # tail
    # (per harness)

    # the guard: delegated <id> refuses what the file can't be trusted for
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

    def test_an_id_missing_from_the_delegated_file_goes_to_crew_boats(self):
        self.delegate()
        self.w.register("gamma")
        self.w.boats(boat("gamma", "underway"))
        msg = self.w.message()
        done = self.w.run(RETASK, self.w.team, "gamma", msg)
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual([c[:3] for c in self.w.crew_calls("send")], [["crew", "send", "gamma"]])


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


class RawTail:
    """decision 8: for a writer boat on Codex or Copilot, tail prints the transcript path and the last <n> lines raw,
    each cut to 300 characters."""

    harness = None
    CUT = 300

    def setUp(self):
        super().setUp()
        self.w.write_team_env(harness=self.harness)
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

    def test_n_larger_than_the_file_prints_every_line(self):
        path = self.transcript(["one", "two"])
        done = self.tail(path, 20)
        self.assertEqual(done.out.splitlines()[1:], ["one", "two"])

    def test_the_harness_drivers_tail_is_not_used(self):
        path = self.transcript(['{"type":"assistant.message","data":{"content":"hi"}}'])
        done = self.tail(path, 5)
        self.assertIn(str(path), done.out.splitlines()[0])
        self.assertNotIn("SAID", done.out)
        self.assertNotIn("TOOL", done.out)
        self.assertEqual(self.w.calls(self.harness), [])

    def test_the_listing_is_asked_for_by_ship(self):
        path = self.transcript(["one"])
        self.tail(path, 1)
        listings = self.w.crew_calls("list")
        self.assertEqual(len(listings), 1, self.w.admiral())
        listing = listings[0]
        self.assertIn("--json", listing)
        self.assertEqual(listing[listing.index("--ship") + 1], SHIP)

    def test_a_null_transcript_exits_3_with_a_message(self):
        self.w.boats(boat("alpha", "underway", transcript=None))
        done = self.w.run(TAIL, self.w.team, "alpha", 5)
        self.assertEqual(done.code, NOT_LISTED, done.text)
        self.assertIn("transcript", done.text.lower())
        self.assertIn("alpha", done.text)

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


class TestCodexRawTail(RawTail, WorldCase):
    harness = "codex"


class TestCopilotRawTail(RawTail, WorldCase):
    harness = "copilot"

    def test_a_null_transcript_says_it_is_recorded_only_after_the_first_turn_ends(self):
        self.w.boats(boat("alpha", "underway", transcript=None))
        done = self.w.run(TAIL, self.w.team, "alpha", 5)
        self.assertEqual(done.code, NOT_LISTED, done.text)
        self.assertRegex(done.text, r"(?i)first turn")


if __name__ == "__main__":
    unittest.main()
