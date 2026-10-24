"""Tests for skills/engineering/commodore/scripts/pr-ready.sh.

The only seam is the script's command line: a run directory and a unit in, exit code and `run:` /
`ready:` / `no auto-merge:` / `not ready:` lines out. Every test builds a fixture run directory in a temp
dir (team.env, state.md, a small git repo whose branch head the PR can match) and puts a stub `gh` first on
PATH. The stub prints canned `gh pr view` JSON and records its argv, so a test can also prove the script
never writes. Expected values are literals worked out by hand from the fixtures.

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

GREEN = {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}
RED = {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}
PENDING = {"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}


def merge_line(method):
    return f"run: gh pr merge --auto --{method} {URL}"


def no_auto_merge(reason):
    return f"no auto-merge: {URL}: {reason}"


def git(cwd, *args):
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    out = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


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
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", BASE)
        (self.repo / "f.txt").write_text("x\n")
        git(self.repo, "add", "f.txt")
        git(self.repo, "commit", "-q", "-m", "init")
        git(self.repo, "checkout", "-q", "-b", BRANCH)
        (self.repo / "f.txt").write_text("y\n")
        git(self.repo, "commit", "-q", "-am", "unit")
        self.head = git(self.repo, "rev-parse", BRANCH)
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
        base=BASE,
        checks=(GREEN,),
        pr_head=None,
        view_fails=False,
        findings=(),
        pr_cell=URL,
        units_unit=UNIT,
        team_env_extra="",
        state_extra="",
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
        (run / "team.env").write_text(f"REPO={self.repo}\nBASE_BRANCH={BASE}\n{team_env_extra}")
        mode = "mission: build\nmode: single\n" + ("autopilot: on\n" if state_line else "") + state_extra
        rows = "".join(f"| f{i} | {u} | low | something | {s} |\n" for i, (u, s) in enumerate(findings))
        (run / "state.md").write_text(
            "# Run state (read this first on every start)\n\n"
            f"## Mode, phase, current unit\n\n{mode}current unit: {units_unit}\n\n"
            "## Units (head is a snapshot; git is the source of truth)\n\n"
            "| unit | branch | worktree | base | head (as of) | PR | reviewed SHA | status | notes |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            f"| {units_unit} | {BRANCH} | /wt | {BASE} |  | {pr_cell} |  | building |  |\n\n"
            "## Acceptance trace (criterion from the source of truth)\n\n"
            "| criterion | unit | test or scenario | status | evidence |\n| --- | --- | --- | --- | --- |\n\n"
            "## Non-blocking findings (unfixed ones go in the final report)\n\n"
            "| id | unit | severity | finding | status |\n| --- | --- | --- | --- | --- |\n"
            f"{rows}\n## Ground rules (from the engineer)\n"
        )
        pr = self.tmp / "pr.json"
        pr.write_text(
            json.dumps(
                {
                    "isDraft": draft,
                    "state": state,
                    "baseRefName": base,
                    "headRefOid": pr_head or self.head,
                    "statusCheckRollup": list(checks),
                }
            )
        )
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


class MarkReadyAutopilotOff(PrReadyCase):
    def test_clean_draft_prints_ready_command_only(self):
        r = self.go()
        self.assertEqual((r.code, r.out), (0, [READY]))
        self.assertEqual(len(r.calls), 1)
        self.assertTrue(r.calls[0].startswith(f"pr view {URL} --json "))

    def test_not_clean_draft_still_prints_ready_command(self):
        cases = {
            "human row": dict(findings=[(UNIT, "human")]),
            "red check": dict(checks=(GREEN, RED)),
            "pending check": dict(checks=(PENDING,)),
            "no checks": dict(checks=()),
            "stale head": dict(pr_head="0" * 40),
            "stacked base": dict(base="u0-branch"),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                r = self.go(**kwargs)
                self.assertEqual((r.code, r.out), (0, [READY]))

    def test_already_ready_prints_ready_url(self):
        r = self.go(draft=False)
        self.assertEqual((r.code, r.out), (0, [f"ready: {URL}"]))

    def test_already_ready_and_not_clean_prints_ready_url(self):
        r = self.go(draft=False, checks=(RED,))
        self.assertEqual((r.code, r.out), (0, [f"ready: {URL}"]))

    def test_auto_merge_set_requests_nothing(self):
        r = self.go(auto_merge="squash")
        self.assertEqual((r.code, r.out), (0, [READY]))

    def test_autopilot_env_without_state_line_requests_nothing(self):
        r = self.go(env_autopilot="1", auto_merge="squash")
        self.assertEqual((r.code, r.out), (0, [READY]))

    def test_state_line_without_autopilot_env_requests_nothing(self):
        r = self.go(state_line=True, auto_merge="squash")
        self.assertEqual((r.code, r.out), (0, [READY]))

    def test_env_autopilot_must_be_exactly_one(self):
        r = self.go(env_autopilot="true", state_line=True, auto_merge="squash")
        self.assertEqual((r.code, r.out), (0, [READY]))

    def test_team_env_and_state_md_alone_never_request_auto_merge(self):
        r = self.go(
            state_line=True,
            team_env_extra="ADMIRAL_AUTOPILOT=1\nADMIRAL_AUTO_MERGE=squash\n",
            state_extra="ADMIRAL_AUTO_MERGE: squash\n",
        )
        self.assertEqual((r.code, r.out), (0, [READY]))

    def test_team_env_cannot_supply_auto_merge_method(self):
        r = self.go(on=True, team_env_extra="ADMIRAL_AUTO_MERGE=squash\n")
        self.assertEqual((r.code, r.out), (0, [READY]))


class MarkReadyAutopilotOn(PrReadyCase):
    def test_clean_with_method_prints_ready_then_merge(self):
        for method in ("squash", "merge", "rebase"):
            with self.subTest(method):
                r = self.go(on=True, auto_merge=method)
                self.assertEqual((r.code, r.out), (0, [READY, merge_line(method)]))

    def test_clean_without_method_prints_ready_only(self):
        r = self.go(on=True)
        self.assertEqual((r.code, r.out), (0, [READY]))

    def test_clean_already_ready_prints_merge_only(self):
        r = self.go(on=True, auto_merge="squash", draft=False)
        self.assertEqual((r.code, r.out), (0, [merge_line("squash")]))

    def test_not_clean_prints_ready_and_reason_without_merge(self):
        cases = {
            "human row": (dict(findings=[(UNIT, "human")]), "1 finding(s) left for a human"),
            "red check": (dict(checks=(GREEN, RED)), "1 check(s) not green"),
            "pending check": (dict(checks=(PENDING,)), "1 check(s) not green"),
            "no checks": (dict(checks=()), "no CI checks"),
            "stale head": (dict(pr_head="0" * 40), f"PR head isn't {BRANCH}'s local head"),
            "stacked base": (dict(base="u0-branch"), "stacked on u0-branch"),
        }
        for name, (kwargs, reason) in cases.items():
            with self.subTest(name):
                r = self.go(on=True, auto_merge="squash", **kwargs)
                self.assertEqual((r.code, r.out), (0, [READY, no_auto_merge(reason)]))

    def test_not_clean_and_already_ready_prints_ready_url_and_reason(self):
        r = self.go(on=True, auto_merge="squash", draft=False, checks=(RED,))
        self.assertEqual((r.code, r.out), (0, [f"ready: {URL}", no_auto_merge("1 check(s) not green")]))

    def test_not_clean_without_method_has_no_reason_line(self):
        r = self.go(on=True, checks=(RED,))
        self.assertEqual((r.code, r.out), (0, [READY]))

    def test_other_units_human_row_and_other_statuses_do_not_block_merge(self):
        r = self.go(on=True, auto_merge="squash", findings=[("u2", "human"), (UNIT, "open"), (UNIT, "fixed")])
        self.assertEqual((r.code, r.out), (0, [READY, merge_line("squash")]))

    def test_check_kinds_that_count_as_green(self):
        checks = (
            GREEN,
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SKIPPED"},
            {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "NEUTRAL"},
            {"__typename": "StatusContext", "state": "SUCCESS"},
        )
        r = self.go(on=True, auto_merge="squash", checks=checks)
        self.assertEqual((r.code, r.out), (0, [READY, merge_line("squash")]))

    def test_failed_status_context_is_not_green(self):
        checks = (GREEN, {"__typename": "StatusContext", "state": "FAILURE"})
        r = self.go(on=True, auto_merge="squash", checks=checks)
        self.assertEqual((r.code, r.out), (0, [READY, no_auto_merge("1 check(s) not green")]))


class NotReady(PrReadyCase):
    def test_pr_not_open_exits_1(self):
        for autopilot in (False, True):
            for state in ("CLOSED", "MERGED"):
                with self.subTest(autopilot=autopilot, state=state):
                    r = self.go(on=autopilot, auto_merge="squash" if autopilot else None, state=state)
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

    def test_bad_auto_merge_value(self):
        self.assertRefused(self.go(on=True, auto_merge="yolo"), "ADMIRAL_AUTO_MERGE must be")

    def test_bad_auto_merge_value_autopilot_off(self):
        self.assertRefused(self.go(auto_merge="yolo"), "ADMIRAL_AUTO_MERGE must be")

    def test_bad_auto_merge_value_with_only_the_env_half_on(self):
        self.assertRefused(self.go(env_autopilot="1", auto_merge="Squash"), "ADMIRAL_AUTO_MERGE must be")

    def test_missing_state_md_exits_5_with_stderr(self):
        run = self.tmp / "empty"
        run.mkdir()
        (run / "team.env").write_text(f"REPO={self.repo}\nBASE_BRANCH={BASE}\n")
        proc = subprocess.run([str(SCRIPT), str(run), UNIT], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((proc.returncode, proc.stdout), (5, ""))
        self.assertNotEqual(proc.stderr, "")


if __name__ == "__main__":
    unittest.main()
