"""Tests for the per-teammate harness lock in the agent-teammates scripts (issue #199, unit u3; docs/adr/0008).

Seam: launch-teammate.sh, close-teammate.sh, retask.sh, teammate-tail.sh and watch-teammates.sh as subprocesses in the
temp world of admiral_world.py (fake admiral, claude, codex, copilot that log every call). Assertions are on which fake
was called with which arguments, the registry rows (a sixth column holds the teammate's harness), stdout/stderr lines
and exit codes. Expected values come from the u3 spec (section 7 overrides), ADR 0008 and drivers/CONTRACT.md.
What it catches: a lock that isn't honoured, a registry column dropped on re-task or close, a bad name reaching a
driver.
What it misses: the real codex and copilot CLIs (fakes only), and the cast and preflight sides (evals/commodore).

Run from the repo root: python3 -m unittest discover -s evals/agent-teammates -p 'test_harness_lock.py' -v
"""

import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import SCRIPTS, SHIP, WorldCase, boat, split_launch

LAUNCH = SCRIPTS / "launch-teammate.sh"
CLOSE = SCRIPTS / "close-teammate.sh"
RETASK = SCRIPTS / "retask.sh"
TAIL = SCRIPTS / "teammate-tail.sh"
WATCH = SCRIPTS / "watch-teammates.sh"

BAD_USAGE = 5
SEND_IS_A_TOOL = 4
LOCK = ["HARNESS_IMPLEMENTER=codex", "MODEL_IMPLEMENTER=gpt-5.5"]


class LockCase(WorldCase):
    def setUp(self):
        super().setUp()
        self.w.write_team_env(extra=LOCK)

    def launch(self, name, *flags, role="implementer", ship=None, **env):
        self.w.prompt(name)
        return self.w.run(LAUNCH, *flags, "--role", role, self.w.team, name, self.w.work, ship=ship, **env)

    def row(self, name):
        rows = [r for r in self.w.registry() if r[0] == name]
        self.assertTrue(rows, f"no registry row for {name}: {self.w.registry()}")
        return rows[-1]

    def six_column_row(self, name, harness, session_id=None, epoch=None):
        epoch = int(time.time()) - 600 if epoch is None else epoch
        with open(self.w.team / "teammates.tsv", "a") as reg:
            reg.write(f"{name} {session_id or name} {epoch} - {self.w.work} {harness}\n")


class TestLaunchOutsideAdmiral(LockCase):
    def test_a_locked_role_launches_on_its_own_harness(self):
        done = self.launch("impl")
        self.assertEqual(done.code, 0, done.text)
        self.assertTrue(self.w.wait_finished("codex"), self.w.calls("codex"))
        self.assertEqual(len(self.w.calls("codex")), 1)
        self.assertEqual([c for c in self.w.calls("claude") if "--bg" in c["argv"]], [])
        self.assertEqual(self.w.admiral(), [])
        row = self.row("impl")
        self.assertEqual(len(row), 6, row)
        self.assertEqual(row[5], "codex")

    def test_an_unlocked_role_launches_on_the_run_harness_and_records_it(self):
        done = self.launch("tw", role="test-writer")
        self.assertEqual(done.code, 0, done.text)
        self.assertEqual(len([c for c in self.w.calls("claude") if "--bg" in c["argv"]]), 1)
        self.assertEqual(self.w.calls("codex"), [])
        row = self.row("tw")
        self.assertEqual(len(row), 6, row)
        self.assertEqual(row[5], "claude")

    def test_harness_flag_beats_the_lock(self):
        done = self.launch("impl", "--harness", "copilot")
        self.assertEqual(done.code, 0, done.text)
        self.assertTrue(self.w.wait_finished("copilot"), self.w.calls("copilot"))
        self.assertEqual(self.w.calls("codex"), [])
        self.assertEqual(self.row("impl")[5], "copilot")

    def test_a_bad_harness_name_is_refused_before_any_driver_call(self):
        for bad, reason in (("admiral", ""), ("nosuch", "no driver for harness nosuch"), ("Bad_Name", "")):
            with self.subTest(harness=bad):
                done = self.launch("x-" + bad.lower().replace("_", "-"), "--harness", bad)
                self.assertEqual(done.code, BAD_USAGE, done.text)
                self.assertIn(reason, done.text)
                self.assertEqual(self.w.calls("codex") + self.w.calls("copilot") + self.w.admiral(), [])
                self.assertEqual([c for c in self.w.calls("claude") if "--bg" in c["argv"]], [])
                self.assertEqual(self.w.registry(), [])
        control = self.launch("control", "--harness", "copilot")
        self.assertEqual(control.code, 0, control.text)

    def test_a_locked_admiral_in_team_env_is_refused(self):
        self.w.write_team_env(extra=["HARNESS_IMPLEMENTER=admiral", "MODEL_IMPLEMENTER=sonnet"])
        done = self.launch("impl")
        self.assertEqual(done.code, BAD_USAGE, done.text)
        self.assertEqual(self.w.registry(), [])
        self.w.write_team_env(extra=LOCK)
        self.assertEqual(self.launch("impl").code, 0)


