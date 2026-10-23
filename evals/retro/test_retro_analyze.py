"""Tests for skills/engineering/retro/scripts/retro-analyze.py.

The only seam is the script's command line: records in (an `admiral outcomes` file plus a teams
directory), files out (`analysis.json`, `retro.md`). Every test runs the script as a subprocess and
reads what it wrote. Expected values are literals worked out by hand from the fixtures.

Run from the repo root: python3 -m unittest discover -s evals/retro -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPT = REPO / "skills" / "engineering" / "retro" / "scripts" / "retro-analyze.py"
FIXTURES = HERE / "fixtures"
MARKDOWNLINT = ["markdownlint-cli2@0.23.2", "--config", str(REPO / ".markdownlint-cli2.jsonc")]

PANEL = "github-2/prs-needs-review"
OTHER_PANEL = "github-2/issues-ready"
UNTIL = "2026-09-30T00:00:00Z"
PR = "https://github.com/example/fixture/pull/%d"
COMMAND = "Bash(gh api user --jq .login)"
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def same_path(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


class Log:
    """Builds `admiral outcomes` records in Admiral's real shapes, with ts rising one minute a call."""

    def __init__(self, start="2026-09-10T09:00:00Z"):
        self.now = parse_ts(start)
        self.records = []

    def add(self, ship, event, ts=None, **fields):
        if ts is None:
            self.now += timedelta(minutes=1)
            ts = self.now.astimezone(timezone.utc).strftime(TS_FORMAT)
        self.records.append({"v": 1, "ts": ts, "ship": ship, "event": event, **fields})
        return ts

    def launch(self, ship, number, panel=PANEL, autopilot=True, ts=None):
        source, name = panel.split("/")
        return self.add(
            ship,
            "launched",
            ts,
            fleet="main",
            harness="claude",
            skill={"kind": "skill", "name": "commodore"},
            source=source,
            panel=name,
            order_id=str(number),
            order_url=PR % number,
            title=f"Fixture order {number}",
            dir="/work/fixture",
            autopilot=autopilot,
        )

    def stop(self, ship, reason, ts=None):
        return self.add(ship, "needs_you", ts, reason=reason)

    def wait(self, ship, seconds, ts=None):
        return self.add(ship, "underway", ts, waited_s=seconds)

    def end(self, ship, report="default", ts=None):
        if report == "default":
            report = {"version": 1, "result": "done", "why": "finished"}
        return self.add(
            ship,
            "ended",
            ts,
            exit_code=0,
            signal=None,
            duration_s=600,
            needs_you_count=0,
            needs_you_s=0,
            report=report,
        )

    def run(self, ship, number, reasons=(), **launch):
        """A whole panel run: launch, one stop per reason, then ended with a done report."""
        self.launch(ship, number, **launch)
        for reason in reasons:
            self.stop(ship, reason)
        self.end(ship)

    def submit(self, ship, edited, ts=None):
        return self.add(
            ship, "review_submitted", ts, item="rev-" + ship, kind="review", review_event="COMMENT", edited=edited
        )

    def discard(self, ship, ts=None, **flags):
        return self.add(ship, "review_discarded", ts, item="rev-" + ship, kind="review", **flags)

    def card(self, ship, decision, ts=None):
        return self.add(ship, "card_" + decision, ts, item="find-" + ship, kind="findings", card="c1")

    def skipped(self, event="skipped", panel=PANEL, ts=None):
        source, name = panel.split("/")
        return self.add(
            "", event, ts, source=source, panel=name, order_id="900", title="Fixture order 900", reason="at cap"
        )


def retro_report(panel=PANEL, until="2026-09-09T00:00:00Z"):
    return {
        "version": 1,
        "result": "done",
        "why": "retro written",
        "retro": {"panel": panel, "since": None, "until": until, "pr": None},
    }


def order_state(number, calls=None):
    """A Commodore state.md for the run on PR `number`; `calls` is the body of ## Autopilot calls."""
    text = "# Run state\n\n## Order\n\n- Order: <%s>\n" % (PR % number)
    if calls is not None:
        text += f"\n## Autopilot calls\n\n{calls}\n\n## Notes\n\nNothing else.\n"
    return text


class Sandbox:
    """A temp tree the script runs in: it is the cwd, and holds decoys the script must never touch."""

    def __init__(self, testcase):
        self.tc = testcase
        tmp = tempfile.TemporaryDirectory(prefix="retro-test-")
        testcase.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / "home"
        self.claude = self.root / "claude"
        self.teams = self.root / "teams"
        self.admiral = self.root / "admiral-home"
        self.out = self.root / "out"
        self.outcomes = self.root / "outcomes.jsonl"
        self.marker = self.root / "admiral-was-run"
        for d in (self.home, self.claude, self.teams, self.out, self.admiral / "outcomes", self.root / "bin"):
            d.mkdir(parents=True)
        (self.root / "config.json").write_text('{"sources": {"decoy": true}}\n', encoding="utf-8")
        # Decoys: the script must read neither $ADMIRAL_HOME nor run `admiral`.
        decoy = Log()
        decoy.run("decoy", 999, ["permission:Bash"])
        decoy.run("decoy2", 998, ["permission:Bash"])
        self.write_lines(self.admiral / "outcomes" / "2026-09.jsonl", decoy)
        fake = self.root / "bin" / "admiral"
        fake.write_text(f'#!/bin/sh\ntouch "{self.marker}"\n', encoding="utf-8")
        fake.chmod(0o755)

    @staticmethod
    def write_lines(path, log, raw=()):
        data = b"".join(json.dumps(r).encode("utf-8") + b"\n" for r in log.records) + b"".join(raw)
        path.write_bytes(data)

    def write_state(self, name, text, under=None):
        path = (under or self.teams) / name / "state.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path.parent

    def env(self, extra=None, drop=()):
        env = {
            "PATH": os.pathsep.join([str(self.root / "bin"), "/usr/bin", "/bin"]),
            "HOME": str(self.home),
            "CLAUDE_CONFIG_DIR": str(self.claude),
            "ADMIRAL_HOME": str(self.admiral),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        env.update(extra or {})
        for key in drop:
            env.pop(key, None)
        return env

    def invoke(self, argv, env_extra=None, env_drop=()):
        self.tc.assertTrue(SCRIPT.is_file(), f"retro-analyze.py not found at {SCRIPT}")
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv],
            cwd=self.root,
            env=self.env(env_extra, env_drop),
            capture_output=True,
            check=False,
            timeout=60,
        )

    def argv(self, panel=PANEL, since=None, until=UNTIL, teams=True):
        argv = ["--panel", panel, "--outcomes", str(self.outcomes), "--out", str(self.out)]
        if since:
            argv += ["--since", since]
        if until:
            argv += ["--until", until]
        if teams:
            argv += ["--teams-dir", str(self.teams)]
        return argv

    def snapshot(self, skip=()):
        """Every path under the tree with its mode and bytes, minus the `skip` directories."""
        seen = {}
        for path in sorted(self.root.rglob("*")):
            if any(path == s or s in path.parents for s in skip):
                continue
            rel = str(path.relative_to(self.root))
            seen[rel] = (path.stat().st_mode, None if path.is_dir() else path.read_bytes())
        return seen


