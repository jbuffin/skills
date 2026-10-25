"""Tests for scripts/coordinator-tokens.py: tool calls by category and the result split.

The only seam is the script's command line. Every test writes coordinator transcripts into a temp
dir, runs the script as a subprocess on those paths (never the real ~/.claude*/projects) and reads
its text or `--json` output. Expected values are literals worked out by hand from the fixtures.

Run from the repo root: python3 -m unittest discover -s evals/coordinator-tokens -v
"""

import ast
import json
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPT = REPO / "scripts" / "coordinator-tokens.py"

BASE = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
PAD = "x" * 210_000  # transcripts under 200 KB are skipped
STATE_SCRIPT = "/abs/commodore/scripts/state-set.sh"

STATE = "state-set.sh"
STATE_MD = "Edit/Write state.md"
PROMPTS = "Write prompts/ (job files)"
RUN_DIR = "Edit/Write run directory"
REPO_FILES = "Edit/Write repo, worktree or elsewhere"
SCRIPTS = "commodore scripts"

SIDE_KEYS = {"active_hours", "active_hours_per_unit", "tool_calls", "tool_calls_per_unit"}

# decision 3's literal table: (command, category)
BASH_TABLE = [
    ("git status", "bash: git"),
    ("cd /r && git log", "bash: git"),
    ("cd /a && cd b; gh pr view 1", "bash: gh"),
    ("grep x f | head", "bash: grep"),
    ("gh pr view 1 ; git log", "bash: gh"),
    ("false || echo hi", "bash: false"),
    ("FOO=1 BAR=2 python3 x.py", "bash: python3"),
    ("(cd x && git log)", "bash: git"),
    ("env FOO=1 make", "bash: make"),
    ('cd "a b" && ls', "bash: ls"),
    ("# note\nls -la", "bash: ls"),
    ("/abs/commodore/scripts/state-set.sh /r mode result done", STATE),
    ("/abs/agent-teammates/scripts/verify-report.sh /r n", SCRIPTS),
    ("/abs/my-evidence.sh", "bash: my-evidence.sh"),
    ("bash /abs/state-set.sh /r mode x y", "bash: bash"),
    ("", "bash: "),
]


def bash(command):
    return ("Bash", {"command": command})


def tool(name, **inp):
    return (name, inp)


