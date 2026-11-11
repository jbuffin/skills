"""Tests for `admiral-io.sh answer-write`: the answer file Commodore writes for a question item."""

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
ANSWERED = 4

ITEM = {
    "version": 1,
    "id": "run-q1",
    "kind": "question",
    "created": "2026-11-04T10:00:00Z",
    "title": "Two questions",
    "question": {
        "questions": [
            {
                "id": "scope",
                "text": "Cut scope?",
                "options": [{"label": "Cut", "description": "d"}, {"label": "Keep", "description": "d"}],
                "recommended": "Cut",
                "multi": False,
            },
            {
                "id": "envs",
                "text": "Which environments?",
                "options": [{"label": "stage", "description": "d"}, {"label": "prod", "description": "d"}],
                "recommended": "stage",
                "multi": True,
            },
        ]
    },
}


def answer(**changes):
    value = {
        "version": 1,
        "id": "run-q1",
        "kind": "question",
        "answered": "2026-11-04T11:00:00Z",
        "answers": {"scope": {"choice": "Cut"}, "envs": {"choice": ["stage", "prod"]}},
        "note": "Answered in the terminal.",
    }
    value.update(changes)
    return value


class AnswerWrite(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        (self.inbox / "run-q1.json").write_text(json.dumps(ITEM))

    def run_write(self, draft, item_id="run-q1"):
        path = self.root / "draft.json"
        path.write_text(draft if isinstance(draft, str) else json.dumps(draft))
        env = {k: v for k, v in os.environ.items() if not k.startswith("ADMIRAL_")}
        proc = subprocess.run(
            [str(SCRIPT), "answer-write", str(self.inbox), item_id, str(path)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, proc.stderr

    def target(self):
        return self.inbox / "run-q1.answer.json"

    def inbox_names(self):
        return sorted(p.name for p in self.inbox.iterdir())

    def test_writes_the_answer_beside_the_item(self):
        draft = answer(answers={"scope": {"other": "Ask me later"}, "envs": {"choice": ["prod"], "other": "and qa"}})
        self.assertEqual(self.run_write(draft), (OK, ""))
        self.assertEqual(json.loads(self.target().read_text()), draft)
        self.assertEqual(self.inbox_names(), ["run-q1.answer.json", "run-q1.json"])

    def test_never_replaces_an_existing_answer(self):
        self.target().write_text('{"from": "admiral"}')
        code, err = self.run_write(answer())
        self.assertEqual(code, ANSWERED)
        self.assertIn("already exists", err)
        self.assertEqual(self.target().read_text(), '{"from": "admiral"}')

    def refused(self, draft, reason, item_id="run-q1"):
        code, err = self.run_write(draft, item_id)
        self.assertEqual(code, INVALID, err)
        self.assertIn(reason, err)
        self.assertEqual(self.inbox_names(), ["run-q1.json"])

    def test_refuses_a_missing_question(self):
        self.refused(answer(answers={"scope": {"choice": "Cut"}}), "'envs'")

    def test_refuses_an_unknown_question(self):
        draft = answer()
        draft["answers"]["extra"] = {"other": "x"}
        self.refused(draft, "'extra'")

    def test_refuses_a_label_the_question_doesnt_offer(self):
        draft = answer()
        draft["answers"]["scope"] = {"choice": "Maybe"}
        self.refused(draft, "'Maybe'")

    def test_refuses_a_list_on_a_single_choice_question(self):
        draft = answer()
        draft["answers"]["scope"] = {"choice": ["Cut"]}
        self.refused(draft, "isn't multi")

    def test_refuses_an_empty_answer(self):
        draft = answer()
        draft["answers"]["scope"] = {}
        self.refused(draft, "needs a choice or an other")

    def test_refuses_another_items_id(self):
        self.refused(answer(id="run-q2"), "isn't the item's id")

    def test_refuses_a_time_that_isnt_utc(self):
        self.refused(answer(answered="2026-11-04T11:00:00+01:00"), "/answered")

    def test_refuses_unknown_fields(self):
        self.refused(answer(removed=True), "/removed")

    def test_refuses_a_draft_that_isnt_json(self):
        self.refused("{not json", "isn't valid JSON")

    def test_refuses_an_item_that_doesnt_exist(self):
        self.refused(answer(id="run-q9"), "no item", item_id="run-q9")

    def test_refuses_an_id_with_a_path_in_it(self):
        self.refused(answer(), "invalid item id", item_id="../run-q1")

    def test_refuses_a_review_item(self):
        (self.inbox / "run-q1.json").write_text(
            json.dumps({**{k: ITEM[k] for k in ("version", "id", "created", "title")}, "kind": "review"})
        )
        self.refused(answer(), "only a question item's answer is written here")


if __name__ == "__main__":
    unittest.main()
