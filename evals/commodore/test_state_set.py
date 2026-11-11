"""Tests for state-set.sh: the single and batch forms, refusals and bad usage against a seeded run dir."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMMODORE = REPO / "skills" / "engineering" / "commodore"
SCRIPT = COMMODORE / "scripts" / "state-set.sh"
TEAM_INIT = COMMODORE / "scripts" / "team-init.sh"

OK = 0
REFUSED = 1
USAGE = 5

SHIP = "ship: (set in phase 1: how units ship and wait on CI)"

UNITS = "## Units"
TRACE = "## Acceptance trace"
FINDINGS = "## Non-blocking findings"
MODE = "## Mode, phase, current unit"

ENV = {**os.environ, "HARNESS": "claude"}


def row(*cells):
    """A table row as state-set.sh writes it."""
    return "|" + "".join(f" {c} |" for c in cells)


def section(text, heading):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start + 1 : end]


def table_rows(text, heading):
    return [line for line in section(text, heading) if line.startswith("|")][2:]


def mode_lines(text):
    return [line for line in section(text, MODE) if line.strip()]


def without(text, heading):
    """state.md with one section's body removed, to prove the other sections are untouched."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[: start + 1] + lines[end:])


def as_prose(text, heading):
    """state.md with a table section replaced by prose: the old format the script refuses."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join([*lines[: start + 1], "", "Hand-written notes, no table.", "", *lines[end:], ""])


class Result:
    def __init__(self, proc):
        self.code = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr


def call(script, run, *args):
    proc = subprocess.run([str(script), str(run), *args], env=ENV, capture_output=True, text=True, check=False)
    return Result(proc)


SEED_STEPS = [
    ["units", "--add", "u1", "branch=feat", "base=main"],
    ["units", "--add", "u2", "branch=feat2", "base=main"],
    ["trace", "--add", "a", "unit=u1", "test or scenario=t-a"],
    ["trace", "--add", "b", "unit=u1", "test or scenario=t-b"],
    ["trace", "--add", "c", "unit=u2", "test or scenario=t-c"],
    ["findings", "--add", "f1", "unit=u1", "severity=low", "finding=one"],
    ["findings", "--add", "f2", "unit=u1", "severity=low", "finding=two"],
    ["mode", "current unit", "u1"],
]
WORLD = {}


def setUpModule():
    tmp = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(tmp.cleanup)
    root = Path(tmp.name)
    (root / "repo").mkdir()
    subprocess.run(
        [str(TEAM_INIT), "seed", str(root / "repo")],
        env={**ENV, "AGENT_TEAMS_DIR": str(root / "teams")},
        capture_output=True,
        text=True,
        check=True,
    )
    seed = root / "teams" / "seed"
    for step in SEED_STEPS:
        done = call(SCRIPT, seed, *step)
        assert (done.code, done.out, done.err) == (OK, "", ""), step
    WORLD.update(root=root, seed=seed, copies=0)


class StateSetCase(unittest.TestCase):
    """Every test gets its own copy of one seeded run dir."""

    @property
    def root(self):
        return WORLD["root"]

    def fresh(self):
        WORLD["copies"] += 1
        run = self.root / "copies" / f"run{WORLD['copies']}"
        shutil.copytree(WORLD["seed"], run)
        return run

    def state(self, run):
        return (run / "state.md").read_bytes().decode()

    def listing(self, run):
        return sorted(p.name for p in run.iterdir())

    def ok(self, run, *args):
        """Run the script under test; a good call prints nothing. Returns the new state.md text."""
        done = call(SCRIPT, run, *args)
        self.assertEqual((done.code, done.out, done.err), (OK, "", ""), args)
        return self.state(run)

    def refused(self, run, code, *args):
        """Run a call that must be refused without touching the run dir. Returns the stderr text."""
        before, files = self.state(run), self.listing(run)
        done = call(SCRIPT, run, *args)
        self.assertEqual(done.code, code, f"{args}: {done.err}")
        self.assertEqual(done.out, "")
        self.assertEqual(self.state(run), before, "state.md changed")
        self.assertEqual(self.listing(run), files, "stray file left in the run dir")
        return done.err


class BatchModeTest(StateSetCase):
    def test_sets_several_keys_in_one_call(self):
        run = self.fresh()
        before = self.state(run)
        after = self.ok(run, "mode", "--set", "current unit=u2", "phase=build", "reviewed sha=abc123")
        self.assertEqual(mode_lines(after), [SHIP, "current unit: u2", "phase: build", "reviewed sha: abc123"])
        self.assertEqual(without(after, MODE), without(before, MODE))

    def test_replaces_an_existing_key_in_place_and_adds_a_new_one(self):
        run = self.fresh()
        self.ok(run, "mode", "phase", "plan")
        self.ok(run, "mode", "--set", "phase=build", "mission=m1", "current unit=u2")
        after = self.state(run)
        self.assertEqual(mode_lines(after), [SHIP, "current unit: u2", "phase: build", "mission: m1"])


class BatchTableTest(StateSetCase):
    def test_sets_several_columns_of_one_units_row(self):
        run = self.fresh()
        before = self.state(run)
        after = self.ok(run, "units", "--set", "u1", "status=building", "reviewed SHA=abc123", "head=def456")
        self.assertEqual(
            table_rows(after, UNITS),
            [
                row("u1", "feat", "", "main", "def456", "", "abc123", "building", ""),
                row("u2", "feat2", "", "main", "", "", "", "planned", ""),
            ],
        )
        self.assertEqual(without(after, UNITS), without(before, UNITS))

    def test_updates_several_trace_rows_each_with_its_own_values(self):
        run = self.fresh()
        before = self.state(run)
        after = self.ok(
            run, "trace", "--set", "a", "status=done", "evidence=ev-a", "--set", "b", "status=partial", "evidence=ev-b"
        )
        self.assertEqual(
            table_rows(after, TRACE),
            [
                row("a", "u1", "t-a", "done", "ev-a"),
                row("b", "u1", "t-b", "partial", "ev-b"),
                row("c", "u2", "t-c", "open", ""),
            ],
        )
        self.assertEqual(without(after, TRACE), without(before, TRACE))


# (label, call, the start of the one stderr line). The bad field comes after a valid one, so a partial write shows.
REFUSALS = [
    (
        "unknown row",
        ["trace", "--set", "a", "status=done", "--set", "zz", "status=done"],
        "trace row zz column status: ",
    ),
    ("unknown column", ["units", "--set", "u1", "status=building", "bogus=1"], "units row u1 column bogus: "),
    ("status outside the set", ["units", "--set", "u1", "notes=n", "status=bogus"], "units row u1 column status: "),
    ("newline in a value", ["units", "--set", "u1", "status=building", "notes=a\nb"], "units row u1 column notes: "),
    ("key column of units", ["units", "--set", "u1", "status=building", "unit=x"], "units row u1 column unit: "),
    (
        "bad field in the second --set group",
        ["trace", "--set", "a", "status=done", "--set", "b", "evidence=e", "status=bogus"],
        "trace row b column status: ",
    ),
    ("invalid mode key", ["mode", "--set", "phase=build", "Bad Key=1"], "mode key Bad Key: "),
]

# The section is what the refusal names.
OLD_FORMAT = [("units", UNITS, ["units", "--set", "u1", "status=building", "notes=x"])]


class RefusalTest(StateSetCase):
    def test_a_batch_with_one_invalid_field_is_refused_whole(self):
        for label, args, start in REFUSALS:
            with self.subTest(label):
                err = self.refused(self.fresh(), REFUSED, *args)
                self.assertEqual(err.count("\n"), 1, err)
                self.assertTrue(err.startswith(start), err)
                self.assertGreater(len(err), len(start) + 1, "the line gives no reason")

    def test_an_old_format_section_is_refused_and_named(self):
        for table, heading, args in OLD_FORMAT:
            with self.subTest(table):
                run = self.fresh()
                (run / "state.md").write_text(as_prose(self.state(run), heading))
                err = self.refused(run, REFUSED, *args)
                self.assertEqual(err.count("\n"), 1, err)
                self.assertIn(table, err.lower())


# Calls that are bad usage of the batch form. Each exits 5, prints the usage text, and leaves state.md alone.
BAD_USAGE = [
    ("mode --set with no pairs", ["mode", "--set"]),
    ("units --set with a row and no pairs", ["units", "--set", "u1"]),
    ("trace --set, good pair then a pair with no =", ["trace", "--set", "a", "status=done", "evidence"]),
]


class UsageTest(StateSetCase):
    def test_bad_usage_of_the_batch_form_exits_5(self):
        for label, args in BAD_USAGE:
            with self.subTest(label):
                self.refused(self.fresh(), USAGE, *args)


class SingleFormTest(StateSetCase):
    def test_mode_sets_a_key(self):
        after = self.ok(self.fresh(), "mode", "phase", "build")
        self.assertEqual(mode_lines(after), [SHIP, "current unit: u1", "phase: build"])

    def test_units_set_escapes_a_pipe(self):
        after = self.ok(self.fresh(), "units", "u1", "notes", "a|b")
        self.assertEqual(table_rows(after, UNITS)[0], row("u1", "feat", "", "main", "", "", "", "planned", "a\\|b"))

    def test_add_appends_a_row(self):
        after = self.ok(self.fresh(), "units", "--add", "u3", "branch=b3", "base=main")
        self.assertEqual(table_rows(after, UNITS)[-1], row("u3", "b3", "", "main", "", "", "", "planned", ""))

    def test_drop_removes_a_row(self):
        after = self.ok(self.fresh(), "units", "--drop", "u2")
        self.assertEqual(table_rows(after, UNITS), [row("u1", "feat", "", "main", "", "", "", "planned", "")])

    def test_a_missing_section_is_refused(self):
        run = self.fresh()
        text = self.state(run)
        (run / "state.md").write_text("\n".join(ln for ln in text.splitlines() if not ln.startswith(UNITS)) + "\n")
        self.refused(run, REFUSED, "units", "u1", "status", "building")

    def test_a_run_dir_that_is_not_there_is_bad_usage(self):
        self.assertEqual(call(SCRIPT, self.root / "no-such-run", "mode", "k", "v").code, USAGE)


class OrderTest(StateSetCase):
    def test_new_mode_keys_go_in_in_argument_order(self):
        after = self.ok(self.fresh(), "mode", "--set", "zeta=1", "current unit=u3", "alpha=2", "mid=3")
        self.assertEqual(mode_lines(after), [SHIP, "current unit: u3", "zeta: 1", "alpha: 2", "mid: 3"])

    def test_a_repeated_mode_key_last_wins(self):
        after = self.ok(self.fresh(), "mode", "--set", "phase=plan", "mission=m", "phase=build")
        self.assertEqual(mode_lines(after), [SHIP, "current unit: u1", "phase: build", "mission: m"])

    def test_a_repeated_row_applies_in_order(self):
        after = self.ok(
            self.fresh(),
            "trace",
            "--set",
            "a",
            "status=partial",
            "--set",
            "b",
            "status=done",
            "--set",
            "a",
            "status=done",
            "evidence=e",
        )
        self.assertEqual(
            table_rows(after, TRACE),
            [row("a", "u1", "t-a", "done", "e"), row("b", "u1", "t-b", "done", ""), row("c", "u2", "t-c", "open", "")],
        )


class ValueTest(StateSetCase):
    def test_a_table_value_splits_at_the_first_equals_only(self):
        after = self.ok(self.fresh(), "trace", "--set", "a", "evidence=x=y=z", "status=done")
        self.assertEqual(table_rows(after, TRACE)[0], row("a", "u1", "t-a", "done", "x=y=z"))

    def test_a_pipe_in_a_table_cell_is_escaped(self):
        after = self.ok(self.fresh(), "units", "--set", "u1", "notes=a|b", "status=building")
        self.assertEqual(table_rows(after, UNITS)[0], row("u1", "feat", "", "main", "", "", "", "building", "a\\|b"))

    def test_a_pipe_in_a_row_key_is_escaped_to_find_the_row(self):
        run = self.fresh()
        self.ok(run, "trace", "--add", "x|y", "unit=u1")
        after = self.ok(run, "trace", "--set", "x|y", "status=done", "evidence=e")
        self.assertEqual(table_rows(after, TRACE)[-1], row("x\\|y", "u1", "", "done", "e"))

    def test_a_mode_value_splits_at_the_first_equals_and_keeps_a_pipe(self):
        after = self.ok(self.fresh(), "mode", "--set", "alpha=a|b", "beta=c=d")
        self.assertEqual(mode_lines(after), [SHIP, "current unit: u1", "alpha: a|b", "beta: c=d"])


class TeamInitRunName(unittest.TestCase):
    """A run name must fit the report's resume pattern, so team-init.sh refuses any other."""

    def init(self, name):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "repo").mkdir()
            proc = subprocess.run(
                [str(TEAM_INIT), name, str(Path(tmp) / "repo")],
                env={**ENV, "AGENT_TEAMS_DIR": str(Path(tmp) / "teams")},
                capture_output=True,
                text=True,
                check=False,
            )
            return proc.returncode, (Path(tmp) / "teams").exists()

    def test_names_outside_the_resume_pattern_are_refused_before_anything_is_made(self):
        for name in ("my run", "a/b"):
            with self.subTest(name=name):
                self.assertEqual(self.init(name), (5, False))

    def test_a_plain_name_is_accepted(self):
        self.assertEqual(self.init("issue-200.v2_a")[0], 0)


if __name__ == "__main__":
    unittest.main()