class Session:
    """Builds a coordinator transcript: one assistant message per call, `step` seconds after BASE."""

    def __init__(self, directory, name):
        self.path = Path(directory) / name
        self.calls = 0
        self.ids = 0
        self.lines = [
            {"type": "user", "message": {"role": "user", "content": "<command-name>/commodore</command-name>"}},
            {"type": "user", "message": {"role": "user", "content": PAD}},
        ]

    def blocks(self, tools):
        out = []
        for name, inp in tools:
            self.ids += 1
            out.append({"type": "tool_use", "id": f"tu{self.ids}", "name": name, "input": inp})
        return out

    def entry(self, mid, seconds, content, **extra):
        stamp = (BASE + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        usage = {"input_tokens": 10, "cache_read_input_tokens": 1000 * self.calls, "cache_creation_input_tokens": 0}
        message = {"id": mid, "model": "claude-test", "role": "assistant", "usage": usage, "content": content}
        return {"type": "assistant", "timestamp": stamp, "message": message, **extra}

    def call(self, seconds, *tools, later=None):
        """Add one API call. `later` = (seconds, tools): a second entry of the same message at another time."""
        self.calls += 1
        mid = f"msg{self.calls}"
        content = self.blocks(tools)
        if later is None:
            self.lines.append(self.entry(mid, seconds, content))
            return
        text = [{"type": "text", "text": "thinking aloud"}]
        self.lines.append(self.entry(mid, seconds, text))
        self.lines.append(self.entry(mid, later[0], self.blocks(later[1])))

    def repeat_last(self):
        """Write the last entry again, as a streamed message does (same message id, same tool_use ids)."""
        self.lines.append(self.lines[-1])

    def sidechain(self, seconds, *tools):
        self.lines.append(self.entry("side", seconds, self.blocks(tools), isSidechain=True))

    def save(self):
        text = "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in self.lines)
        self.path.write_text(text)
        return str(self.path)


def make_run(directory, units=5):
    run = Path(directory) / "teams" / "run1"
    run.mkdir(parents=True)
    rows = "".join(f"| u{i} | planned |\n" for i in range(1, units + 1))
    (run / "state.md").write_text(f"# State\n\n## Units\n\n| unit | status |\n| --- | --- |\n{rows}")
    return run


def run_script(*args):
    cmd = [sys.executable, str(SCRIPT), "--min-calls", "0", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def run_json(*args):
    proc = run_script("--json", *args)
    if proc.returncode != 0:
        raise AssertionError(f"exit {proc.returncode}: {proc.stderr}")
    return json.loads(proc.stdout)


def run_text(*args):
    proc = run_script(*args)
    if proc.returncode != 0:
        raise AssertionError(f"exit {proc.returncode}: {proc.stderr}")
    return proc.stdout


def counts(out):
    return {c["category"]: c["calls"] for c in out["tool_calls"]["categories"]}


def one_call(directory, command_tool):
    s = Session(directory, "one.jsonl")
    s.call(0, command_tool)
    return s.save()


class TempDirCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name


class MixedCase(TempDirCase):
    """A session using every category, with 5 units in its run's state.md."""

    def setUp(self):
        super().setUp()
        run = make_run(self.tmp)
        r = str(run)
        s = Session(self.tmp, "mixed.jsonl")
        s.call(0, tool("Read", file_path=f"{r}/state.md"))
        s.call(60, tool("Read", file_path="/repo/a.py"), tool("ToolSearch", query="select:Foo"))
        s.call(120, bash(f"{STATE_SCRIPT} {r} u1 status done"))
        s.call(180, bash(f"cd /x && {STATE_SCRIPT} {r} u2 status done"))
        s.call(
            240,
            tool("Edit", file_path=f"{r}/state.md", old_string="planned", new_string="running"),
            tool("Write", file_path=f"{r}/state.md", content="# State\n"),
        )
        s.call(300, tool("Write", file_path=f"{r}/prompts/u1.md", content="brief"))
        s.call(
            360,
            tool("Edit", file_path=f"{r}/reports/u1.md", old_string="a", new_string="b"),
            tool("Write", file_path=f"{r}/brief.md", content="b"),
        )
        s.call(
            420,
            tool("Edit", file_path="/repo/src/a.py", old_string="a", new_string="b"),
            tool("Write", file_path="/tmp/plan.md", content="p"),
        )
        s.call(480, tool("Edit", file_path="/Users/x/.claude/memory/m.md", old_string="a", new_string="b"))
        s.call(540, bash("/abs/agent-teammates/scripts/verify-report.sh /r n"), bash("git status"))
        s.call(600, bash("cd /r && git log"), bash("gh pr view 1"))
        s.repeat_last()  # a streamed duplicate: counted once
        s.sidechain(610, bash("ls"))  # sub-agent traffic: skipped
        s.call(660, tool("Agent", prompt="x"), tool("Monitor", command="x"), tool("mcp__foo__bar"))
        self.path = s.save()

    def test_each_category_counts_its_calls_and_they_sum_to_the_total(self):
        out = run_json("--units", "5", self.path)
        self.assertEqual(
            counts(out),
            {
                "Read": 2,
                "ToolSearch": 1,
                STATE: 2,
                STATE_MD: 2,
                PROMPTS: 1,
                RUN_DIR: 2,
                REPO_FILES: 3,
                SCRIPTS: 1,
                "bash: git": 2,
                "bash: gh": 1,
                "other": 3,
            },
        )
        self.assertEqual(out["tool_calls"]["total"], 20)
        self.assertEqual(sum(counts(out).values()), out["tool_calls"]["total"])

    def test_edit_of_state_md_and_edit_of_a_repo_file_are_different_categories(self):
        by_category = counts(run_json("--units", "5", self.path))
        self.assertEqual(by_category[STATE_MD], 2)
        self.assertEqual(by_category[REPO_FILES], 3)

    def test_json_shape_is_total_per_unit_and_ordered_categories(self):
        tc = run_json("--units", "5", self.path)["tool_calls"]
        self.assertEqual(set(tc), {"total", "per_unit", "categories"})
        self.assertEqual(tc["per_unit"], 4.0)
        for row in tc["categories"]:
            self.assertEqual(set(row), {"category", "calls", "per_unit"})
            self.assertGreater(row["calls"], 0)
        sizes = [row["calls"] for row in tc["categories"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        by_category = {row["category"]: row["per_unit"] for row in tc["categories"]}
        self.assertEqual(by_category[REPO_FILES], 0.6)
        self.assertEqual(by_category["Read"], 0.4)
        self.assertEqual(by_category[PROMPTS], 0.2)

    def test_units_come_from_state_md_when_not_given(self):
        out = run_json(self.path)
        self.assertEqual(out["units"], 5)
        self.assertEqual(out["tool_calls"]["per_unit"], 4.0)

    def test_units_flag_wins_over_state_md(self):
        tc = run_json("--units", "10", self.path)["tool_calls"]
        self.assertEqual(tc["per_unit"], 2.0)
        by_category = {row["category"]: row["per_unit"] for row in tc["categories"]}
        self.assertEqual(by_category[REPO_FILES], 0.3)
        self.assertEqual(by_category[PROMPTS], 0.1)

    def test_raw_does_not_change_the_tool_call_section(self):
        plain = run_json("--units", "5", self.path)
        raw = run_json("--units", "5", "--raw", self.path)
        self.assertEqual(raw["tool_calls"], plain["tool_calls"])
        self.assertEqual(raw["result_split"], plain["result_split"])

    def test_text_section_lists_each_category_with_counts_and_a_last_total_row(self):
        all_lines = run_text("--units", "5", self.path).splitlines()
        header = next(i for i, line in enumerate(all_lines) if "tool calls by category" in line)
        total_row = next(i for i, line in enumerate(all_lines) if i > header and re.search(r"(?i)\btotal\b", line))
        lines = all_lines[header + 1 : total_row]  # the section's rows only, so no earlier table can match

        def row_index(label):
            return next(i for i, line in enumerate(lines) if line.split(None, 2)[-1] == label)

        expected = [  # label, calls, per unit
            ("Edit/Write repo, worktree or elsewhere", "3", "0.6"),
            ("Edit/Write state.md", "2", "0.4"),
            ("bash: git", "2", "0.4"),
            ("other", "3", "0.6"),
        ]
        for label, calls, per_unit in expected:
            row = lines[row_index(label)]
            self.assertRegex(row, rf"\b{calls}\b")
            self.assertRegex(row, rf"\b{re.escape(per_unit)}\b")
        labels = [STATE, STATE_MD, PROMPTS, RUN_DIR, REPO_FILES, SCRIPTS, "bash: git", "bash: gh", "other"]
        for label in labels:
            row_index(label)  # raises StopIteration if a category is missing from the section
        self.assertRegex(all_lines[total_row], r"\b20\b")
        self.assertRegex(all_lines[total_row], r"\b4\.0\b")


class BashFirstCommandCase(TempDirCase):
    def test_every_row_of_the_literal_table(self):
        for command, category in BASH_TABLE:
            with self.subTest(command=command):
                path = one_call(self.tmp, bash(command))
                out = run_json(path)
                self.assertEqual(
                    out["tool_calls"]["categories"], [{"category": category, "calls": 1, "per_unit": None}]
                )
                self.assertEqual(out["tool_calls"]["total"], 1)

    def test_a_commodore_script_other_than_state_set_by_basename_counts_as_a_script(self):
        path = one_call(self.tmp, bash("cd /r && /abs/watch-teammates.sh /r"))
        self.assertEqual(counts(run_json(path)), {SCRIPTS: 1})


class UnitsUnknownCase(TempDirCase):
    def test_per_unit_is_null_in_json_and_absent_in_text(self):
        path = one_call(self.tmp, bash("git status"))
        out = run_json(path)
        self.assertIsNone(out["tool_calls"]["per_unit"])
        self.assertIsNone(out["tool_calls"]["categories"][0]["per_unit"])
        row = next(line for line in run_text(path).splitlines() if "bash: git" in line)
        self.assertNotRegex(row, r"\d\.\d")


class ToolSeenOnceCase(TempDirCase):
    def test_a_tool_use_repeated_across_entries_counts_once_and_a_sidechain_not_at_all(self):
        s = Session(self.tmp, "dup.jsonl")
        s.call(0, bash("git status"))
        s.repeat_last()
        s.repeat_last()
        s.sidechain(10, bash("git log"), tool("Read", file_path="/r"))
        s.call(20, tool("Read", file_path="/r"))
        out = run_json(s.save())
        self.assertEqual(counts(out), {"bash: git": 1, "Read": 1})
        self.assertEqual(out["tool_calls"]["total"], 2)


class ResultSplitCase(TempDirCase):
    def split_session(self):
        """Result written at the 4th call; gaps >10 min before it (1700 s) and after it (2100 s)."""
        s = Session(self.tmp, "split.jsonl")
        s.call(0, tool("Read", file_path="/repo/a.py"))
        s.call(300, bash("git status"))
        s.call(2000, bash("git log"))
        s.call(2600, bash(f"cd /r && {STATE_SCRIPT} /r mode result done"))
        # one message over two entries: timed by the first (2900), its tool_use arrives in the second (3500)
        s.call(2900, later=(3500, [bash("gh pr view 1")]))
        s.call(5000, tool("Edit", file_path="/repo/a.py", old_string="a", new_string="b"))
        s.call(5120, tool("Read", file_path="/repo/b.py"))
        return s.save()

    def test_active_time_and_tool_calls_split_at_the_result_write(self):
        out = run_json("--units", "5", "--sessions", self.split_session())
        split = out["result_split"]
        self.assertEqual(set(split), {"to_result", "after_result", "sessions_without_result"})
        self.assertEqual(set(split["to_result"]), SIDE_KEYS)
        self.assertEqual(set(split["after_result"]), SIDE_KEYS)
        # to result: gaps 300 + 0 (1700 s) + 600 (exactly the cap) = 900 s = 0.25 h, 4 calls
        self.assertEqual(
            split["to_result"],
            {"active_hours": 0.25, "active_hours_per_unit": 0.05, "tool_calls": 4, "tool_calls_per_unit": 0.8},
        )
        # after: 300 (the gap that crosses the split goes to its later call) + 0 (2100 s) + 120 = 420 s
        self.assertEqual(
            split["after_result"],
            {"active_hours": 0.12, "active_hours_per_unit": 0.02, "tool_calls": 3, "tool_calls_per_unit": 0.6},
        )
        self.assertEqual(split["sessions_without_result"], [])
        self.assertEqual(out["per_session"][0]["has_result"], True)
        self.assertEqual(out["tool_calls"]["total"], 7)

    def test_text_shows_both_sides_and_no_flag(self):
        text = run_text("--units", "5", self.split_session())
        to_line = next(line for line in text.splitlines() if "to result" in line)
        after_line = next(line for line in text.splitlines() if "after result" in line)
        for line, values in ((to_line, ("0.25", "0.05", "4", "0.8")), (after_line, ("0.12", "0.02", "3", "0.6"))):
            for value in values:
                self.assertRegex(line, rf"(?<![\d.]){re.escape(value)}(?![\d.])")
        self.assertNotRegex(text, r"(?i)no result")

    def test_a_session_with_no_result_is_all_to_result_and_flagged(self):
        s = Session(self.tmp, "noresult.jsonl")
        s.call(0, bash("git status"))
        s.call(120, bash("git log"))
        path = s.save()
        out = run_json("--sessions", path)
        split = out["result_split"]
        self.assertEqual(
            split["to_result"],
            {"active_hours": 0.03, "active_hours_per_unit": None, "tool_calls": 2, "tool_calls_per_unit": None},
        )
        self.assertEqual(
            split["after_result"],
            {"active_hours": 0.0, "active_hours_per_unit": None, "tool_calls": 0, "tool_calls_per_unit": None},
        )
        self.assertEqual(len(split["sessions_without_result"]), 1)
        self.assertTrue(split["sessions_without_result"][0].endswith("noresult.jsonl"))
        self.assertEqual(out["per_session"][0]["has_result"], False)
        text = run_text("--sessions", path)
        self.assertRegex(text, r"(?i)\b1\b[^\n]*(without|no)[^\n]*result")
        session_line = next(line for line in text.splitlines() if "noresult.jsonl" in line)
        self.assertIn("no result", session_line)

    def test_sessions_add_up_and_only_the_one_without_a_result_is_flagged(self):
        s = Session(self.tmp, "noresult.jsonl")
        s.call(0, bash("git status"))
        s.call(120, bash("git log"))
        out = run_json("--units", "5", "--sessions", self.split_session(), s.save())
        split = out["result_split"]
        # to result: 900 s + 120 s = 1020 s = 0.2833 h; 4 + 2 calls
        self.assertEqual(split["to_result"]["active_hours"], 0.28)
        self.assertEqual(split["to_result"]["tool_calls"], 6)
        self.assertEqual(split["to_result"]["tool_calls_per_unit"], 1.2)
        self.assertEqual(split["after_result"]["tool_calls"], 3)
        self.assertEqual(len(split["sessions_without_result"]), 1)
        flags = {p["path"].rsplit("/", 1)[-1]: p["has_result"] for p in out["per_session"]}
        self.assertEqual(flags, {"split.jsonl": True, "noresult.jsonl": False})
        self.assertEqual(out["tool_calls"]["total"], 9)

    def test_split_falls_at_the_last_of_two_result_writes(self):
        s = Session(self.tmp, "twice.jsonl")
        s.call(0, bash("git status"))
        s.call(60, bash(f"{STATE_SCRIPT} /r mode result partial"))
        s.call(120, bash("git log"))
        s.call(180, bash(f"{STATE_SCRIPT} /r mode result done"))
        s.call(240, bash("gh pr view 1"))
        split = run_json(s.save())["result_split"]
        self.assertEqual(split["to_result"]["tool_calls"], 4)
        self.assertEqual(split["to_result"]["active_hours"], 0.05)  # 180 s
        self.assertEqual(split["after_result"]["tool_calls"], 1)
        self.assertEqual(split["after_result"]["active_hours"], 0.02)  # 60 s
        self.assertEqual(split["sessions_without_result"], [])

    def test_a_result_write_as_the_last_call_leaves_nothing_after(self):
        s = Session(self.tmp, "last.jsonl")
        s.call(0, bash("git status"))
        s.call(60, bash(f"{STATE_SCRIPT} /r mode result done"))
        split = run_json(s.save())["result_split"]
        self.assertEqual(split["to_result"]["tool_calls"], 2)
        self.assertEqual(split["after_result"]["tool_calls"], 0)
        self.assertEqual(split["after_result"]["active_hours"], 0.0)


class ResultWriteKindsCase(TempDirCase):
    """Which calls count as writing `result:`. The candidate is call 2 of 4, so a hit splits 2 / 2."""

    def split_of(self, candidate):
        s = Session(self.tmp, "kind.jsonl")
        s.call(0, tool("Read", file_path="/repo/a.py"))
        s.call(60, candidate)
        s.call(120, bash("git status"))
        s.call(180, bash("git log"))
        out = run_json(s.save())["result_split"]
        return out["to_result"]["tool_calls"], out["after_result"]["tool_calls"], out["sessions_without_result"]

    def edit(self, old, new, path="/teams/run1/state.md"):
        return tool("Edit", file_path=path, old_string=old, new_string=new)

    def test_an_edit_that_adds_a_result_line_to_state_md(self):
        self.assertEqual(self.split_of(self.edit("status: running\n", "status: running\nresult: done\n")), (2, 2, []))

    def test_an_indented_result_line_counts(self):
        self.assertEqual(self.split_of(self.edit("a: 1\n", "a: 1\n  result: done\n")), (2, 2, []))

    def test_an_edit_that_replaces_result_partial_with_done(self):
        self.assertEqual(self.split_of(self.edit("result: partial\n", "result: done\n")), (2, 2, []))

    def test_a_write_of_state_md_with_a_result_line(self):
        write = tool("Write", file_path="/teams/run1/state.md", content="# State\nresult: done\n")
        self.assertEqual(self.split_of(write), (2, 2, []))

    def test_an_edit_that_keeps_an_existing_result_line_is_not_a_write(self):
        edit = self.edit("result: done\nstatus: a\n", "result: done\nstatus: b\n")
        to_result, after, without = self.split_of(edit)
        self.assertEqual((to_result, after), (4, 0))
        self.assertEqual(len(without), 1)

    def test_an_edit_that_mentions_result_mid_line_is_not_a_write(self):
        to_result, after, without = self.split_of(self.edit("a", "see result: below"))
        self.assertEqual((to_result, after), (4, 0))
        self.assertEqual(len(without), 1)

    def test_an_edit_of_another_file_is_not_a_write(self):
        edit = self.edit("a", "result: done\n", path="/repo/notes.md")
        self.assertEqual(self.split_of(edit)[:2], (4, 0))

    def test_state_set_with_another_field_is_not_a_write(self):
        for command in (f"{STATE_SCRIPT} /r unit result done", f"{STATE_SCRIPT} /r mode status done"):
            with self.subTest(command=command):
                self.assertEqual(self.split_of(bash(command))[:2], (4, 0))

    def test_a_state_set_after_cd_is_a_write(self):
        self.assertEqual(self.split_of(bash(f"cd /r && {STATE_SCRIPT} /r mode result done")), (2, 2, []))

    def test_state_set_batch_form_with_a_result_pair_is_a_write(self):
        self.assertEqual(self.split_of(bash(f"{STATE_SCRIPT} /r mode --set result=done phase=x")), (2, 2, []))
        self.assertEqual(self.split_of(bash(f"cd /r && {STATE_SCRIPT} /r mode --set result=partial")), (2, 2, []))

    def test_state_set_batch_form_without_a_result_pair_is_not_a_write(self):
        self.assertEqual(self.split_of(bash(f"{STATE_SCRIPT} /r mode --set phase=x"))[:2], (4, 0))

    def test_a_result_write_counts_even_when_the_call_failed(self):
        s = Session(self.tmp, "failed.jsonl")
        s.call(0, bash(f"{STATE_SCRIPT} /r mode result done"))
        s.call(60, bash("git status"))
        s.lines.append(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "tu1", "is_error": True, "content": "exit 1"}],
                },
            }
        )
        split = run_json(s.save())["result_split"]
        self.assertEqual(split["to_result"]["tool_calls"], 1)
        self.assertEqual(split["after_result"]["tool_calls"], 1)


