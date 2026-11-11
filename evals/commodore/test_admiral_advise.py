"""Tests for `admiral-io.sh advise`: the stakes line it prints for a draft call, and the drafts it refuses."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills" / "engineering" / "commodore" / "scripts" / "admiral-io.sh"

OK = 0
INVALID = 2
USAGE = 5

DRAFT = {
    "question": "Rename the helper before the PR?",
    "options": ["Rename it", "Leave it"],
    "recommendation": "Rename it",
}
KEYS = {"stakes", "reason", "cost"}


def without(key):
    d = copy.deepcopy(DRAFT)
    del d[key]
    return d


def with_(**changes):
    return {**copy.deepcopy(DRAFT), **changes}


class AdviseCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "log"
        self.log.mkdir()
        self.stub_out = self.tmp / "stub-out"
        self.stub_code = self.tmp / "stub-code"
        self.set_stub("", 0)

    def set_stub(self, stdout, code):
        self.stub_out.write_text(stdout)
        self.stub_code.write_text(str(code))
        stub = self.bin / "admiral"
        stub.write_text(
            "#!/bin/sh\n"
            f'for a in "$@"; do printf "%s\\n" "$a"; done > "{self.log}/argv"\n'
            f'cat > "{self.log}/stdin"\n'
            f'cat "{self.stub_out}"\n'
            f'exit "$(cat "{self.stub_code}")"\n'
        )
        stub.chmod(0o755)

    def stub_answers(self, **fields):
        self.set_stub(json.dumps({"stakes": "low", "reason": "Cheap to undo.", "cost": 0.04, **fields}), 0)

    def stub_called(self):
        return (self.log / "stdin").exists()

    def draft(self, draft=DRAFT):
        p = self.tmp / "draft.json"
        p.write_text(draft if isinstance(draft, str) else json.dumps(draft))
        return p

    def env(self, path_dirs=None, ship="little-bramble"):
        if path_dirs is None:
            path_dirs = [str(self.bin), *os.environ["PATH"].split(os.pathsep)]
        env = {**os.environ, "PATH": os.pathsep.join(path_dirs)}
        env.pop("ADMIRAL_SHIP", None)
        if ship is not None:
            env["ADMIRAL_SHIP"] = ship
        return env

    def run_advise(self, *args, env=None):
        return subprocess.run(
            [str(SCRIPT), "advise", *args], env=env or self.env(), capture_output=True, text=True, check=False
        )

    def advise(self, draft=DRAFT, env=None):
        return self.run_advise(str(self.draft(draft)), env=env)

    def assertHigh(self, r):
        self.assertEqual(r.returncode, OK, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["stakes"], "high")
        self.assertIsInstance(out["reason"], str)
        self.assertTrue(out["reason"].strip())
        return out


class TestAnswers(AdviseCase):
    def test_a_low_answer_passes_through_and_the_draft_goes_on_stdin(self):
        draft = json.dumps(DRAFT, indent=1, ensure_ascii=False) + "\n"
        self.stub_answers()
        r = self.advise(draft)
        self.assertEqual(r.returncode, OK, r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertEqual(json.loads(r.stdout), {"stakes": "low", "reason": "Cheap to undo.", "cost": 0.04})
        self.assertEqual((self.log / "stdin").read_text(), draft)
        self.assertEqual((self.log / "argv").read_text().split(), ["advise"])
        self.assertNotIn(DRAFT["question"], (self.log / "argv").read_text())

    def test_a_high_answer_is_printed_as_high(self):
        self.stub_answers(stakes="high", reason="Hard to undo.")
        r = self.advise()
        self.assertEqual(r.returncode, OK, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"stakes": "high", "reason": "Hard to undo.", "cost": 0.04})

    def test_a_null_cost_is_passed_through(self):
        self.stub_answers(cost=None)
        r = self.advise()
        self.assertEqual(r.returncode, OK, r.stderr)
        self.assertIsNone(json.loads(r.stdout)["cost"])

    def test_the_output_has_exactly_the_three_keys_even_when_the_judge_adds_more(self):
        self.stub_answers(extra="x")
        r = self.advise()
        self.assertEqual(r.returncode, OK, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(set(out), KEYS)
        self.assertEqual(out["stakes"], "high")
        self.assertTrue(out["cost"] is None or isinstance(out["cost"], (int, float)))


class TestFallsBackToHigh(AdviseCase):
    def test_a_non_zero_exit_from_admiral_is_high(self):
        self.set_stub(json.dumps({"stakes": "low", "reason": "r", "cost": None}) + "\nLEAKED-MARKER", 1)
        out = self.assertHigh(self.advise())
        self.assertNotIn("LEAKED-MARKER", out["reason"])
        self.assertEqual(set(out), KEYS)
        self.assertIsNone(out["cost"])

    def test_no_admiral_on_path_is_high(self):
        dirs = [d for d in os.environ["PATH"].split(os.pathsep) if not (Path(d) / "admiral").exists()]
        out = self.assertHigh(self.advise(env=self.env(path_dirs=dirs)))
        self.assertEqual(set(out), KEYS)
        self.assertIsNone(out["cost"])

    def test_no_admiral_ship_is_high_and_admiral_is_not_called(self):
        self.stub_answers()
        self.assertHigh(self.advise(env=self.env(ship=None)))
        self.assertFalse(self.stub_called())

    def test_an_empty_admiral_ship_is_high_and_admiral_is_not_called(self):
        self.stub_answers()
        self.assertHigh(self.advise(env=self.env(ship="")))
        self.assertFalse(self.stub_called())

    def test_an_answer_over_several_lines_is_high(self):
        self.set_stub(json.dumps({"stakes": "low", "reason": "Cheap to undo.", "cost": 0.04}, indent=1), 0)
        self.assertHigh(self.advise())

    def test_unparseable_output_is_high(self):
        self.set_stub("not json at all\n", 0)
        self.assertHigh(self.advise())

    def test_a_stakes_other_than_low_or_high_is_high(self):
        self.stub_answers(stakes="medium")
        self.assertHigh(self.advise())

    def test_an_answer_without_a_reason_is_high(self):
        self.set_stub(json.dumps({"stakes": "low", "cost": 0.01}), 0)
        self.assertHigh(self.advise())


class TestInvalidDrafts(AdviseCase):
    def assertRefused(self, draft):
        self.stub_answers()
        r = self.advise(draft)
        self.assertEqual(r.returncode, INVALID, r.stderr)
        self.assertFalse(self.stub_called(), "an invalid draft must never reach admiral")

    def test_fewer_than_two_options_is_refused(self):
        self.assertRefused(with_(options=["Rename it"]))

    def test_duplicate_options_are_refused(self):
        self.assertRefused(with_(options=["Rename it", "Rename it"]))

    def test_an_empty_option_is_refused(self):
        self.assertRefused(with_(options=["Rename it", ""]))

    def test_a_recommendation_that_is_not_an_option_is_refused(self):
        self.assertRefused(with_(recommendation="Delete it"))

    def test_a_missing_field_is_refused(self):
        self.assertRefused(without("question"))

    def test_a_draft_over_one_mebibyte_is_refused(self):
        self.assertRefused(with_(question="x" * (1024 * 1024)))

    def test_a_draft_that_is_not_json_is_refused(self):
        self.assertRefused("{not json")


class TestUsage(AdviseCase):
    def test_no_draft_argument_is_a_usage_error(self):
        self.assertEqual(self.run_advise().returncode, USAGE)

    def test_an_extra_argument_is_a_usage_error(self):
        r = self.run_advise(str(self.draft()), "extra")
        self.assertEqual(r.returncode, USAGE)


if __name__ == "__main__":
    unittest.main()
