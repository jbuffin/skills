"""pr-ready.sh prints the command that leaves a unit's PR ready for review, and never a merge."""

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

    def go(self, *, unit=UNIT, draft=True, state="OPEN", view_fails=False, pr_cell=URL, admiral=False):  # noqa: PLR0913
        """Builds the fixture run, runs the script, and returns a Result. `admiral` sets ADMIRAL_AUTOPILOT=1,
        ADMIRAL_AUTO_MERGE=squash and state.md's `autopilot: on`."""
        self.log.write_text("")
        run = self.tmp / "run"
        run.mkdir(exist_ok=True)
        mode = "mission: build\nmode: single\n" + ("autopilot: on\n" if admiral else "")
        (run / "state.md").write_text(
            "# Run state (read this first on every start)\n\n"
            f"## Mode, phase, current unit\n\n{mode}current unit: {UNIT}\n\n"
            "## Units (head is a snapshot; git is the source of truth)\n\n"
            "| unit | branch | worktree | base | head (as of) | PR | reviewed SHA | status | notes |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            f"| {UNIT} | {BRANCH} | /wt | {BASE} |  | {pr_cell} |  | building |  |\n\n"
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
        if admiral:
            env["ADMIRAL_AUTOPILOT"] = "1"
            env["ADMIRAL_AUTO_MERGE"] = "squash"
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

    def test_autopilot_and_auto_merge_inputs_add_no_merge_line(self):
        r = self.go(admiral=True)
        self.assertEqual((r.code, r.out), (0, [READY]))


class NotReady(PrReadyCase):
    def test_pr_not_open_exits_1(self):
        r = self.go(state="MERGED")
        self.assertEqual((r.code, r.out), (1, [f"not ready: {URL}: PR is MERGED, not OPEN"]))

    def test_gh_pr_view_failure_exits_1(self):
        r = self.go(view_fails=True)
        self.assertEqual((r.code, r.out), (1, [f"not ready: {URL}: gh pr view failed"]))


class Preconditions(PrReadyCase):
    def assertRefused(self, r):
        self.assertEqual((r.code, r.out, r.calls), (5, [], []))
        self.assertTrue(r.err.startswith("pr-ready.sh: "), r.err)

    def test_bad_unit_name(self):
        self.assertRefused(self.go(unit="u 1;x"))

    def test_no_units_row(self):
        r = self.go(unit="u9")
        self.assertRefused(r)
        self.assertIn("u9", r.err)

    def test_pr_cell_that_is_not_a_full_url(self):
        self.assertRefused(self.go(pr_cell="#7"))

    def test_missing_state_md_exits_5_with_stderr(self):
        run = self.tmp / "empty"
        run.mkdir()
        proc = subprocess.run([str(SCRIPT), str(run), UNIT], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((proc.returncode, proc.stdout), (5, ""))
        self.assertNotEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