# What c04c275 prints for ExistingOutputCase's fixture, apart from the new section and fields (D2).
OLD_JSON = {
    "sessions": 1,
    "calls": 3,
    "cache_read": 6000,
    "mean_context_per_call": 2010,
    "never_compacted": 1,
    "mean_initial_context": 1010,
    "units": 5,
    "calls_per_unit": 0.6,
}
OLD_BREAKDOWN = [
    {"source": "base prompt (system, tools, MCP, skill listing)", "carry": 3030, "share": 0.5025, "added": 1010},
    {"source": "state.md", "carry": 2000, "share": 0.3317, "added": 1000},
    {"source": "git", "carry": 1000, "share": 0.1658, "added": 1000},
]
OLD_SESSION_KEYS = ["path", "model", "calls", "peak", "compactions", "cache_read", "run", "units"]
OLD_TEXT_HEAD = [
    "1 coordinator sessions, 3 API calls, 0M cache reads",
    "5 units, 0.6 calls per unit",
    "mean context per call 2k, mean initial context 1k, 1 never compacted",
    "",
    "    carry  share     added  source",
    "     0.0M  50.2%      1.0k  base prompt (system, tools, MCP, skill listing)",
    "     0.0M  33.2%      1.0k  state.md",
    "     0.0M  16.6%      1.0k  git",
]
OLD_TEXT_TAIL = [
    "handoff above 150k: 0% fewer input tokens, 0 handoffs",
    "handoff above 200k: 0% fewer input tokens, 0 handoffs",
    "handoff above 300k: 0% fewer input tokens, 0 handoffs",
]