class TestLaunchInsideAdmiral(LockCase):
    def test_a_locked_writer_goes_through_crew_launch_with_the_harness(self):
        done = self.launch("impl", ship=SHIP)
        self.assertEqual(done.code, 0, done.text)
        (argv,) = self.w.crew_calls("launch")
        flags, args = split_launch(self, argv, "impl")
        self.assertEqual(flags["--harness"], ["codex"])
        self.assertEqual(
            args[:6],
            [
                "-s",
                "workspace-write",
                "-c",
                "sandbox_workspace_write.network_access=true",
                "--add-dir",
                str(self.w.team / "reports"),
            ],
        )
        self.assertIn("gpt-5.5", args)
        self.assertEqual(self.w.calls("codex"), [])
        self.assertEqual(self.row("impl")[5], "codex")

    def test_a_locked_copilot_writer_gets_the_copilot_arguments(self):
        self.w.write_team_env(extra=["HARNESS_IMPLEMENTER=copilot", "MODEL_IMPLEMENTER=gpt-5"])
        done = self.launch("impl", ship=SHIP)
        self.assertEqual(done.code, 0, done.text)
        (argv,) = self.w.crew_calls("launch")
        flags, args = split_launch(self, argv, "impl")
        self.assertEqual(flags["--harness"], ["copilot"])
        self.assertEqual(args[0], "--no-ask-user")
        self.assertEqual(self.row("impl")[5], "copilot")

    def test_a_locked_read_only_reviewer_is_delegated_headless(self):
        self.w.write_team_env(extra=["HARNESS_REVIEWER=codex", "MODEL_REVIEWER=gpt-5.5"])
        done = self.launch("rev", "--read-only", role="reviewer", ship=SHIP)
        self.assertEqual(done.code, 0, done.text)
        self.assertEqual(self.w.crew_calls("launch"), [])
        self.assertTrue(self.w.wait_finished("codex"), self.w.calls("codex"))
        self.assertEqual(self.row("rev")[5], "codex")

    def test_autopilot_runs_a_locked_codex_teammate_headless_and_keeps_claude_on_crew_launch(self):
        done = self.launch("impl", ship=SHIP, ADMIRAL_AUTOPILOT="1")
        self.assertEqual(done.code, 0, done.text)
        self.assertEqual(self.w.crew_calls("launch"), [])
        self.assertTrue(self.w.wait_finished("codex"), self.w.calls("codex"))
        self.assertEqual(self.row("impl")[5], "codex")
        control = self.launch("tw", role="test-writer", ship=SHIP, ADMIRAL_AUTOPILOT="1")
        self.assertEqual(control.code, 0, control.text)
        (argv,) = self.w.crew_calls("launch")
        flags, _ = split_launch(self, argv, "tw")
        self.assertEqual(flags["--harness"], ["claude"])


