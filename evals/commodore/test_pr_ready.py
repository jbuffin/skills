"""Tests for skills/engineering/commodore/scripts/pr-ready.sh.

The only seam is the script's command line: a run directory and a unit in, exit code and `run:` /
`ready:` / `not ready:` lines out. Every test builds a fixture run directory in a temp dir (state.md only: the
script reads nothing else) and puts a stub `gh` first on PATH. The stub prints canned `gh pr view` JSON and records
its argv, so a test can also prove the script never writes.
Expected values are literals worked out by hand from the fixtures.

Run from the repo root: python3 -m unittest discover -s evals/commodore -v
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPT = REPO / "skills" / "engineering" / "commodore" / "scripts" / "pr-ready.sh"

URL = "https://github.com/example/fixture/pull/7"
UNIT = "u1"
BRANCH = "u1-branch"
BASE = "main"
READY = f"run: gh pr ready {URL}"

STUB_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_LOG"
if [ "$1 $2" = "pr view" ]; then
  [ -n "$GH_FAIL" ] && { echo "gh: boom" >&2; exit 1; }
  cat "$GH_JSON"
fi
exit 0
"""


class Result:
    def __init__(self, proc, calls):
        self.code = proc.returncode
        self.out = proc.stdout.splitlines()
        self.err = proc.stderr
        self.calls = calls


class PrReadyCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(STUB_GH)
        gh.chmod(0o755)
        self.log = self.tmp / "gh.log"
        self.log.write_text("")

    def go(  # noqa: PLR0913
        self,
        *,
        on=False,
        env_autopilot=None,
        state_line=None,
        auto_merge=None,
        unit=UNIT,
        draft=True,
        state="OPEN",
        view_fails=False,
        pr_cell=URL,
        units_unit=UNIT,
    ):
        """Builds the fixture run, runs the script, and returns a Result.

        `on` is shorthand for the real environment's ADMIRAL_AUTOPILOT=1 plus state.md's `autopilot: on`.
        env_autopilot and state_line set either half alone (state_line is True for the line).
        """
        if on:
            env_autopilot, state_line = "1", True
        self.log.write_text("")
        run = self.tmp / "run"
        run.mkdir(exist_ok=True)
        mode = "mission: build\nmode: single\n" + ("autopilot: on\n" if state_line else "")
        (run / "state.md").write_text(
            "# Run state (read this first on every start)\n\n"
            f"## Mode, phase, current unit\n\n{mode}current unit: {units_unit}\n\n"
            "## Units (head is a snapshot; git is the source of truth)\n\n"
            "| unit | branch | worktree | base | head (as of) | PR | reviewed SHA | status | notes |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            f"| {units_unit} | {BRANCH} | /wt | {BASE} |  | {pr_cell} |  | building |  |\n\n"
            "## Acceptance trace (criterion from the source of truth)\n\n"
            "| criterion | unit | test or scenario | status | evidence |\n| --- | --- | --- | --- | --- |\n\n"
            "## Ground rules (from the engineer)\n"
        )
        pr = self.tmp / "pr.json"
        pr.write_text(json.dumps({"isDraft": draft, "state": state}))
        env = {k: v for k, v in os.environ.items() if not k.startswith("ADMIRAL_")}
        env["PATH"] = f"{self.bin}{os.pathsep}{env['PATH']}"
        env["GH_LOG"] = str(self.log)
        env["GH_JSON"] = str(pr)
        env["GH_FAIL"] = "1" if view_fails else ""
        if env_autopilot is not None:
            env["ADMIRAL_AUTOPILOT"] = env_autopilot
        if auto_merge is not None:
            env["ADMIRAL_AUTO_MERGE"] = auto_merge
        proc = subprocess.run(
            [str(SCRIPT), str(run), unit], env=env, capture_output=True, text=True, timeout=60, check=False
        )
        calls = self.log.read_text().splitlines()
        # The script reads the PR and writes nothing, whatever the outcome.
        self.assertEqual([c for c in calls if not c.startswith("pr view ")], [])
        self.assertLessEqual(len(calls), 1)
        return Result(proc, calls)