class ExistingOutputCase(TempDirCase):
    """The lines and keys that exist at c04c275 stay as they were."""

    def setUp(self):
        super().setUp()
        run = make_run(self.tmp)
        s = Session(self.tmp, "old.jsonl")
        s.call(0, tool("Read", file_path=f"{run}/state.md"))
        s.call(60, bash("git status"))
        s.call(120, tool("Edit", file_path="/repo/a.py", old_string="a", new_string="b"))
        self.path = s.save()

    def test_json_keys_and_values_are_unchanged(self):
        out = run_json("--sessions", "--simulate-handoff", self.path)
        self.assertEqual(
            set(out) - {"tool_calls", "result_split"},
            set(OLD_JSON) | {"breakdown", "handoff", "per_session"},
        )
        for key, value in OLD_JSON.items():
            self.assertEqual(out[key], value, key)
        self.assertEqual(out["breakdown"], OLD_BREAKDOWN)
        self.assertEqual(list(out["per_session"][0])[: len(OLD_SESSION_KEYS)], OLD_SESSION_KEYS)

    def test_per_session_gains_only_has_result(self):
        out = run_json("--sessions", self.path)
        self.assertEqual(set(out["per_session"][0]) - set(OLD_SESSION_KEYS), {"has_result"})

    def test_text_lines_are_unchanged(self):
        lines = run_text("--sessions", "--simulate-handoff", self.path).splitlines()
        self.assertEqual(lines[: len(OLD_TEXT_HEAD)], OLD_TEXT_HEAD)
        tail = [line for line in lines if line.startswith("handoff above")]
        self.assertEqual(tail, OLD_TEXT_TAIL)
        self.assertRegex(lines[-1], r"^    3 calls  peak    3k  0 compactions   5 units  .*old\.jsonl$")

    def test_the_new_section_sits_between_the_table_and_handoff(self):
        lines = run_text("--sessions", "--simulate-handoff", self.path).splitlines()
        first_tail = next(i for i, line in enumerate(lines) if line.startswith("handoff above"))
        between = [line for line in lines[len(OLD_TEXT_HEAD) : first_tail] if line.strip()]
        self.assertTrue(any("bash: git" in line for line in between), "no category section before handoff")
        self.assertTrue(any("to result" in line for line in between), "no result split block before handoff")


