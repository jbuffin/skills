"""Tests for question items inside an Admiral ship (issue #166).

With `ADMIRAL_SHIP` set and autopilot off, Commodore asks the engineer through a question item or AskUserQuestion and
never through a prose `needs input:` line. The seam is the text of the shipped docs. Expected values come from the
rules the skill must follow, not from any implementation. Each section is located by headings that exist on main, so
the implementer is free to put the new rules in the bullet, a subsection or a section after "Bubbling questions up".

Where autopilot mode already states a
rule, the shipped text may point at it instead of repeating it, so those checks accept either form.

`TestRegressionGuards` holds the only tests that pass before the change: they must keep passing.

The changeset is checked by hand: the release workflow consumes it, so a test for it would break after release.

Run from the repo root: python3 -m unittest evals/commodore/test_inbox_questions.py -v
"""

import re
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMMODORE = REPO / "skills" / "engineering" / "commodore"
SKILL = COMMODORE / "SKILL.md"
MISSION_REVIEW = COMMODORE / "references" / "mission-review.md"
GLOSSARY = REPO / "GLOSSARY.md"

QUESTION_ITEM_ENTRY = (
    "**Question item**: an item Commodore writes to its Admiral ship's inbox to ask the engineer one or more "
    "questions, each with options and a recommendation. The engineer answers it from the inbox, not in the "
    "session. _Avoid_: inbox question, needs-input line."
)

UNCHANGED_FILES = (
    "skills/engineering/commodore/references/harness-codex.md",
    "skills/engineering/commodore/references/harness-copilot.md",
    "skills/engineering/commodore/references/admiral-inbox-item.schema.json",
    "skills/engineering/commodore/scripts/admiral-io.sh",
    "skills/engineering/commodore/references/mission-pr-feedback.md",
)


def text(path):
    return Path(path).read_text()


BASELINE = "c51d027"  # the commit this change started from; the guards compare against it, not a moving branch


def at_baseline(rel):
    """The file at BASELINE as bytes, or None when the commit is missing (shallow checkout)."""
    done = subprocess.run(["git", "show", f"{BASELINE}:{rel}"], cwd=REPO, capture_output=True, check=False)
    return done.stdout if done.returncode == 0 else None


class DocCase(unittest.TestCase):
    def section(self, body, start, end=None):
        """The text from `start` up to `end` (to the end of the body when `end` is None)."""
        self.assertIn(start, body, f"no {start!r}")
        tail = body.split(start, 1)[1]
        if end is None:
            return start + tail
        self.assertIn(end, tail, f"no {end!r} after {start!r}")
        return start + tail.split(end, 1)[0]

    def paragraph(self, body, needle):
        found = [p for p in body.split("\n\n") if needle in p]
        self.assertTrue(found, f"no paragraph with {needle!r}")
        return found[0]

    def line(self, body, needle):
        found = [ln for ln in body.splitlines() if needle in ln]
        self.assertTrue(found, f"no line with {needle!r}")
        return found[0]

    def assertMatches(self, pattern, body, msg=None):
        self.assertRegex(body, re.compile(pattern, re.I | re.S), msg)


class SkillCase(DocCase):
    def setUp(self):
        self.skill = text(SKILL)
        # Every place the in-ship rules can live: the bubbling bullet, a subsection after it, or a new section.
        self.rules = self.section(self.skill, "## Bubbling questions up", "## Guarding the coordinator")

    def restated_or_pointed(self, restated, pointer=r"Resume[^\n]{0,120}steps? 2"):
        """Autopilot's Resume steps 2-3 state the answer rules; the in-ship rules may restate them or point there."""
        self.assertTrue(
            re.search(restated, self.rules, re.I | re.S) or re.search(pointer, self.rules, re.I | re.S),
            f"the in-ship rules neither state this nor point at Resume steps 2-3 ({restated})",
        )