class Result:
    def __init__(self, proc, out):
        self.proc = proc
        self.out = out
        self.analysis = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
        self.md = (out / "retro.md").read_text(encoding="utf-8")

    @property
    def summary(self):
        return self.analysis["summary"]

    @property
    def findings(self):
        return self.analysis["findings"]


class RetroCase(unittest.TestCase):
    def sandbox(self):
        return Sandbox(self)

    def analyse(self, log=None, sb=None, raw=(), states=None, expect_ok=True, **argv):
        """Write `log` as the outcomes file, run the script, and return what it wrote."""
        sb = sb or self.sandbox()
        sb.write_lines(sb.outcomes, log or Log(), raw)
        for name, text in (states or {}).items():
            sb.write_state(name, text)
        proc = sb.invoke(sb.argv(**argv))
        if expect_ok:
            self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return Result(proc, sb.out)

    def assert_markdown_clean(self, md_path):
        npx = shutil.which("npx")
        if npx is None:
            self.skipTest("npx not found: cannot run markdownlint-cli2@0.23.2")
        proc = subprocess.run(
            [npx, "-y", *MARKDOWNLINT, md_path.name],
            cwd=md_path.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        # a glob that matches nothing also exits 0, so check the file was actually linted
        self.assertIn("Linting: 1 file", proc.stdout, proc.stdout + proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


_fixture_runs = {}


def fixture_run(case, name):
    """Run the script once per fixture for the whole module; the first caller's assertions apply."""
    if name not in _fixture_runs:
        sb = Sandbox(case)
        fixture = FIXTURES / name
        shutil.copy(fixture / "outcomes.jsonl", sb.outcomes)
        shutil.copytree(fixture / "teams", sb.teams, dirs_exist_ok=True)
        proc = sb.invoke(sb.argv())
        case.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        keep = Path(tempfile.mkdtemp(prefix="retro-fixture-"))
        unittest.addModuleCleanup(shutil.rmtree, keep, True)
        shutil.copytree(sb.out, keep / "out")
        _fixture_runs[name] = (proc, keep / "out", sb.teams)
    proc, out, teams = _fixture_runs[name]
    return Result(proc, out), teams


# --------------------------------------------------------------------------------------------------
# AC1: five review runs, three stopping on the same denied command, one edited review
# --------------------------------------------------------------------------------------------------


class FiveReviewsTest(RetroCase):
    def result(self):
        return fixture_run(self, "five-reviews")

    def test_writes_exactly_the_two_files(self):
        result, _ = self.result()
        self.assertEqual(sorted(p.name for p in result.out.iterdir()), ["analysis.json", "retro.md"])

    def test_period_comes_from_the_last_retro_of_this_panel(self):
        a = self.result()[0].analysis
        self.assertEqual(a["panel"], PANEL)
        self.assertEqual(a["since"], "2026-09-08T00:00:00Z")
        self.assertEqual(a["since_source"], "last_retro")
        self.assertEqual(a["until"], UNTIL)
        self.assertIs(a["changes_proposed"], True)

    def test_runs_are_the_five_autopilot_launches_in_order(self):
        result, teams = self.result()
        runs = result.analysis["runs"]
        self.assertEqual([r["ship"] for r in runs], ["alpha", "bravo", "charlie", "delta", "echo"])
        self.assertEqual([r["order_url"] for r in runs], [PR % n for n in (101, 102, 103, 104, 105)])
        self.assertEqual(
            [r["launched_ts"] for r in runs],
            [
                "2026-09-10T09:00:00Z",
                "2026-09-10T11:00:00Z",
                "2026-09-11T09:00:00Z",
                "2026-09-11T13:00:00Z",
                "2026-09-12T09:00:00Z",
            ],
        )
        self.assertEqual([r["result"] for r in runs], ["done", "done", "done", "partial", "done"])
        for run, name in zip(runs, ("review-101", "review-102", "review-103", "review-104", "review-105")):
            self.assertTrue(same_path(run["run_dir"], teams / name), f"{run['ship']}: {run['run_dir']}")
            self.assertIsNone(run["run_dir_note"])

    def test_summary_values(self):
        s = self.result()[0].summary
        self.assertEqual(s["runs"], 5)
        self.assertEqual(s["results"], {"done": 4, "partial": 1})
        self.assertEqual(s["needs_you_by_reason"], {"stop": 5, "permission:Bash": 3})
        self.assertEqual(s["guard_denied"], 1)
        self.assertEqual(s["median_wait_s"], 82.5)
        self.assertEqual(s["calls"], {"total": 5, "high_stakes": 3, "low_stakes": 2})
        self.assertEqual(
            s["engineer_actions"],
            {"accepted": 3, "edited": 1, "rejected": 0, "discarded_other": 1, "answered": 1},
        )
        self.assertEqual(s["not_launched"], {"skipped": 1})
        self.assertEqual(s["skipped_lines"], 0)

    def test_exactly_one_finding_for_the_repeated_permission_stop(self):
        findings = self.result()[0].findings
        self.assertEqual(len(findings), 1, findings)
        f = findings[0]
        self.assertEqual(f["id"], "F1")
        self.assertEqual(f["kind"], "repeated_stop")
        self.assertEqual(f["reason"], "permission:Bash")
        self.assertIsNone(f["detail"])
        self.assertEqual(f["runs"], 3)
        self.assertEqual(f["ships"], ["alpha", "bravo", "charlie"])
        self.assertIsNone(f["proposed"])

    def test_finding_evidence_names_the_denied_command(self):
        result, teams = self.result()
        evidence = result.findings[0]["evidence"]
        self.assertEqual(
            [(e["ts"], e["ship"], e["order_url"]) for e in evidence],
            [
                ("2026-09-10T09:10:00Z", "alpha", PR % 101),
                ("2026-09-10T11:10:00Z", "bravo", PR % 102),
                ("2026-09-11T09:10:00Z", "charlie", PR % 103),
            ],
        )
        for entry, name in zip(evidence, ("review-101", "review-102", "review-103")):
            self.assertTrue(same_path(entry["run_dir"], teams / name))
            self.assertIn(COMMAND, entry["autopilot_calls"])
            # the section stops at the next heading
            self.assertNotIn("Review drafted and handed", entry["autopilot_calls"])

    def test_edited_review_is_listed_with_its_link_target(self):
        edited = self.result()[0].analysis["edited_reviews"]
        self.assertEqual(len(edited), 1, edited)
        self.assertEqual(
            {k: edited[0][k] for k in ("ship", "order_url", "ts", "event")},
            {
                "ship": "bravo",
                "order_url": PR % 102,
                "ts": "2026-09-10T11:30:00Z",
                "event": "review_submitted",
            },
        )

    def test_overturned_low_stakes_calls_are_marked_unrecorded(self):
        self.assertEqual(
            self.result()[0].analysis["overturned_low_stakes"],
            {"recorded": False, "note": "Admiral doesn't record overturned low-stakes calls"},
        )

    def test_retro_md_has_a_summary_table(self):
        md = self.result()[0].md
        table = [line for line in md.splitlines() if line.startswith("|")]
        self.assertTrue(any(re.match(r"^\|(\s*:?-{3,}:?\s*\|)+\s*$", line) for line in table), "no table separator")
        self.assertTrue(any("Runs" in line and re.search(r"\b5\b", line) for line in table), table)
        self.assertTrue(any("permission:Bash" in line and re.search(r"\b3\b", line) for line in table), table)
        self.assertTrue(any("edian" in line and "82.5" in line for line in table), table)

    def test_retro_md_has_one_finding_section_with_placeholders(self):
        md = self.result()[0].md
        self.assertEqual(md.count("Cause:"), 1)
        self.assertEqual(md.count("Proposed change:"), 1)
        for ts in ("2026-09-10T09:10:00Z", "2026-09-10T11:10:00Z", "2026-09-11T09:10:00Z"):
            self.assertIn(ts, md)
        for ship in ("alpha", "bravo", "charlie"):
            self.assertIn(ship, md)
        self.assertNotIn("No changes proposed.", md)

    def test_retro_md_links_the_edited_review(self):
        md = self.result()[0].md
        self.assertRegex(md, r"\[[^\]\n]+\]\(https://github\.com/example/fixture/pull/102\)")
        self.assertRegex(md, r"(?i)edit")

    def test_retro_md_says_overturned_calls_are_not_recorded_and_resumed_legs_are_not_counted(self):
        md = self.result()[0].md
        self.assertIn("Admiral doesn't record overturned low-stakes calls", md)
        self.assertRegex(md, r"(?i)resumed legs")

    def test_retro_md_passes_markdownlint(self):
        result, _ = self.result()
        self.assert_markdown_clean(result.out / "retro.md")


# --------------------------------------------------------------------------------------------------
# AC2: nothing repeats
# --------------------------------------------------------------------------------------------------


class NoRepeatsTest(RetroCase):
    def result(self):
        return fixture_run(self, "no-repeats")

    def test_no_findings_and_no_changes_proposed(self):
        result, _ = self.result()
        self.assertEqual(result.findings, [])
        self.assertIs(result.analysis["changes_proposed"], False)
        self.assertRegex(result.md, r"(?m)^No changes proposed\.$")
        self.assertNotIn("Proposed change:", result.md)
        self.assertNotIn("Cause:", result.md)

    def test_period_comes_from_the_last_retro(self):
        a = self.result()[0].analysis
        self.assertEqual((a["since"], a["since_source"]), ("2026-09-14T00:00:00Z", "last_retro"))

    def test_only_this_panels_autopilot_runs_count(self):
        runs = self.result()[0].analysis["runs"]
        self.assertEqual([r["ship"] for r in runs], ["alpha", "bravo", "echo", "delta"])
        self.assertEqual([r["order_url"] for r in runs], [PR % n for n in (301, 302, 304, 305)])

    def test_run_dirs(self):
        result, teams = self.result()
        by_ship = {r["ship"]: r for r in result.analysis["runs"]}
        self.assertTrue(same_path(by_ship["alpha"]["run_dir"], teams / "review-301"))
        self.assertTrue(same_path(by_ship["echo"]["run_dir"], teams / "review-304"))
        for ship in ("bravo", "delta"):
            self.assertIsNone(by_ship[ship]["run_dir"])
            self.assertEqual(by_ship[ship]["run_dir_note"], "state.md not found")

    def test_summary_values(self):
        s = self.result()[0].summary
        self.assertEqual(s["runs"], 4)
        self.assertEqual(s["results"], {"done": 2, "no_report": 1, "no_ended": 1})
        self.assertEqual(
            s["needs_you_by_reason"],
            {"stop": 1, "question": 1, "idle": 2, "permission:Bash": 1, "unknown": 1},
        )
        self.assertEqual(s["guard_denied"], 1)
        self.assertEqual(s["median_wait_s"], 40)
        self.assertEqual(s["calls"], {"total": 3, "high_stakes": 1, "low_stakes": 2})
        self.assertEqual(
            s["engineer_actions"],
            {"accepted": 2, "edited": 1, "rejected": 2, "discarded_other": 1, "answered": 1},
        )
        self.assertEqual(s["not_launched"], {"skipped": 1})

    def test_edited_and_rejected_items_are_listed_even_though_they_do_not_repeat(self):
        edited = self.result()[0].analysis["edited_reviews"]
        self.assertEqual(
            [(e["ship"], e["order_url"], e["ts"], e["event"]) for e in edited],
            [
                ("echo", PR % 304, "2026-09-16T09:20:00Z", "review_submitted"),
                ("delta", PR % 305, "2026-09-16T13:11:00Z", "card_rejected"),
                ("delta", PR % 305, "2026-09-16T13:12:00Z", "review_discarded"),
            ],
        )

    def test_retro_md_lists_the_edited_review_as_a_link(self):
        self.assertRegex(self.result()[0].md, r"\]\(https://github\.com/example/fixture/pull/304\)")

    def test_retro_md_passes_markdownlint(self):
        result, _ = self.result()
        self.assert_markdown_clean(result.out / "retro.md")


# --------------------------------------------------------------------------------------------------
# Panel runs: which launches count, and which records belong to them
# --------------------------------------------------------------------------------------------------


class PanelRunsTest(RetroCase):
    def test_hand_launch_is_not_a_panel_run(self):
        log = Log()
        log.run("auto", 1, ["stop"])
        log.run("hand", 2, ["permission:Bash"], autopilot=False)
        log.submit("hand", True)
        r = self.analyse(log)
        self.assertEqual([x["ship"] for x in r.analysis["runs"]], ["auto"])
        self.assertEqual(r.summary["needs_you_by_reason"], {"stop": 1})
        self.assertEqual(r.summary["engineer_actions"]["edited"], 0)

    def test_other_panel_and_other_source_are_not_this_panel(self):
        log = Log()
        log.run("mine", 1, ["stop"])
        log.run("other-panel", 2, ["permission:Bash"], panel=OTHER_PANEL)
        log.run("other-source", 3, ["permission:Bash"], panel="github-3/prs-needs-review")
        log.run("resumed-leg", 4, ["permission:Bash"], panel="github-2/resume")
        r = self.analyse(log)
        self.assertEqual([x["ship"] for x in r.analysis["runs"]], ["mine"])
        self.assertEqual(r.summary["needs_you_by_reason"], {"stop": 1})
        self.assertEqual(r.findings, [])

    def test_retro_run_is_never_a_panel_run_even_launched_on_the_panel(self):
        log = Log()
        log.launch("retro", 5)
        log.stop("retro", "question")
        log.end("retro", retro_report(until="2026-09-10T00:00:00Z"))
        log.run("real", 6, ["stop"])
        r = self.analyse(log)
        self.assertEqual([x["ship"] for x in r.analysis["runs"]], ["real"])
        self.assertEqual(r.summary["needs_you_by_reason"], {"stop": 1})
        self.assertEqual(r.analysis["since_source"], "last_retro")

    def test_ship_names_are_reused_and_records_follow_the_latest_launch(self):
        log = Log()
        log.run("echo", 1, ["stop"])
        log.launch("echo", 2, panel=OTHER_PANEL)
        log.stop("echo", "permission:Bash")
        log.end("echo")
        log.launch("echo", 3)
        log.stop("echo", "question")
        log.submit("echo", True)
        log.end("echo")
        r = self.analyse(log)
        self.assertEqual([x["order_url"] for x in r.analysis["runs"]], [PR % 1, PR % 3])
        self.assertEqual(r.summary["needs_you_by_reason"], {"stop": 1, "question": 1})
        edited = r.analysis["edited_reviews"]
        self.assertEqual([e["order_url"] for e in edited], [PR % 3])

    def test_records_of_a_ship_with_no_launch_are_ignored(self):
        log = Log()
        log.stop("ghost", "permission:Bash")
        log.submit("ghost", True)
        log.end("ghost")
        log.run("real", 1, ["stop"])
        r = self.analyse(log)
        self.assertEqual(r.summary["runs"], 1)
        self.assertEqual(r.summary["results"], {"done": 1})
        self.assertEqual(r.summary["needs_you_by_reason"], {"stop": 1})
        self.assertEqual(r.summary["engineer_actions"]["edited"], 0)

    def test_last_ended_wins(self):
        log = Log()
        log.launch("a", 1)
        log.end("a", {"version": 1, "result": "failed", "why": "first", "assumptions": ["asked: x"]})
        log.end("a", {"version": 1, "result": "done", "why": "second", "assumptions": ["default: y"]})
        r = self.analyse(log)
        self.assertEqual(r.summary["results"], {"done": 1})
        self.assertEqual(r.analysis["runs"][0]["result"], "done")
        self.assertEqual(r.summary["calls"], {"total": 1, "high_stakes": 0, "low_stakes": 1})

    def test_ended_report_cases(self):
        log = Log()
        log.launch("no-ended", 1)
        log.launch("null-report", 2)
        log.end("null-report", None)
        r = self.analyse(log)
        self.assertEqual(r.summary["results"], {"no_ended": 1, "no_report": 1})

    def test_ended_without_a_launch_is_ignored(self):
        log = Log()
        log.end("late")
        r = self.analyse(log)
        self.assertEqual(r.summary["runs"], 0)
        self.assertEqual(r.summary["results"], {})

    def test_window_is_inclusive_and_events_do_not_leak_from_runs_launched_outside_it(self):
        log = Log()
        log.launch("early", 1, ts="2026-09-10T09:59:59Z")
        log.stop("early", "question", ts="2026-09-10T10:30:00Z")
        log.launch("first", 2, ts="2026-09-10T10:00:00Z")
        log.launch("last", 3, ts="2026-09-12T10:00:00Z")
        log.launch("late", 4, ts="2026-09-12T10:00:01Z")
        log.stop("late", "question", ts="2026-09-12T10:05:00Z")
        r = self.analyse(log, since="2026-09-10T10:00:00Z", until="2026-09-12T10:00:00Z")
        self.assertEqual([x["ship"] for x in r.analysis["runs"]], ["first", "last"])
        self.assertEqual(r.summary["needs_you_by_reason"], {})

    def test_ties_go_by_line_order(self):
        log = Log()
        same = "2026-09-10T10:00:00Z"
        log.launch("echo", 1, ts=same)
        log.stop("echo", "question", ts=same)
        log.end("echo", ts=same)
        log.launch("echo", 2, ts=same)
        log.stop("echo", "permission:Bash", ts=same)
        r = self.analyse(log)
        self.assertEqual(r.summary["runs"], 2)
        self.assertEqual(r.summary["needs_you_by_reason"], {"question": 1, "permission:Bash": 1})
        self.assertEqual([x["result"] for x in r.analysis["runs"]], ["done", "no_ended"])

    def test_ship_less_events_are_counted_by_event_and_make_no_findings(self):
        log = Log()
        for _ in range(3):
            log.skipped("skipped")
        log.skipped("launch_failed")
        log.skipped("resource_wait")
        log.skipped("skipped", panel=OTHER_PANEL)
        log.skipped("skipped", panel="github-3/prs-needs-review")
        log.add("zed", "resumed", source="github-2", panel="prs-needs-review", order="x")
        log.add("zed", "dismissed")
        r = self.analyse(log)
        self.assertEqual(r.summary["runs"], 0)
        self.assertEqual(r.summary["not_launched"], {"skipped": 3, "launch_failed": 1, "resource_wait": 1})
        self.assertEqual(r.findings, [])
        self.assertIs(r.analysis["changes_proposed"], False)

    def test_empty_outcomes_file(self):
        r = self.analyse(Log())
        self.assertEqual(r.summary["runs"], 0)
        self.assertIsNone(r.summary["median_wait_s"])
        self.assertEqual(r.findings, [])
        self.assertRegex(r.md, r"(?m)^No changes proposed\.$")


# --------------------------------------------------------------------------------------------------
# --since, last retro, --until
# --------------------------------------------------------------------------------------------------


class PeriodTest(RetroCase):
    def two_days(self):
        log = Log()
        log.launch("retro", 9, panel="manual/hand", autopilot=False, ts="2026-09-09T12:00:00Z")
        log.end("retro", retro_report(until="2026-09-10T00:00:00Z"))
        log.run("day10", 1, ["stop"])
        log.launch("day11", 2, ts="2026-09-11T10:00:00Z")
        log.end("day11")
        return log

    def test_since_flag_wins(self):
        r = self.analyse(self.two_days(), since="2026-09-11T00:00:00Z")
        self.assertEqual(r.analysis["since"], "2026-09-11T00:00:00Z")
        self.assertEqual(r.analysis["since_source"], "flag")
        self.assertEqual([x["ship"] for x in r.analysis["runs"]], ["day11"])

    def test_default_is_the_last_retro_found_by_its_report_panel_not_by_how_it_was_launched(self):
        r = self.analyse(self.two_days())
        self.assertEqual(r.analysis["since"], "2026-09-10T00:00:00Z")
        self.assertEqual(r.analysis["since_source"], "last_retro")
        self.assertEqual([x["ship"] for x in r.analysis["runs"]], ["day10", "day11"])

    def test_newest_ended_retro_of_this_panel_wins(self):
        log = Log()
        log.launch("old", 1, ts="2026-09-02T10:00:00Z")
        log.end("old", retro_report(until="2026-09-03T00:00:00Z"), ts="2026-09-02T10:10:00Z")
        log.launch("new", 2, ts="2026-09-05T10:00:00Z")
        log.end("new", retro_report(until="2026-09-06T00:00:00Z"), ts="2026-09-05T10:10:00Z")
        log.launch("elsewhere", 3, panel=OTHER_PANEL, ts="2026-09-08T10:00:00Z")
        log.end("elsewhere", retro_report(panel=OTHER_PANEL, until="2026-09-09T00:00:00Z"), ts="2026-09-08T10:10:00Z")
        r = self.analyse(log)
        self.assertEqual((r.analysis["since"], r.analysis["since_source"]), ("2026-09-06T00:00:00Z", "last_retro"))

    def test_no_retro_means_all_records(self):
        log = Log()
        log.run("ancient", 1, ["stop"])
        r = self.analyse(log)
        self.assertIsNone(r.analysis["since"])
        self.assertEqual(r.analysis["since_source"], "all")
        self.assertEqual(r.summary["runs"], 1)

    def test_since_accepts_an_offset(self):
        log = Log()
        log.launch("before", 1, ts="2026-09-10T23:59:59Z")
        log.launch("at", 2, ts="2026-09-11T00:00:00Z")
        r = self.analyse(log, since="2026-09-11T02:00:00+02:00")
        self.assertEqual([x["ship"] for x in r.analysis["runs"]], ["at"])

    def test_until_defaults_to_now(self):
        before = datetime.now(timezone.utc) - timedelta(seconds=2)
        r = self.analyse(Log(), until=None)
        after = datetime.now(timezone.utc) + timedelta(seconds=2)
        self.assertTrue(before <= parse_ts(r.analysis["until"]) <= after, r.analysis["until"])


# --------------------------------------------------------------------------------------------------
# Run directory lookup
# --------------------------------------------------------------------------------------------------


class RunDirTest(RetroCase):
    def one_run(self, number=12, report="default", states=None, sb=None, teams=True):
        log = Log()
        log.launch("ship", number)
        log.end("ship", report)
        r = self.analyse(log, sb=sb, states=states, teams=teams)
        return r.analysis["runs"][0]

    @staticmethod
    def resume(name):
        return {"version": 1, "result": "partial", "why": "stopped", "resume": "/commodore resume " + name}

    def test_resume_names_the_directory(self):
        sb = self.sandbox()
        run = self.one_run(report=self.resume("my-run.1_x"), states={"my-run.1_x": "# State\n"}, sb=sb)
        self.assertTrue(same_path(run["run_dir"], sb.teams / "my-run.1_x"), run)
        self.assertIsNone(run["run_dir_note"])

    def test_resume_wins_over_a_url_match(self):
        sb = self.sandbox()
        states = {"named": "# State\n", "other": order_state(12), "another": order_state(12)}
        run = self.one_run(report=self.resume("named"), states=states, sb=sb)
        self.assertTrue(same_path(run["run_dir"], sb.teams / "named"), run)

    def test_resume_without_a_state_file_falls_back_to_the_url(self):
        sb = self.sandbox()
        (sb.teams / "named").mkdir()
        run = self.one_run(report=self.resume("named"), states={"by-url": order_state(12)}, sb=sb)
        self.assertTrue(same_path(run["run_dir"], sb.teams / "by-url"), run)

    def test_resume_names_that_could_leave_the_teams_directory_are_not_used(self):
        for text in ("..", "../outside", "a/b", ".hidden", "-dash", "run-1 extra", "run-1/"):
            with self.subTest(resume=text):
                sb = self.sandbox()
                (sb.root / "state.md").write_text("# State\n", encoding="utf-8")
                sb.write_state("outside", "# State\n", under=sb.root)
                for name in ("a/b", ".hidden", "-dash", "run-1"):
                    sb.write_state(name, "# State\n")
                report = {"version": 1, "result": "partial", "why": "x", "resume": "/commodore resume " + text}
                run = self.one_run(report=report, sb=sb)
                self.assertIsNone(run["run_dir"])
                self.assertEqual(run["run_dir_note"], "state.md not found")

    def test_resume_text_must_be_the_exact_command(self):
        sb = self.sandbox()
        sb.write_state("run-1", "# State\n")
        report = {"version": 1, "result": "partial", "why": "x", "resume": "commodore resume run-1"}
        run = self.one_run(report=report, sb=sb)
        self.assertIsNone(run["run_dir"])

    def test_url_must_be_a_whole_url(self):
        cases = [
            ("pull/123 only", "see <%s>" % (PR % 123), False),
            ("letter after", "see " + PR % 12 + "abc", False),
            ("review anchor", "see " + PR % 12 + "#pullrequestreview-5", True),
            ("files tab", "see " + PR % 12 + "/files", True),
            ("angle brackets", "see <%s>" % (PR % 12), True),
            ("end of text", "see " + PR % 12, True),
            ("full stop", "see " + PR % 12 + ".", True),
            ("closing paren", "(" + PR % 12 + ")", True),
        ]
        for label, text, matches in cases:
            with self.subTest(label):
                sb = self.sandbox()
                (sb.teams / "d").mkdir()
                (sb.teams / "d" / "state.md").write_text("# State\n\n" + text, encoding="utf-8")
                run = self.one_run(sb=sb)
                if matches:
                    self.assertTrue(same_path(run["run_dir"], sb.teams / "d"), run)
                    self.assertIsNone(run["run_dir_note"])
                else:
                    self.assertIsNone(run["run_dir"])
                    self.assertEqual(run["run_dir_note"], "state.md not found")

    def test_two_matching_state_files_are_ambiguous(self):
        run = self.one_run(states={"one": order_state(12), "two": order_state(12)})
        self.assertIsNone(run["run_dir"])
        self.assertEqual(run["run_dir_note"], "ambiguous")

    def test_no_match_and_a_missing_teams_directory(self):
        run = self.one_run(states={"unrelated": order_state(77)})
        self.assertEqual((run["run_dir"], run["run_dir_note"]), (None, "state.md not found"))
        sb = self.sandbox()
        shutil.rmtree(sb.teams)
        run = self.one_run(sb=sb)
        self.assertEqual((run["run_dir"], run["run_dir_note"]), (None, "state.md not found"))

    def test_teams_dir_default_chain(self):
        for label, env, drop, expected in (
            ("AGENT_TEAMS_DIR", {"AGENT_TEAMS_DIR": "agent"}, (), "from-agent"),
            ("CLAUDE_CONFIG_DIR", {}, ("AGENT_TEAMS_DIR",), "from-claude"),
            ("HOME", {}, ("AGENT_TEAMS_DIR", "CLAUDE_CONFIG_DIR"), "from-home"),
        ):
            with self.subTest(label):
                sb = self.sandbox()
                where = {
                    "from-agent": sb.root / "agent",
                    "from-claude": sb.claude / "teams",
                    "from-home": sb.home / ".claude" / "teams",
                }
                for name, under in where.items():
                    sb.write_state(name, order_state(12), under=under)
                sb.write_lines(sb.outcomes, self.single_run())
                extra = {key: str(sb.root / value) for key, value in env.items()}
                proc = sb.invoke(sb.argv(teams=False), extra, drop)
                self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
                run = Result(proc, sb.out).analysis["runs"][0]
                self.assertTrue(same_path(run["run_dir"], where[expected] / expected), run)

    def test_teams_dir_flag_beats_the_environment(self):
        sb = self.sandbox()
        sb.write_state("from-flag", order_state(12))
        sb.write_state("from-env", order_state(12), under=sb.root / "agent")
        sb.write_lines(sb.outcomes, self.single_run())
        proc = sb.invoke(sb.argv(), {"AGENT_TEAMS_DIR": str(sb.root / "agent")})
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        run = Result(proc, sb.out).analysis["runs"][0]
        self.assertTrue(same_path(run["run_dir"], sb.teams / "from-flag"), run)

    @staticmethod
    def single_run():
        log = Log()
        log.run("ship", 12)
        return log


# --------------------------------------------------------------------------------------------------
# Findings: which stops and actions repeat
# --------------------------------------------------------------------------------------------------


class StopFindingsTest(RetroCase):
    def test_reasons_that_repeat_across_two_runs_are_findings(self):
        for reason in ("question", "permission", "permission:Bash", "notification", "notification:idle_prompt"):
            with self.subTest(reason):
                log = Log()
                log.run("a", 1, [reason])
                log.run("b", 2, [reason])
                log.run("c", 3, ["stop"])
                r = self.analyse(log)
                self.assertEqual(len(r.findings), 1, r.findings)
                f = r.findings[0]
                self.assertEqual((f["id"], f["kind"], f["reason"], f["detail"]), ("F1", "repeated_stop", reason, None))
                self.assertEqual((f["runs"], f["ships"]), (2, ["a", "b"]))
                self.assertIs(r.analysis["changes_proposed"], True)

    def test_stop_idle_and_unknown_count_in_the_summary_only(self):
        log = Log()
        for i, ship in enumerate(("a", "b", "c")):
            log.run(ship, i + 1, ["stop", "idle", "unknown"])
        r = self.analyse(log)
        self.assertEqual(r.findings, [])
        self.assertEqual(r.summary["needs_you_by_reason"], {"stop": 3, "idle": 3, "unknown": 3})
        self.assertIs(r.analysis["changes_proposed"], False)

    def test_a_stop_repeated_inside_one_run_is_not_a_repeat(self):
        log = Log()
        log.run("a", 1, ["question", "question", "question"])
        r = self.analyse(log)
        self.assertEqual(r.findings, [])
        self.assertEqual(r.summary["needs_you_by_reason"], {"question": 3})

    def test_runs_counts_distinct_runs(self):
        log = Log()
        log.run("a", 1, ["question", "question"])
        log.run("b", 2, ["question"])
        f = self.analyse(log).findings[0]
        self.assertEqual((f["runs"], f["ships"]), (2, ["a", "b"]))

    def test_tools_are_distinct_keys(self):
        log = Log()
        log.run("a", 1, ["permission:Bash"])
        log.run("b", 2, ["permission:Write"])
        log.run("c", 3, ["permission:Bash"])
        findings = self.analyse(log).findings
        self.assertEqual([(f["reason"], f["runs"]) for f in findings], [("permission:Bash", 2)])

    def test_ids_follow_first_evidence(self):
        log = Log()
        log.run("a", 1, ["permission:Bash"])
        log.run("b", 2, ["question"])
        log.run("c", 3, ["question"])
        log.run("d", 4, ["permission:Bash"])
        findings = self.analyse(log).findings
        self.assertEqual([(f["id"], f["reason"]) for f in findings], [("F1", "permission:Bash"), ("F2", "question")])

    def test_guard_denied_repeats_by_rule(self):
        log = Log()
        log.launch("a", 1)
        log.add("a", "guard_denied", rule="Bash(rm:*)", tool="Bash")
        log.end("a")
        log.launch("b", 2)
        log.add("b", "guard_denied", rule="Bash(rm:*)", tool="Bash")
        log.end("b")
        r = self.analyse(log)
        self.assertEqual(r.summary["guard_denied"], 2)
        self.assertEqual(len(r.findings), 1, r.findings)
        f = r.findings[0]
        self.assertEqual(
            (f["kind"], f["reason"], f["detail"], f["runs"]), ("repeated_stop", "guard_denied", "Bash(rm:*)", 2)
        )
        self.assertIsNone(f["evidence"][0]["autopilot_calls"])

    def test_guard_denied_with_different_rules_is_not_a_repeat(self):
        log = Log()
        for ship, n, rule in (("a", 1, "Bash(rm:*)"), ("b", 2, "Bash(curl:*)")):
            log.launch(ship, n)
            log.add(ship, "guard_denied", rule=rule)
            log.end(ship)
        r = self.analyse(log)
        self.assertEqual(r.summary["guard_denied"], 2)
        self.assertEqual(r.findings, [])

    def test_guard_denied_does_not_count_as_a_needs_you_reason(self):
        log = Log()
        log.launch("a", 1)
        log.add("a", "guard_denied", rule="Bash(rm:*)")
        r = self.analyse(log)
        self.assertEqual(r.summary["needs_you_by_reason"], {})


class AutopilotCallsTest(RetroCase):
    def two_permission_runs(self, states, reason="permission:Bash"):
        log = Log()
        log.run("a", 1, [reason])
        log.run("b", 2, [reason])
        return self.analyse(log, states=states)

    def test_section_text_is_attached_up_to_the_next_heading(self):
        r = self.two_permission_runs({"x": order_state(1, f"- denied `{COMMAND}`"), "y": order_state(2, "- nothing")})
        calls = [e["autopilot_calls"] for e in r.findings[0]["evidence"]]
        self.assertIn(COMMAND, calls[0])
        self.assertIn("nothing", calls[1])
        self.assertNotIn("Nothing else.", calls[0])

    def test_section_at_the_end_of_the_file(self):
        text = "# State\n\n- Order: <%s>\n\n## Autopilot calls\n\n- last words\n" % (PR % 1)
        r = self.two_permission_runs({"x": text})
        self.assertIn("last words", r.findings[0]["evidence"][0]["autopilot_calls"])

    def test_bare_permission_gets_the_section_too(self):
        r = self.two_permission_runs({"x": order_state(1, "- bare permission")}, reason="permission")
        self.assertIn("bare permission", r.findings[0]["evidence"][0]["autopilot_calls"])

    def test_null_without_a_state_file_or_a_section(self):
        r = self.two_permission_runs({"x": "# State\n\n- Order: <%s>\n\n## Notes\n\nNo calls here.\n" % (PR % 1)})
        self.assertEqual([e["autopilot_calls"] for e in r.findings[0]["evidence"]], [None, None])

    def test_only_permission_stops_carry_the_section(self):
        log = Log()
        log.run("a", 1, ["question"])
        log.run("b", 2, ["question"])
        r = self.analyse(log, states={"x": order_state(1, "- a call"), "y": order_state(2, "- a call")})
        self.assertEqual([e["autopilot_calls"] for e in r.findings[0]["evidence"]], [None, None])

    def test_long_sections_are_cut_at_4000_characters(self):
        r = self.two_permission_runs({"x": order_state(1, "y" * 6000)})
        calls = r.findings[0]["evidence"][0]["autopilot_calls"]
        self.assertLessEqual(len(calls), 4000)
        self.assertGreater(len(calls), 3000)


class ActionFindingsTest(RetroCase):
    def test_edited_reviews_and_cards_together_repeat_across_runs(self):
        log = Log()
        log.launch("a", 1)
        log.submit("a", True)
        log.end("a")
        log.launch("b", 2)
        log.card("b", "edited")
        log.end("b")
        r = self.analyse(log)
        self.assertEqual(r.summary["engineer_actions"]["edited"], 2)
        self.assertEqual(len(r.findings), 1, r.findings)
        f = r.findings[0]
        self.assertEqual((f["kind"], f["reason"], f["detail"], f["runs"]), ("repeated_action", "edited", None, 2))
        self.assertEqual(f["ships"], ["a", "b"])
        self.assertEqual([e["order_url"] for e in f["evidence"]], [PR % 1, PR % 2])
        self.assertEqual([e["autopilot_calls"] for e in f["evidence"]], [None, None])
        self.assertEqual([e["event"] for e in r.analysis["edited_reviews"]], ["review_submitted", "card_edited"])

    def test_rejected_reviews_and_cards_together_repeat_across_runs(self):
        log = Log()
        log.launch("a", 1)
        log.discard("a")
        log.end("a")
        log.launch("b", 2)
        log.card("b", "rejected")
        log.end("b")
        r = self.analyse(log)
        self.assertEqual(
            [(f["kind"], f["reason"], f["runs"]) for f in r.findings], [("repeated_action", "rejected", 2)]
        )

    def test_discards_flagged_as_not_the_engineers_call_are_not_rejections(self):
        log = Log()
        for i, flag in enumerate(("unreachable", "external", "invalid_target")):
            ship = f"s{i}"
            log.launch(ship, i + 1)
            log.discard(ship, **{flag: True})
            log.end(ship)
        r = self.analyse(log)
        self.assertEqual(r.summary["engineer_actions"]["rejected"], 0)
        self.assertEqual(r.summary["engineer_actions"]["discarded_other"], 3)
        self.assertEqual(r.findings, [])
        self.assertEqual(r.analysis["edited_reviews"], [])

    def test_a_bucket_seen_in_one_run_is_not_a_repeat(self):
        log = Log()
        log.launch("a", 1)
        log.submit("a", True)
        log.card("a", "edited")
        log.discard("a")
        log.card("a", "rejected")
        log.end("a")
        r = self.analyse(log)
        self.assertEqual(r.summary["engineer_actions"]["edited"], 2)
        self.assertEqual(r.summary["engineer_actions"]["rejected"], 2)
        self.assertEqual(r.findings, [])
        self.assertEqual(len(r.analysis["edited_reviews"]), 4)

    def test_accepted_and_answered_never_make_findings(self):
        log = Log()
        for i, ship in enumerate(("a", "b", "c")):
            log.launch(ship, i + 1)
            log.submit(ship, False)
            log.add(ship, "answered", item="q", kind="question")
            log.end(ship)
        log.card("c", "approved")
        r = self.analyse(log)
        self.assertEqual(r.findings, [])
        self.assertEqual(r.summary["engineer_actions"]["accepted"], 4)
        self.assertEqual(r.summary["engineer_actions"]["answered"], 3)

    def test_actions_on_hand_launched_and_other_panel_ships_are_not_counted(self):
        log = Log()
        log.launch("hand", 1, autopilot=False)
        log.submit("hand", True)
        log.launch("other", 2, panel=OTHER_PANEL)
        log.discard("other")
        r = self.analyse(log)
        self.assertEqual(
            r.summary["engineer_actions"],
            {"accepted": 0, "edited": 0, "rejected": 0, "discarded_other": 0, "answered": 0},
        )

    def test_ids_are_numbered_across_kinds_by_first_evidence(self):
        log = Log()
        log.launch("a", 1)
        log.submit("a", True)
        log.stop("a", "question")
        log.end("a")
        log.launch("b", 2)
        log.stop("b", "question")
        log.card("b", "edited")
        log.end("b")
        findings = self.analyse(log).findings
        self.assertEqual([(f["id"], f["reason"]) for f in findings], [("F1", "edited"), ("F2", "question")])


class SummaryTest(RetroCase):
    def test_median_wait(self):
        for waits, expected in (([7], 7), ([3, 9, 5], 5), ([10, 20], 15), ([], None)):
            with self.subTest(waits=waits):
                log = Log()
                log.launch("a", 1)
                for w in waits:
                    log.wait("a", w)
                self.assertEqual(self.analyse(log).summary["median_wait_s"], expected)

    def test_calls_come_from_report_assumptions(self):
        log = Log()
        log.launch("a", 1)
        log.end("a", {"version": 1, "result": "done", "why": "x", "assumptions": ["asked: a", "default: b", "note: c"]})
        log.launch("b", 2)
        log.end("b", {"version": 1, "result": "done", "why": "x"})
        self.assertEqual(self.analyse(log).summary["calls"], {"total": 3, "high_stakes": 1, "low_stakes": 1})


class MalformedLinesTest(RetroCase):
    def test_bad_lines_are_skipped_and_counted(self):
        log = Log()
        log.run("a", 1, ["stop"])
        clean = self.analyse(log)
        raw = [b"{not json\n", b'\xff\xfe{"v":1}\n', b'{"v":1,"ts":"2026-09-10T10:00:00Z","ship":"a","ev\n']
        dirty = self.analyse(log, raw=raw)
        self.assertEqual(dirty.summary["skipped_lines"], 3)
        self.assertEqual(clean.summary["skipped_lines"], 0)
        self.assertEqual({**dirty.summary, "skipped_lines": 0}, clean.summary)

    def test_last_line_without_a_newline_is_read(self):
        log = Log()
        log.launch("a", 1)
        sb = self.sandbox()
        sb.write_lines(sb.outcomes, log)
        sb.outcomes.write_bytes(sb.outcomes.read_bytes().rstrip(b"\n"))
        proc = sb.invoke(sb.argv())
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertEqual(Result(proc, sb.out).summary["runs"], 1)


# --------------------------------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------------------------------


class ArgumentsTest(RetroCase):
    def test_bad_arguments_exit_2_with_a_message_and_write_nothing(self):
        cases = {
            "no arguments": lambda sb: [],
            "no panel": lambda sb: ["--outcomes", str(sb.outcomes), "--out", str(sb.out)],
            "no outcomes": lambda sb: ["--panel", PANEL, "--out", str(sb.out)],
            "no out": lambda sb: ["--panel", PANEL, "--outcomes", str(sb.outcomes)],
            "panel without a slash": lambda sb: sb.argv(panel="prs-needs-review"),
            "since not RFC 3339": lambda sb: sb.argv(since="yesterday"),
            "until a bare date": lambda sb: sb.argv(until="2026-09-30"),
            "unknown flag": lambda sb: [*sb.argv(), "--bogus"],
            "missing outcomes file": lambda sb: [*sb.argv()[:3], str(sb.root / "nope.jsonl"), *sb.argv()[4:]],
            "outcomes is a directory": lambda sb: [*sb.argv()[:3], str(sb.root), *sb.argv()[4:]],
        }
        for label, build in cases.items():
            with self.subTest(label):
                sb = self.sandbox()
                sb.write_lines(sb.outcomes, Log())
                proc = sb.invoke(build(sb))
                self.assertEqual(proc.returncode, 2, proc.stderr.decode("utf-8", "replace"))
                self.assertTrue(proc.stderr.strip(), "no message on stderr")
                self.assertEqual(list(sb.out.iterdir()), [])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read any file")
    def test_unreadable_outcomes_file_exits_2(self):
        sb = self.sandbox()
        sb.write_lines(sb.outcomes, Log())
        sb.outcomes.chmod(0)
        proc = sb.invoke(sb.argv())
        self.assertEqual(proc.returncode, 2, proc.stderr.decode("utf-8", "replace"))
        self.assertTrue(proc.stderr.strip())
        self.assertEqual(list(sb.out.iterdir()), [])


# --------------------------------------------------------------------------------------------------
# AC3: what the script writes
# --------------------------------------------------------------------------------------------------


class WriteScopeTest(RetroCase):
    def test_only_analysis_json_and_retro_md_are_created_and_nothing_else_changes(self):
        sb = self.sandbox()
        shutil.copy(FIXTURES / "five-reviews" / "outcomes.jsonl", sb.outcomes)
        shutil.copytree(FIXTURES / "five-reviews" / "teams", sb.teams, dirs_exist_ok=True)
        before = sb.snapshot(skip=(sb.out,))
        proc = sb.invoke(sb.argv())
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertEqual(sorted(p.name for p in sb.out.iterdir()), ["analysis.json", "retro.md"])
        after = sb.snapshot(skip=(sb.out,))
        self.assertEqual(sorted(after), sorted(before))
        changed = [rel for rel in before if before[rel] != after[rel]]
        self.assertEqual(changed, [])
        self.assertFalse(sb.marker.exists(), "the script ran `admiral`")

    def test_files_already_in_the_out_directory_are_left_alone(self):
        sb = self.sandbox()
        (sb.out / "keep.txt").write_text("mine\n", encoding="utf-8")
        r = self.analyse(Log(), sb=sb)
        self.assertEqual(sorted(p.name for p in r.out.iterdir()), ["analysis.json", "keep.txt", "retro.md"])
        self.assertEqual((sb.out / "keep.txt").read_text(encoding="utf-8"), "mine\n")

    def test_output_is_deterministic_for_a_fixed_until(self):
        first, second = (self.analyse(Log()) for _ in range(2))
        self.assertEqual(first.md, second.md)
        self.assertEqual(first.analysis, second.analysis)

    def test_decoys_are_never_read(self):
        # The sandbox's $ADMIRAL_HOME holds two autopilot runs on this panel; neither may show up.
        r = self.analyse(Log())
        self.assertEqual(r.summary["runs"], 0)


# --------------------------------------------------------------------------------------------------
# Untrusted text in retro.md
# --------------------------------------------------------------------------------------------------


class UntrustedTextTest(RetroCase):
    RULE = "Bash(echo `x` | cat)\n## Injected rule heading\n| a | b |"

    def hostile(self):
        log = Log()
        for ship, n in (("evil`ship|x\n# Injected ship heading", 1), ("second", 2)):
            log.launch(ship, n)
            log.add(ship, "guard_denied", rule=self.RULE, tool="Bash")
            log.stop(ship, "question\n## Injected reason heading")
            log.add(ship, "review_submitted", item="r", kind="review", review_event="COMMENT", edited=True)
            log.end(ship)
        log.records[0]["order_url"] = "https://github.com/example/fixture/pull/1|x\n## Injected url heading"
        sb = self.sandbox()
        return self.analyse(log, sb=sb), sb

    def test_injected_lines_do_not_reach_retro_md(self):
        r, _ = self.hostile()
        lines = r.md.splitlines()
        for text in ("## Injected", "# Injected", "| a | b |"):
            self.assertFalse(any(line.startswith(text) for line in lines), text)

    def test_the_data_itself_is_kept_in_analysis_json(self):
        r, _ = self.hostile()
        self.assertIn(self.RULE, [f["detail"] for f in r.findings])

    def test_retro_md_passes_markdownlint(self):
        r, _ = self.hostile()
        self.assert_markdown_clean(r.out / "retro.md")


if __name__ == "__main__":
    unittest.main()