WRAPPER_TABLE = [
    ("time -p make", "bash: make"),
    ("sudo -u bob make", "bash: make"),
    ("env -i ls", "bash: ls"),
]
UNSAFE_NAMES = [
    '"ghp_SECRET token here" x',
    '/a/b/"c d e"',
    "a" * 41,
    "ls\x07",
    "\x1b[2Jfake",
]


def usage_less(session, seconds, *tools):
    """Append an assistant message that carries tool_use blocks but no `usage`, after the last real API call."""
    entry = session.entry("nousage", seconds, session.blocks(tools))
    del entry["message"]["usage"]
    session.lines.append(entry)


class BashNameCase(TempDirCase):
    def test_wrapper_flags_are_skipped(self):
        for command, category in WRAPPER_TABLE:
            with self.subTest(command=command):
                out = run_json(one_call(self.tmp, bash(command)))
                self.assertEqual(counts(out), {category: 1})

    def test_a_name_that_is_not_plain_shows_as_a_question_mark_in_json_and_text(self):
        for command in UNSAFE_NAMES:
            with self.subTest(command=command):
                path = one_call(self.tmp, bash(command))
                self.assertEqual(counts(run_json(path)), {"bash: ?": 1})
                text = run_text(path)
                self.assertTrue(any(line.endswith("bash: ?") for line in text.splitlines()))
                for leaked in ("ghp_SECRET", "c d e", "\x07", "\x1b"):
                    self.assertNotIn(leaked, text)

    def test_a_forty_character_name_is_still_shown(self):
        self.assertEqual(counts(run_json(one_call(self.tmp, bash("a" * 40)))), {"bash: " + "a" * 40: 1})