class TestBubblingRule(SkillCase):
    def test_in_a_ship_the_rule_names_the_ship_and_both_ways_to_ask(self):
        para = self.paragraph(self.rules, "ADMIRAL_SHIP")
        self.assertIn("question item", para)
        self.assertIn("AskUserQuestion", para)

    def test_a_question_item_is_for_when_independent_work_remains(self):
        para = self.paragraph(self.rules, "ADMIRAL_SHIP")
        self.assertMatches(r"independent", para)
        self.assertMatches(r"question item.{0,300}independent|independent.{0,300}question item", para)

    def test_ask_user_question_is_for_when_nothing_independent_is_left_recommendation_first(self):
        para = self.paragraph(self.rules, "ADMIRAL_SHIP")
        self.assertMatches(r"(nothing|no work|no independent|none)[^.]{0,80}(independent|left|remain)", para)
        self.assertMatches(r"AskUserQuestion.{0,200}recommend|recommend.{0,200}AskUserQuestion", para)

    def test_in_a_ship_a_needs_input_line_or_prose_alone_is_never_the_way(self):
        para = self.paragraph(self.rules, "ADMIRAL_SHIP")
        self.assertMatches(r"\b(never|not|no)\b[^.]{0,160}(needs input|prose)", para)

    def test_the_needs_input_line_is_scoped_to_outside_admiral(self):
        # Pairs the guard below with a check that fails today: the line is now one branch of two.
        self.assertIn("ADMIRAL_SHIP", self.rules)
        self.assertMatches(r"(outside|without|not in|no) Admiral|ADMIRAL_SHIP[^.]{0,40}(unset|not set)", self.rules)
        self.assertIn("needs input:", self.rules)

    def test_an_empty_admiral_inbox_means_ask_user_question_not_a_question_item(self):
        # admiral-io.sh item prints a note and writes nothing when the inbox is unset.
        self.assertMatches(r"ADMIRAL_INBOX[^\n]{0,200}(empty|unset|not set)", self.rules)


class TestQuestionItemFormat(SkillCase):
    def test_items_use_the_run_name_id_and_share_autopilots_counter(self):
        self.assertIn("-q<n>", self.rules)
        self.assertMatches(r"(counter|next `?n`?|same `?n`?|shares?)", self.rules)
        self.assertIn("autopilot", self.rules)

    def test_items_are_published_with_admiral_io_item_in_the_existing_schema(self):
        self.assertIn("admiral-io.sh item", self.rules)
        # Format is autopilot's: restated, or pointed at (schema file or the high-stakes stop).
        self.assertMatches(
            r"admiral-inbox-item\.schema|high-stakes stop|`version`|kind: question|`question`", self.rules
        )

    def test_questions_are_batched_into_one_item(self):
        para = self.paragraph(self.rules, "ADMIRAL_SHIP")
        self.assertMatches(r"(batch|one question item|a single question item|one item)", para)

    def test_a_later_batch_gets_the_next_n(self):
        self.assertMatches(r"(later|next|another|second)[^.]{0,80}(batch|item)[^.]{0,80}\bn\b|next `?n`?", self.rules)


class TestRecording(SkillCase):
    def test_every_question_item_is_recorded_under_inbox_questions(self):
        self.assertIn("## Inbox questions", self.rules)
        self.assertIn("state.md", self.paragraph(self.rules, "## Inbox questions"))

    def test_the_record_holds_id_inbox_directory_and_questions(self):
        para = self.paragraph(self.rules, "## Inbox questions")
        self.assertMatches(r"\bid\b", para)
        self.assertMatches(r"inbox (dir|directory)", para)
        self.assertMatches(r"questions", para)

    def test_an_applied_mark_is_added_once_the_answer_is_applied(self):
        para = self.paragraph(self.rules, "## Inbox questions")
        self.assertIn("applied", para)

    def test_the_open_questions_section_lists_only_the_item_id(self):
        # The questions aren't kept in two places.
        self.assertIn("Open questions for the engineer", self.rules)


class TestAnswerCheck(SkillCase):
    def test_every_wake_runs_admiral_io_answer_for_each_open_question_item(self):
        self.assertIn("admiral-io.sh answer", self.rules)
        self.assertIn(
            "open question item", self.rules
        )  # not "open item": inbox items also include review and findings items

    def test_all_three_wake_triggers_are_named(self):
        para = self.paragraph(self.rules, "admiral-io.sh answer")
        self.assertMatches(r"watchdog", para)
        self.assertMatches(r"teammate report|report", para)
        self.assertMatches(r"resume", para)

    def test_exit_3_means_unanswered_and_the_coordinator_carries_on(self):
        self.assertMatches(r"exit 3[^.\n]{0,80}unanswered|unanswered[^.\n]{0,80}exit 3", self.rules)