class TestCloseRetaskTail(LockCase):
    def test_close_stops_a_codex_teammate_on_codex_and_keeps_its_harness(self):
        self.w.ctl_write("codex.sleep", "30")
        self.assertEqual(self.launch("impl").code, 0)
        done = self.w.run(CLOSE, self.w.team, "impl", ship=None)
        self.assertEqual(done.code, 0, done.text)
        self.assertNotIn(["stop", self.row("impl")[1]], [c["argv"] for c in self.w.calls("claude")])
        self.assertEqual([c for c in self.w.calls("claude") if c["argv"][:1] == ["stop"]], [])
        row = self.row("impl")
        self.assertEqual(row[2], "closed")
        self.assertEqual(len(row), 6, row)
        self.assertEqual(row[5], "codex")

    def test_close_of_a_legacy_five_column_row_uses_the_run_harness_and_records_it(self):
        self.w.register("old")
        done = self.w.run(CLOSE, self.w.team, "old", ship=None)
        self.assertEqual(done.code, 0, done.text)
        self.assertIn(["stop", "old"], [c["argv"] for c in self.w.calls("claude")])
        row = self.row("old")
        self.assertEqual(row[2], "closed")
        self.assertEqual(row[5:], ["claude"])

    def test_retask_of_a_codex_row_resumes_the_codex_thread_and_keeps_the_harness(self):
        self.assertEqual(self.launch("impl").code, 0)
        self.assertTrue(self.w.wait_finished("codex"))
        msg = self.w.message()
        done = self.w.run(RETASK, self.w.team, "impl", msg, ship=None)
        self.assertEqual(done.code, 0, done.text)
        resumes = [c for c in self.w.calls("codex") if c["argv"][:2] == ["exec", "resume"]]
        self.assertEqual(len(resumes), 1, self.w.calls("codex"))
        row = self.row("impl")
        self.assertEqual(len(row), 6, row)
        self.assertEqual(row[5], "codex")

    def test_retask_of_a_claude_teammate_in_a_codex_run_names_its_own_harness(self):
        self.w.write_team_env(harness="codex")
        self.six_column_row("cl", "claude")
        done = self.w.run(RETASK, self.w.team, "cl", self.w.message(), ship=None)
        self.assertEqual(done.code, SEND_IS_A_TOOL, done.text)
        self.assertIn("claude declares SEND=tool", done.text)
        self.assertEqual(self.w.calls("codex"), [])

    def test_a_bad_teammate_harness_in_the_environment_is_refused_by_retask(self):
        self.w.write_team_env(harness="codex")
        self.six_column_row("cl", "claude")
        control = self.w.run(RETASK, self.w.team, "cl", self.w.message(), ship=None)
        self.assertEqual(control.code, SEND_IS_A_TOOL, control.text)
        for bad in ("admiral", "Bad_Name!"):
            with self.subTest(bad=bad):
                done = self.w.run(RETASK, self.w.team, "cl", self.w.message(), ship=None, TEAMMATE_HARNESS=bad)
                self.assertEqual(done.code, BAD_USAGE, done.text)

    def test_retask_of_a_codex_row_in_a_claude_ship_uses_crew_send_and_keeps_the_column(self):
        self.six_column_row("impl", "codex")
        done = self.w.run(RETASK, self.w.team, "impl", self.w.message(), ship=SHIP)
        self.assertEqual(done.code, 0, done.text)
        self.assertEqual(len(self.w.crew_calls("send")), 1, self.w.admiral())
        row = self.row("impl")
        self.assertEqual(len(row), 6, row)
        self.assertEqual(row[5], "codex")

    def test_tail_of_a_codex_teammate_shows_the_codex_report(self):
        self.assertEqual(self.launch("impl").code, 0)
        self.assertTrue(self.w.wait_finished("codex"))
        done = self.w.run(TAIL, self.w.team, "impl", "20", ship=None)
        self.assertEqual(done.code, 0, done.text)
        self.assertIn("SAID  codex report text", done.out)

    def test_tail_of_a_locked_codex_boat_in_a_claude_ship_takes_the_raw_transcript_path(self):
        transcript = self.w.root / "boat.jsonl"
        transcript.write_text("line one\nline two\nline three\n")
        self.six_column_row("impl", "codex")
        self.w.boats(boat("impl", "underway", transcript=str(transcript)))
        done = self.w.run(TAIL, self.w.team, "impl", "2", ship=SHIP)
        self.assertEqual(done.code, 0, done.text)
        self.assertEqual(done.out.splitlines()[0], f"transcript: {transcript}")
        self.assertEqual(done.out.splitlines()[1:], ["line two", "line three"])
        self.assertEqual(self.w.calls("codex"), [])


