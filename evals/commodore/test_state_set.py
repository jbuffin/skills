"""Tests for skills/engineering/commodore/scripts/state-set.sh.

The only seam is the script's command line: a run directory made by team-init.sh, seeded with the existing
`--add` form, then state-set.sh run as a subprocess. Tests assert on state.md's text, stdout, stderr and the exit
code. Expected values are literals worked out by hand from the seeded run. The ac5 compatibility tests run the
same call against state-set.sh as of c04c275 and against the worktree's script, and compare.

Run from the repo root: python3 -m unittest evals.commodore.test_state_set -v
"""

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMMODORE = REPO / "skills" / "engineering" / "commodore"
SCRIPT = COMMODORE / "scripts" / "state-set.sh"
TEAM_INIT = COMMODORE / "scripts" / "team-init.sh"
BASELINE = "c04c275"

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


class StateSetCase(unittest.TestCase):
    """Every test gets copies of one seeded run dir, so a test never sees another's edits."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "repo").mkdir()
        init = subprocess.run(
            [str(TEAM_INIT), "seed", str(root / "repo")],
            env={**ENV, "AGENT_TEAMS_DIR": str(root / "teams")},
            capture_output=True,
            text=True,
            check=True,
        )
        assert init.returncode == OK
        cls.root = root
        cls.seed = root / "teams" / "seed"
        # Seeding goes through the baseline script, so a broken --add in the script under test fails the tests
        # about it and not every test.
        cls.baseline = root / "state-set-baseline.sh"
        source = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{BASELINE}:skills/engineering/commodore/scripts/state-set.sh"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        cls.baseline.write_text(source)
        cls.baseline.chmod(cls.baseline.stat().st_mode | stat.S_IXUSR)
        cls.copies = 0
        cls.seed_rows()

    @classmethod
    def seed_rows(cls):
        steps = [
            ["units", "--add", "u1", "branch=feat", "base=main"],
            ["units", "--add", "u2", "branch=feat2", "base=main"],
            ["trace", "--add", "a", "unit=u1", "test or scenario=t-a"],
            ["trace", "--add", "b", "unit=u1", "test or scenario=t-b"],
            ["trace", "--add", "c", "unit=u2", "test or scenario=t-c"],
            ["findings", "--add", "f1", "unit=u1", "severity=low", "finding=one"],
            ["findings", "--add", "f2", "unit=u1", "severity=low", "finding=two"],
            ["mode", "current unit", "u1"],
        ]
        for step in steps:
            done = call(cls.baseline, cls.seed, *step)
            assert (done.code, done.out, done.err) == (OK, "", ""), step

    def fresh(self):
        type(self).copies += 1
        run = self.root / "copies" / f"run{self.copies}"
        shutil.copytree(self.seed, run)
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

    def test_updates_several_findings_rows(self):
        run = self.fresh()
        after = self.ok(run, "findings", "--set", "f1", "status=fixed", "--set", "f2", "status=human", "severity=high")
        self.assertEqual(
            table_rows(after, FINDINGS),
            [
                row("f1", "u1", "low", "one", "fixed"),
                row("f2", "u1", "high", "two", "human"),
            ],
        )


# (label, call, the start of the one stderr line). The bad field comes after a valid one, so a partial write shows.
REFUSALS = [
    (
        "unknown row",
        ["trace", "--set", "a", "status=done", "--set", "zz", "status=done"],
        "trace row zz column status: ",
    ),
    ("unknown column", ["units", "--set", "u1", "status=building", "bogus=1"], "units row u1 column bogus: "),
    ("status outside the set", ["units", "--set", "u1", "notes=n", "status=bogus"], "units row u1 column status: "),
    (
        "trace status outside the set",
        ["trace", "--set", "a", "evidence=e", "status=closed"],
        "trace row a column status: ",
    ),
    (
        "findings status outside the set",
        ["findings", "--set", "f1", "severity=high", "status=done"],
        "findings row f1 column status: ",
    ),
    ("newline in a value", ["units", "--set", "u1", "status=building", "notes=a\nb"], "units row u1 column notes: "),
    (
        "carriage return in a value",
        ["trace", "--set", "a", "status=done", "evidence=a\rb"],
        "trace row a column evidence: ",
    ),
    ("key column of units", ["units", "--set", "u1", "status=building", "unit=x"], "units row u1 column unit: "),
    ("key column of trace", ["trace", "--set", "a", "status=done", "criterion=x"], "trace row a column criterion: "),
    (
        "bad field in the second --set group",
        ["trace", "--set", "a", "status=done", "--set", "b", "evidence=e", "status=bogus"],
        "trace row b column status: ",
    ),
    (
        "unknown row in the second --set group",
        ["trace", "--set", "a", "status=done", "--set", "nope", "status=done", "evidence=e"],
        "trace row nope column status: ",
    ),
    ("invalid mode key", ["mode", "--set", "phase=build", "Bad Key=1"], "mode key Bad Key: "),
    ("mode key starting with a digit", ["mode", "--set", "phase=build", "1x=1"], "mode key 1x: "),
    ("newline in a mode value", ["mode", "--set", "phase=build", "note=a\nb"], "mode key note: "),
]

# Every field in these calls hits the old-format section; the section is what the line names.
OLD_FORMAT = [
    ("units", UNITS, ["units", "--set", "u1", "status=building", "notes=x"]),
    ("trace", TRACE, ["trace", "--set", "a", "status=done", "evidence=e", "--set", "b", "status=done"]),
    ("findings", FINDINGS, ["findings", "--set", "f1", "status=fixed", "severity=high"]),
]


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
    ("mode --set with a pair that has no =", ["mode", "--set", "phase"]),
    ("mode --set, good pair then a pair with no =", ["mode", "--set", "phase=build", "mission"]),
    ("units --set with no row", ["units", "--set"]),
    ("units --set with a row and no pairs", ["units", "--set", "u1"]),
    ("trace --set with a pair that has no =", ["trace", "--set", "a", "status"]),
    ("trace --set, good pair then a pair with no =", ["trace", "--set", "a", "status=done", "evidence"]),
    ("trailing --set with no row", ["trace", "--set", "a", "status=done", "--set"]),
    ("second --set group with no pairs", ["trace", "--set", "a", "status=done", "--set", "b"]),
    ("second --set group with a pair that has no =", ["trace", "--set", "a", "status=done", "--set", "b", "status"]),
]


class UsageTest(StateSetCase):
    def test_bad_usage_of_the_batch_form_exits_5(self):
        for label, args in BAD_USAGE:
            with self.subTest(label):
                self.refused(self.fresh(), USAGE, *args)

    def test_the_usage_text_shows_the_batch_form(self):
        # At c04c275 the usage text never prints: `$0` inside the usage function is "usage", so sed fails.
        err = self.refused(self.fresh(), USAGE, "mode", "--set")
        self.assertIn("--set", err)


# (label, call, exit code at c04c275, how to prepare state.md first). No call has --set after the table or mode.
def prose(heading):
    return lambda text: as_prose(text, heading)


def drop_heading(heading):
    return lambda text: "\n".join(line for line in text.splitlines() if not line.startswith(heading)) + "\n"


COMPAT = [
    ("mode adds a key", ["mode", "phase", "build"], OK, None),
    ("mode replaces a key", ["mode", "current unit", "u9"], OK, None),
    ("mode keeps a pipe", ["mode", "note", "a|b"], OK, None),
    ("mode keeps an equals sign", ["mode", "note", "a=b"], OK, None),
    ("mode invalid key", ["mode", "Bad Key", "x"], REFUSED, None),
    ("mode newline in a value", ["mode", "note", "a\nb"], REFUSED, None),
    ("units set one field", ["units", "u1", "status", "building"], OK, None),
    ("units set a column with a space", ["units", "u1", "reviewed SHA", "abc"], OK, None),
    ("units set escapes a pipe", ["units", "u1", "notes", "a|b"], OK, None),
    ("units unknown row", ["units", "zz", "status", "building"], REFUSED, None),
    ("units unknown column", ["units", "u1", "bogus", "x"], REFUSED, None),
    ("units status outside the set", ["units", "u1", "status", "bogus"], REFUSED, None),
    ("units key column", ["units", "u1", "unit", "x"], REFUSED, None),
    ("units newline in a value", ["units", "u1", "notes", "a\nb"], REFUSED, None),
    ("trace set one field", ["trace", "a", "evidence", "ev"], OK, None),
    ("trace status outside the set", ["trace", "a", "status", "closed"], REFUSED, None),
    ("findings set one field", ["findings", "f1", "status", "fixed"], OK, None),
    ("findings status outside the set", ["findings", "f1", "status", "done"], REFUSED, None),
    ("add a row", ["units", "--add", "u3", "branch=b3", "base=main"], OK, None),
    ("add a row with no columns", ["trace", "--add", "d"], OK, None),
    ("add a row, value with = and |", ["findings", "--add", "f3", "unit=u1", "finding=a=b|c"], OK, None),
    ("add a row that exists", ["units", "--add", "u1"], REFUSED, None),
    ("add with a status outside the set", ["units", "--add", "u3", "status=bogus"], REFUSED, None),
    ("add with an unknown column", ["units", "--add", "u3", "bogus=1"], REFUSED, None),
    ("add with the key column", ["units", "--add", "u3", "unit=x"], REFUSED, None),
    ("add with a newline in a value", ["units", "--add", "u3", "notes=a\nb"], REFUSED, None),
    ("drop a row", ["units", "--drop", "u2"], OK, None),
    ("drop the last findings row", ["findings", "--drop", "f2"], OK, None),
    ("drop a row that is not there", ["trace", "--drop", "zz"], REFUSED, None),
    ("units set on an old-format section", ["units", "u1", "status", "building"], REFUSED, prose(UNITS)),
    ("add on an old-format section", ["trace", "--add", "d"], REFUSED, prose(TRACE)),
    ("drop on an old-format section", ["findings", "--drop", "f1"], REFUSED, prose(FINDINGS)),
    ("section missing", ["units", "u1", "status", "building"], REFUSED, drop_heading(UNITS)),
    ("mode section missing", ["mode", "phase", "build"], REFUSED, drop_heading(MODE)),
    ("mode value is --set", ["mode", "phase", "--set"], OK, None),
    ("units set value is --set", ["units", "u1", "notes", "--set"], OK, None),
    ("drop of a row named --set", ["units", "--drop", "--set"], REFUSED, None),
    ("add of a row named --set", ["units", "--add", "--set"], OK, None),
    ("usage: too few arguments for a set", ["units", "u1", "status"], USAGE, None),
    ("usage: too many arguments for a set", ["units", "u1", "status", "a", "b"], USAGE, None),
    ("usage: mode with no value", ["mode", "phase"], USAGE, None),
    ("usage: unknown table", ["bogus", "u1", "status", "x"], USAGE, None),
    ("usage: --add with no row", ["units", "--add"], USAGE, None),
    ("usage: --add with a pair that has no =", ["units", "--add", "u3", "branch"], USAGE, None),
    ("usage: --drop with no row", ["units", "--drop"], USAGE, None),
    ("usage: --drop with two rows", ["units", "--drop", "u1", "u2"], USAGE, None),
]


class CompatibilityTest(StateSetCase):
    """ac5. These pass before the batch form exists; they guard the forms that must not change."""

    def test_existing_forms_match_the_baseline_script(self):
        for label, args, code, prepare in COMPAT:
            with self.subTest(label):
                old_run, new_run = self.fresh(), self.fresh()
                if prepare:
                    for run in (old_run, new_run):
                        (run / "state.md").write_text(prepare(self.state(run)))
                old, new = call(self.baseline, old_run, *args), call(SCRIPT, new_run, *args)
                self.assertEqual(old.code, code, "the baseline exit code is not what the case expects")
                self.assertEqual(new.code, old.code)
                self.assertEqual(self.state(new_run), self.state(old_run))
                if code != USAGE:  # the usage text gains the --set lines by design
                    self.assertEqual(new.out, old.out)
                    self.assertEqual(new.err, old.err)

    def test_a_run_dir_that_is_not_there_is_bad_usage(self):
        missing = self.root / "no-such-run"
        self.assertEqual(call(self.baseline, missing, "mode", "k", "v").code, USAGE)
        self.assertEqual(call(SCRIPT, missing, "mode", "k", "v").code, USAGE)


class EquivalenceTest(StateSetCase):
    """A batch gives the state.md that the same fields set one at a time, in order, give."""

    def twin(self, batch, singles):
        run, twin = self.fresh(), self.fresh()
        batched = self.ok(run, *batch)
        for single in singles:
            self.ok(twin, *single)
        self.assertEqual(batched, self.state(twin))
        return batched

    def test_new_mode_keys_go_in_in_argument_order(self):
        after = self.twin(
            ["mode", "--set", "zeta=1", "current unit=u3", "alpha=2", "mid=3"],
            [["mode", "zeta", "1"], ["mode", "current unit", "u3"], ["mode", "alpha", "2"], ["mode", "mid", "3"]],
        )
        self.assertEqual(mode_lines(after), [SHIP, "current unit: u3", "zeta: 1", "alpha: 2", "mid: 3"])

    def test_a_repeated_mode_key_last_wins(self):
        after = self.twin(
            ["mode", "--set", "phase=plan", "mission=m", "phase=build"],
            [["mode", "phase", "plan"], ["mode", "mission", "m"], ["mode", "phase", "build"]],
        )
        self.assertEqual(mode_lines(after), [SHIP, "current unit: u1", "phase: build", "mission: m"])

    def test_a_repeated_column_last_wins(self):
        after = self.twin(
            ["units", "--set", "u1", "notes=first", "status=building", "notes=last"],
            [
                ["units", "u1", "notes", "first"],
                ["units", "u1", "status", "building"],
                ["units", "u1", "notes", "last"],
            ],
        )
        self.assertEqual(table_rows(after, UNITS)[0], row("u1", "feat", "", "main", "", "", "", "building", "last"))

    def test_a_repeated_row_applies_in_order(self):
        after = self.twin(
            [
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
            ],
            [
                ["trace", "a", "status", "partial"],
                ["trace", "b", "status", "done"],
                ["trace", "a", "status", "done"],
                ["trace", "a", "evidence", "e"],
            ],
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


class DocsTest(StateSetCase):
    def test_the_skill_no_longer_says_one_field_per_call(self):
        self.assertNotIn("one field per call", (COMMODORE / "SKILL.md").read_text())

    def test_closing_a_unit_shows_one_trace_call_and_one_units_call(self):
        lines = (COMMODORE / "references" / "mission-build.md").read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("7. "))
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i][:1].isdigit() or lines[i].startswith("#")),
            len(lines),
        )
        step = "\n".join(lines[start:end])
        self.assertIn("trace --set", step)
        self.assertIn("units --set", step)


if __name__ == "__main__":
    unittest.main()