class UsageLessMessageCase(TempDirCase):
    def test_a_trailing_message_without_usage_counts_and_does_not_crash(self):
        s = Session(self.tmp, "trail.jsonl")
        s.call(0, bash("git status"))
        s.call(60, bash("git log"))
        usage_less(s, 120, bash("gh pr view 1"))
        out = run_json("--sessions", s.save())
        self.assertEqual(counts(out), {"bash: git": 2, "bash: gh": 1})
        split = out["result_split"]
        self.assertEqual((split["to_result"]["tool_calls"], split["after_result"]["tool_calls"]), (3, 0))
        self.assertEqual(len(split["sessions_without_result"]), 1)
        self.assertEqual(out["per_session"][0]["has_result"], False)

    def test_a_result_write_in_a_trailing_message_splits_at_the_last_real_call(self):
        s = Session(self.tmp, "trailres.jsonl")
        s.call(0, bash("git status"))
        s.call(60, bash("git log"))
        usage_less(s, 120, bash(f"{STATE_SCRIPT} /r mode result done"))
        split = run_json(s.save())["result_split"]
        self.assertEqual((split["to_result"]["tool_calls"], split["after_result"]["tool_calls"]), (3, 0))
        self.assertEqual(split["to_result"]["active_hours"], 0.02)  # 60 s
        self.assertEqual(split["sessions_without_result"], [])