def copied_scripts(world):
    """A copy of the scripts tree inside the world, so a test can replace driver operations with logging stubs."""
    dest = world.root / "scripts"
    shutil.copytree(SCRIPTS, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def stub(path, text):
    path.write_text(text)
    path.chmod(0o755)


class TestWatchdogAndCloseGroupByHarness(LockCase):
    def setUp(self):
        super().setUp()
        self.scripts = copied_scripts(self.w)
        self.log = self.w.root / "driver.log"
        for name, rows in (("claude", "c1 working working {now}"), ("codex", "x1 working working {now}")):
            self.stub_status(name, rows)

    def stub_status(self, name, rows, rc=0):
        now = int(time.time())
        body = "".join(f"echo '{r.format(now=now)}'\n" for r in rows.split(";"))
        stub(
            self.scripts / "drivers" / name / "status",
            f'#!/bin/sh\necho "{name} TEAMMATE_HARNESS=$TEAMMATE_HARNESS" >> "{self.log}"\n{body}exit {rc}\n',
        )

    def logged(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def watch(self, **env):
        return self.w.run(self.scripts / "watch-teammates.sh", "--until-event", "1", self.w.team, timeout=30, **env)

    def test_each_harness_group_is_listed_once_with_its_own_teammate_harness(self):
        self.w.register("ca", "c1")
        self.six_column_row("cx", "codex", "x1")
        self.stub_status("claude", "c1 working stopped -")
        done = self.watch(ship=None)
        self.assertEqual(sorted(self.logged()), ["claude TEAMMATE_HARNESS=claude", "codex TEAMMATE_HARNESS=codex"])
        self.assertIn("GONE ca c1 stopped", done.out)
        self.assertNotIn("cx", done.out)

    def test_a_failing_codex_listing_does_not_stop_the_claude_group(self):
        self.w.register("ca", "c1")
        self.six_column_row("cx", "codex", "x1")
        self.stub_status("claude", "c1 working stopped -")
        self.stub_status("codex", "", rc=3)
        done = self.watch(ship=None)
        self.assertIn("GONE ca c1 stopped", done.out)
        self.assertIn("codex TEAMMATE_HARNESS=codex", self.logged())  # the failing group was asked, not skipped unseen

    def test_a_codex_driver_without_status_stops_the_watch(self):
        self.six_column_row("cx", "codex", "x1")
        (self.scripts / "drivers" / "codex" / "status").unlink()
        done = self.watch(ship=None)
        self.assertEqual(done.code, 5, done.text)
        self.assertIn("WATCH the codex driver has no status operation; the watchdog can't run", done.out)

    def test_a_legacy_row_is_listed_under_the_run_harness(self):
        self.w.register("ca", "c1")
        self.watch(ship=None)
        self.assertEqual(self.logged(), ["claude TEAMMATE_HARNESS=claude"])

    def test_a_bad_registry_harness_is_skipped_and_the_watch_goes_on(self):
        self.w.register("ca", "c1")
        self.six_column_row("bd", "Bad_Name!", "x2")
        self.six_column_row("ad", "admiral", "x3")
        self.stub_status("claude", "c1 working stopped -")
        done = self.watch(ship=None)
        self.assertIn("WATCH bd has a bad harness in the registry; skipped", done.out)
        self.assertIn("WATCH ad has a bad harness in the registry; skipped", done.out)
        self.assertIn("GONE ca c1 stopped", done.out)

    def test_close_skips_a_bad_registry_harness_and_closes_the_next_name(self):
        self.six_column_row("bd", "Bad_Name!", "x2")
        self.w.register("ca", "c1")
        done = self.w.run(self.scripts / "close-teammate.sh", self.w.team, "bd", "ca", ship=None)
        self.assertIn("bd: bad harness 'Bad_Name!' in the registry; skipping", done.text)
        self.assertEqual([r for r in self.w.registry() if r[0] == "bd" and r[2] == "closed"], [])
        self.assertEqual([r[2] for r in self.w.registry() if r[0] == "ca"][-1], "closed")


class TestWatchdogInsideAdmiral(LockCase):
    def test_autopilot_splits_the_listing_between_admiral_and_codex(self):
        scripts = copied_scripts(self.w)
        log = self.w.root / "driver.log"
        for name in ("admiral", "codex"):
            stub(
                scripts / "drivers" / name / "status",
                f'#!/bin/sh\necho "{name} TEAMMATE_HARNESS=$TEAMMATE_HARNESS" >> "{log}"\nexit 0\n',
            )
        self.w.register("ca", "c1")
        self.six_column_row("cx", "codex", "x1")
        self.w.run(scripts / "watch-teammates.sh", "--until-event", "1", self.w.team, timeout=30, ADMIRAL_AUTOPILOT="1")
        self.assertEqual(
            sorted(log.read_text().splitlines()), ["admiral TEAMMATE_HARNESS=claude", "codex TEAMMATE_HARNESS=codex"]
        )


if __name__ == "__main__":
    unittest.main()