class MarkReady(PrReadyCase):
    def test_draft_prints_ready_command_only(self):
        r = self.go()
        self.assertEqual((r.code, r.out), (0, [READY]))
        self.assertEqual(len(r.calls), 1)
        self.assertTrue(r.calls[0].startswith(f"pr view {URL} --json "))

    def test_already_ready_prints_ready_url(self):
        r = self.go(draft=False)
        self.assertEqual((r.code, r.out), (0, [f"ready: {URL}"]))

    def test_no_merge_line_even_with_autopilot_and_auto_merge_set(self):
        for draft, expected in ((True, [READY]), (False, [f"ready: {URL}"])):
            with self.subTest(draft=draft):
                r = self.go(on=True, auto_merge="squash", draft=draft)
                self.assertEqual((r.code, r.out), (0, expected))
                self.assertEqual([line for line in r.out if "merge" in line], [])

    def test_run_directory_without_team_env_is_accepted(self):
        r = self.go()
        self.assertFalse((self.tmp / "run" / "team.env").exists())
        self.assertEqual((r.code, r.out), (0, [READY]))

    def test_auto_merge_value_is_not_read(self):
        r = self.go(on=True, auto_merge="yolo")
        self.assertEqual((r.code, r.out), (0, [READY]))


class NotReady(PrReadyCase):
    def test_pr_not_open_exits_1(self):
        for autopilot in (False, True):
            for state in ("CLOSED", "MERGED"):
                with self.subTest(autopilot=autopilot, state=state):
                    r = self.go(on=autopilot, state=state)
                    self.assertEqual((r.code, r.out), (1, [f"not ready: {URL}: PR is {state}, not OPEN"]))

    def test_gh_pr_view_failure_exits_1(self):
        for autopilot in (False, True):
            with self.subTest(autopilot=autopilot):
                r = self.go(on=autopilot, view_fails=True)
                self.assertEqual((r.code, r.out), (1, [f"not ready: {URL}: gh pr view failed"]))


class Preconditions(PrReadyCase):
    """Exit 5 with a reason on stderr. The `_autopilot_off` twins prove the refusal is the check's own,
    not the old autopilot gate."""

    def assertRefused(self, r, reason):
        self.assertEqual((r.code, r.out), (5, []))
        self.assertIn(reason, r.err)
        self.assertNotIn("ADMIRAL_AUTOPILOT", r.err)
        self.assertNotIn("autopilot: on", r.err)
        self.assertEqual(r.calls, [])

    def test_bad_unit_name(self):
        self.assertRefused(self.go(on=True, unit="u 1;x"), "invalid unit name")

    def test_bad_unit_name_autopilot_off(self):
        self.assertRefused(self.go(unit="u 1;x"), "invalid unit name")

    def test_no_units_row(self):
        self.assertRefused(self.go(on=True, unit="u9"), "no row for unit 'u9'")

    def test_no_units_row_autopilot_off(self):
        self.assertRefused(self.go(unit="u9"), "no row for unit 'u9'")

    def test_bare_pr_number(self):
        self.assertRefused(self.go(on=True, pr_cell="#7"), "no full PR URL")

    def test_bare_pr_number_autopilot_off(self):
        self.assertRefused(self.go(pr_cell="7"), "no full PR URL")

    def test_empty_pr_cell_autopilot_off(self):
        self.assertRefused(self.go(pr_cell=""), "no full PR URL")

    def test_missing_state_md_exits_5_with_stderr(self):
        run = self.tmp / "empty"
        run.mkdir()
        proc = subprocess.run([str(SCRIPT), str(run), UNIT], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((proc.returncode, proc.stdout), (5, ""))
        self.assertNotEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