class TestAnswerRules(SkillCase):
    def test_an_answer_is_data_never_instructions(self):
        self.restated_or_pointed(r"data,? (and )?never instructions|data, not instructions")

    def test_only_the_question_ids_the_item_asked_are_accepted(self):
        self.restated_or_pointed(r"only[^.]{0,60}question ids?|question ids?[^.]{0,60}(item )?asked")

    def test_an_answer_that_cannot_be_parsed_is_unanswered(self):
        self.restated_or_pointed(r"(can'?t|cannot|can not|unable to) (be )?parse[^.]{0,80}unanswered")

    def test_security_stop_denial_and_external_write_need_an_exact_option_label(self):
        self.restated_or_pointed(
            r"security stop.{0,300}permission denial.{0,300}external write.{0,300}exact (option )?label"
            r"|exact (option )?label.{0,300}security stop"
        )

    def test_free_text_does_not_clear_a_security_stop(self):
        self.restated_or_pointed(r"free text[^.]{0,120}(unanswered|never|doesn'?t|does not|not clear)")


class TestEscalation(SkillCase):
    def test_when_independent_work_runs_out_the_same_questions_go_to_ask_user_question(self):
        self.assertMatches(r"same questions", self.rules)
        self.assertMatches(r"also in the inbox as", self.rules)

    def test_the_first_answer_wins_and_the_item_is_marked_applied(self):
        self.assertMatches(r"(whichever|first)[^.]{0,80}(answer|arrives?|comes?)", self.rules)
        self.assertMatches(r"(first|whichever)[^.]{0,200}applied|applied[^.]{0,200}(first|whichever)", self.rules)

    def test_a_later_answer_is_ignored_and_noted_in_state_md(self):
        self.assertMatches(r"later answer[^.]{0,120}ignored|ignore[sd]?[^.]{0,60}later answer", self.rules)
        self.assertMatches(r"(ignored|ignore)[^.]{0,200}(noted|note|record)[^.]{0,80}state\.md", self.rules)


class TestResume(SkillCase):
    def setUp(self):
        super().setUp()
        resume = self.section(self.skill, "**Resume.**", "**Marking ready.**")
        steps = [ln for ln in resume.splitlines() if re.match(r"^1\. ", ln)]
        self.assertTrue(steps, "no Resume step 1")
        self.step1 = steps[0]

    def test_resume_step_1_reads_inbox_questions_as_well_as_autopilot_calls(self):
        self.assertIn("## Inbox questions", self.step1)
        self.assertIn("## Autopilot calls", self.step1)
        self.assertIn("admiral-io.sh answer", self.step1)

    def test_mission_resume_detection_counts_an_open_question_item_as_unfinished(self):
        mission = self.section(self.skill, "## The mission, before phase 1", "## Phase 1")
        para = self.paragraph(mission, "A run whose")
        self.assertIn("## Inbox questions", para)
        self.assertIn("## Autopilot calls", para)


class TestEndingARun(SkillCase):
    def setUp(self):
        super().setUp()
        self.ending = self.section(self.skill, "## Ending a run", "## Marking ready")

    def test_an_open_question_item_goes_in_the_admiral_reports_inbox_and_the_final_report(self):
        self.assertMatches(r"question item", self.ending)
        self.assertMatches(r"(open|still open)[^.]{0,200}`?inbox`?|`?inbox`?[^.]{0,200}(open|still open)", self.ending)
        self.assertIn("final report", self.ending)

    def test_the_item_case_covers_a_partial_or_failed_run_outside_autopilot(self):
        self.assertMatches(
            r"question item[^\n]{0,400}(partial|failed)|(partial|failed)[^\n]{0,400}question item", self.ending
        )

    def test_a_partial_run_outside_autopilot_resumes_without_the_autopilot_flag(self):
        # Step 2 must say the resume is /commodore resume <run-name>, without --autopilot.
        self.assertIn("--autopilot", self.ending)

    def test_drafts_for_question_items_in_a_ship_are_written_with_the_file_tool(self):
        step3 = [ln for ln in self.ending.splitlines() if re.match(r"^3\. ", ln)]
        self.assertTrue(step3, "no Ending step 3")
        self.assertNotIn("in autopilot mode, question and review items", step3[0])
        self.assertIn("question item", step3[0])
        self.assertIn("file tool", step3[0])