class TimeAndWordingCase(TempDirCase):
    def test_fractional_seconds_count_toward_the_idle_cap(self):
        s = Session(self.tmp, "frac.jsonl")
        s.call(0, bash("git status"))
        s.call(600, bash("git log"))
        s.lines[-2]["timestamp"] = "2026-10-01T10:00:00.100Z"
        s.lines[-1]["timestamp"] = "2026-10-01T10:10:00.900Z"  # 600.8 s later: idle
        split = run_json(s.save())["result_split"]
        self.assertEqual(split["to_result"]["active_hours"], 0.0)

    def test_the_summary_line_is_printed_even_when_every_session_has_a_result(self):
        s = Session(self.tmp, "ok.jsonl")
        s.call(0, bash(f"{STATE_SCRIPT} /r mode result done"))
        text = run_text(s.save())
        self.assertIn("0 sessions without a result: line, counted as to result", text)
        self.assertIn("after result:", text)
        self.assertIn("0 tool calls", text.split("after result:")[1])

    def test_a_count_of_one_is_singular(self):
        text = run_text(one_call(self.tmp, bash("git status")))
        self.assertIn("1 session without a result: line", text)
        self.assertRegex(text, r"1 tool call(?!s)")


class HelpTextCase(unittest.TestCase):
    def test_usage_text_mentions_tool_calls_by_category_and_the_result_split(self):
        text = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=True
        ).stdout.lower()
        self.assertIn("tool call", text)
        self.assertIn("categor", text)
        self.assertIn("result", text)

    def test_docstring_describes_the_section_and_avoids_job_for_a_mission(self):
        doc = ast_docstring()
        self.assertIn("result:", doc)
        self.assertIn("after result", doc)
        self.assertNotRegex(doc, r"\bjobs?\b")


def ast_docstring():
    return ast.get_docstring(ast.parse(SCRIPT.read_text())) or ""


if __name__ == "__main__":
    unittest.main()