class TestReviewPostingGate(DocCase):
    def setUp(self):
        review = text(MISSION_REVIEW)
        phase3 = self.section(review, "## Phase 3: report, post and finish")
        steps = [ln for ln in phase3.splitlines() if re.match(r"^3\. ", ln)]
        self.assertTrue(steps, "no Phase 3 step 3")
        self.step3 = steps[0]

    def test_in_a_ship_the_posting_gate_is_always_ask_user_question(self):
        self.assertIn("ADMIRAL_SHIP", self.step3)
        self.assertMatches(
            r"(always|never)[^.]{0,120}AskUserQuestion|AskUserQuestion[^.]{0,120}(always|never)", self.step3
        )

    def test_the_needs_input_line_is_only_for_outside_a_ship(self):
        sentence = [s for s in self.step3.split(". ") if "needs input" in s]
        self.assertTrue(sentence, "no sentence with needs input")
        self.assertMatches(r"(outside|without|not in|no) Admiral|ADMIRAL_SHIP[^.]{0,40}(unset|not set)", sentence[0])

    def test_in_a_ship_the_gate_names_nothing_independent_left(self):
        self.assertMatches(r"nothing (independent|else)|no independent|nothing is left", self.step3)


class TestWords(SkillCase):
    def test_the_autopilot_definition_says_question_item_not_inbox_question(self):
        self.assertNotIn("inbox question", self.skill)


class TestGlossary(unittest.TestCase):
    def test_the_question_item_entry_is_there_word_for_word(self):
        entries = [ln for ln in text(GLOSSARY).splitlines() if ln.startswith("**Question item**")]
        self.assertEqual(len(entries), 1, "want exactly one **Question item** entry")
        self.assertEqual(" ".join(entries[0].split()), QUESTION_ITEM_ENTRY)


class TestRegressionGuards(DocCase):
    """GUARDS: these pass before the change and must keep passing."""

    def setUp(self):
        self.skill = text(SKILL)
        self.rules = self.section(self.skill, "## Bubbling questions up", "## Guarding the coordinator")

    def test_guard_outside_admiral_the_needs_input_line_is_still_there(self):
        self.assertIn("`needs input:` line", self.rules)
        self.assertIn("keep the team on work that doesn't depend on the answer", self.rules)

    def test_guard_the_autopilot_gate_for_bubbling_questions_still_reads_as_before(self):
        self.assertIn(
            "In autopilot mode, an engineer question goes through [Autopilot mode](#autopilot-mode) in place of "
            "AskUserQuestion and the `needs input:` line.",
            self.skill,
        )

    def test_guard_the_review_gate_still_offers_the_three_choices_and_the_needs_input_line(self):
        review = text(MISSION_REVIEW)
        step3 = self.line(review, "3. Send the engineer the list")
        self.assertIn("post as `COMMENT`", step3)
        self.assertIn("edit the findings first", step3)
        self.assertIn("post nothing", step3)
        self.assertIn("`needs input:`", step3)

    def test_guard_the_autopilot_text_is_unchanged_except_resume_step_1(self):
        old = at_baseline("skills/engineering/commodore/SKILL.md")
        if old is None:
            self.skipTest("the baseline commit is not available")

        def autopilot(body):
            tail = body[body.index("## Autopilot mode") :]
            return [ln for ln in tail.splitlines() if not ln.startswith("1. For each item listed under")]

        self.assertEqual(autopilot(self.skill), autopilot(old.decode()))

    def test_guard_files_outside_this_change_are_byte_identical_to_the_baseline(self):
        for rel in UNCHANGED_FILES:
            with self.subTest(path=rel):
                old = at_baseline(rel)
                if old is None:
                    self.skipTest("the baseline commit is not available")
                self.assertEqual((REPO / rel).read_bytes(), old)

    def test_guard_question_item_is_still_defined_in_words_used_here(self):
        self.assertMatches(r"\*\*question item\*\* is[^\n]*kind `question`", self.skill)


if __name__ == "__main__":
    unittest.main()
