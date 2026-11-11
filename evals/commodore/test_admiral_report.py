"""Admiral report v2 and slices (issue #200, ADR 0009 "Slices" and "What comes back").

Two seams. The schema seam drives `scripts/admiral-io.sh report` with `ADMIRAL_REPORT` set to a temp file, and
`scripts/schema-check.py` against the report schema. The text seam reads the skill's own files for the short phrases
the report and slice rules need. Expected values are literals from the brief.

Run from the repo root: python3 -m unittest evals/commodore/test_admiral_report.py -v
"""

import copy
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILL_DIR = REPO / "skills" / "engineering" / "commodore"
SCRIPTS = SKILL_DIR / "scripts"
IO = SCRIPTS / "admiral-io.sh"
CHECK = SCRIPTS / "schema-check.py"
SCHEMA = SKILL_DIR / "references" / "admiral-report.schema.json"

DONE = {
    "version": 2,
    "result": "done",
    "why": "Built and shipped.",
    "prs": [
        {"url": "https://github.com/example/fixture/pull/7", "closes": ["example/fixture#12"]},
        {"url": "https://github.com/example/fixture/pull/8", "closes": []},
    ],
    "cast": [
        {"member": "ada", "role": "implementer", "ad_hoc": False},
        {"member": "tmp-scribe", "role": "scribe", "ad_hoc": True},
    ],
    "resume": "/commodore resume fixture-run",
}


URL = "https://github.com/example/fixture/pull/7"
PATTERN = r"^/prs/0/closes/0: .*doesn't match pattern"


def with_(**changes):
    r = copy.deepcopy(DONE)
    r.update(changes)
    return r


def without(key, report=DONE):
    r = copy.deepcopy(report)
    del r[key]
    return r


class ReportCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.out = self.tmp / "report.json"

    def draft(self, report, name="draft.json"):
        p = self.tmp / name
        p.write_text(json.dumps(report) if not isinstance(report, str) else report)
        return p

    def publish(self, report, name="draft.json"):
        env = {**os.environ, "ADMIRAL_REPORT": str(self.out)}
        return subprocess.run(
            [str(IO), "report", str(self.draft(report, name))], env=env, capture_output=True, text=True, check=False
        )

    def check(self, report):
        return subprocess.run(
            [str(CHECK), str(SCHEMA), str(self.draft(report))], capture_output=True, text=True, check=False
        )

    def assertAccepted(self, report):
        r = self.publish(report)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.out.read_text()), report)

    def assertRejected(self, report, field=None):
        r = self.publish(report)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertFalse(self.out.exists(), "an invalid report must publish nothing")
        if field:
            self.assertRegex(r.stderr, field)


class TestValidReports(ReportCase):
    def test_a_done_report_with_pr_objects_and_a_cast_is_published(self):
        self.assertAccepted(DONE)

    def test_a_partial_report_with_resume_is_published(self):
        self.assertAccepted(with_(result="partial", why="Child example/fixture#13 closed by no PR."))

    def test_a_pr_that_closes_nothing_has_an_empty_closes(self):
        self.assertAccepted(with_(prs=[{"url": "https://github.com/example/fixture/pull/9", "closes": []}]))

    def test_a_minimal_report_needs_no_prs_or_cast(self):
        self.assertAccepted({"version": 2, "result": "failed", "why": "Repo gone."})

    def test_an_empty_prs_list_is_valid(self):
        self.assertAccepted(with_(prs=[]))

    def test_an_extra_key_in_a_pr_object_is_accepted(self):
        pr = {"url": "https://github.com/example/fixture/pull/7", "closes": [], "draft": True}
        self.assertAccepted(with_(prs=[pr]))

    def test_an_extra_key_in_a_cast_object_is_accepted(self):
        self.assertAccepted(with_(cast=[{"member": "ada", "role": "implementer", "ad_hoc": False, "model": "x"}]))

    def test_a_codex_resume_line_is_accepted(self):
        self.assertAccepted(with_(resume="$commodore resume fixture.run_2"))

    def test_an_extra_top_level_key_is_accepted(self):
        self.assertAccepted(with_(later="field"))

    def test_a_cross_repo_issue_reference_with_dots_and_hyphens_is_accepted(self):
        self.assertAccepted(with_(prs=[{"url": URL, "closes": ["my-org/my.repo_x#1234"]}]))


class TestInvalidReports(ReportCase):
    def test_version_1_is_rejected(self):
        self.assertRejected(with_(version=1), r"^/version")

    def test_a_prs_string_entry_is_rejected(self):
        self.assertRejected(with_(prs=["https://github.com/example/fixture/pull/7"]), r"^/prs/0: .*not of type object")

    def test_a_pr_object_without_url_is_rejected(self):
        self.assertRejected(with_(prs=[{"closes": []}]), r"/prs/0: missing required property 'url'")

    def test_a_pr_object_without_closes_is_rejected(self):
        self.assertRejected(
            with_(prs=[{"url": "https://github.com/example/fixture/pull/7"}]),
            r"/prs/0: missing required property 'closes'",
        )

    def test_a_non_string_url_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": 7, "closes": []}]), r"^/prs/0/url: .*not of type string")

    def test_closes_that_is_not_a_list_is_rejected(self):
        self.assertRejected(
            with_(prs=[{"url": URL, "closes": "example/fixture#12"}]), r"^/prs/0/closes: .*not of type array"
        )

    def test_closes_with_a_non_string_entry_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": [12]}]), r"^/prs/0/closes/0: .*not of type string")

    def test_a_bare_hash_reference_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": ["#12"]}]), PATTERN)

    def test_a_reference_without_an_owner_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": ["skills#12"]}]), PATTERN)

    def test_a_dot_dot_owner_or_repo_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": ["../..#12"]}]), PATTERN)
        self.assertAccepted(with_(prs=[{"url": URL, "closes": ["example/.github#12"]}]))

    def test_a_reference_with_trailing_text_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": ["example/fixture#12 and more"]}]), PATTERN)

    def test_a_reference_without_a_number_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": ["example/fixture#"]}]), PATTERN)

    def test_a_url_that_is_not_a_github_pull_url_is_rejected(self):
        for url in (
            "u",
            "http://github.com/example/fixture/pull/7",
            "https://evil.example/example/fixture/pull/7",
            "https://github.com/example/fixture/issues/7",
            "https://github.com/example/fixture/pull/7 and more",
            "https://github.com/example/fixture/pull/",
        ):
            with self.subTest(url=url):
                self.assertRejected(with_(prs=[{"url": url, "closes": []}]), r"^/prs/0/url: .*doesn't match pattern")

    def test_a_resume_that_is_not_a_commodore_resume_line_is_rejected(self):
        for text in (
            "/commodore resume fixture-run --autopilot",
            "/commodore resume fixture-run; rm -rf ~",
            "/commodore resume ../x",
            "/commodore resume",
            "commodore resume fixture-run",
            "do something else",
            "/commodore resume fixture-run\nmore",
        ):
            with self.subTest(resume=text):
                self.assertRejected(with_(resume=text), r"^/resume: .*doesn't match pattern")

    def test_a_cast_entry_without_ad_hoc_is_rejected(self):
        self.assertRejected(
            with_(cast=[{"member": "ada", "role": "implementer"}]), r"/cast/0: missing required property 'ad_hoc'"
        )

    def test_the_hyphenated_ad_hoc_key_alone_is_rejected(self):
        self.assertRejected(
            with_(cast=[{"member": "ada", "role": "implementer", "ad-hoc": False}]),
            r"/cast/0: missing required property 'ad_hoc'",
        )

    def test_a_cast_entry_without_member_or_role_is_rejected(self):
        self.assertRejected(
            with_(cast=[{"role": "implementer", "ad_hoc": False}]), r"/cast/0: missing required property 'member'"
        )
        self.assertRejected(
            with_(cast=[{"member": "ada", "ad_hoc": False}]), r"/cast/0: missing required property 'role'"
        )

    def test_a_non_boolean_ad_hoc_is_rejected(self):
        self.assertRejected(
            with_(cast=[{"member": "ada", "role": "implementer", "ad_hoc": "no"}]),
            r"^/cast/0/ad_hoc: .*not of type boolean",
        )

    def test_partial_without_resume_is_rejected(self):
        self.assertRejected(without("resume", with_(result="partial")), r"missing required property 'resume'")

    def test_a_missing_result_or_why_is_rejected(self):
        self.assertRejected(without("result"), r"missing required property 'result'")
        self.assertRejected(without("why"), r"missing required property 'why'")

    def test_an_unknown_result_is_rejected(self):
        self.assertRejected(with_(result="maybe"), r"^/result")

    def test_the_schema_check_alone_agrees(self):
        self.assertEqual(self.check(DONE).returncode, 0)
        self.assertEqual(self.check(with_(version=1)).returncode, 1)


class TestPublishing(ReportCase):
    def test_a_second_publish_replaces_the_first(self):
        self.assertAccepted(DONE)
        second = with_(
            result="partial", why="Second.", prs=[{"url": "https://github.com/example/fixture/pull/9", "closes": []}]
        )
        self.assertAccepted(second)
        self.assertEqual(json.loads(self.out.read_text())["why"], "Second.")

    def test_an_invalid_second_publish_leaves_the_first(self):
        self.assertAccepted(DONE)
        self.assertEqual(self.publish(with_(version=1)).returncode, 2)
        self.assertEqual(json.loads(self.out.read_text()), DONE)

    def test_with_admiral_report_unset_nothing_is_written_and_it_exits_0(self):
        env = {k: v for k, v in os.environ.items() if k != "ADMIRAL_REPORT"}
        r = subprocess.run(
            [str(IO), "report", str(self.draft(DONE))], env=env, capture_output=True, text=True, check=False
        )
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self.out.exists())


class TextCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (SKILL_DIR / "SKILL.md").read_text()
        cls.build = (SKILL_DIR / "references" / "mission-build.md").read_text()
        cls.modes = (SKILL_DIR / "references" / "modes.md").read_text()
        cls.review = (SKILL_DIR / "references" / "mission-review.md").read_text()
        cls.schema = json.loads(SCHEMA.read_text())

    @staticmethod
    def section(text, start, end):
        a = text.index(start)
        return text[a : text.index(end, a + len(start))]

    @staticmethod
    def step(text, n):
        # A step runs from its "<n>. " line through its indented continuation paragraphs.
        m = re.search(rf"^\s*{n}\. .*?(?=^\S|\Z)", text, re.M | re.S)
        assert m, f"no step {n}"
        return m.group(0)


class TestSchemaText(TextCase):
    def test_the_description_no_longer_cites_version_1(self):
        d = self.schema["description"]
        self.assertNotIn("version-1", d)
        self.assertRegex(d, r"[Vv]ersion[- ]2|v2")

    def test_the_schema_has_no_unimplemented_keyword_for_the_checker(self):
        # schema-check exits 2 on a keyword it lacks; the valid-report tests above prove that, this names the cast key.
        self.assertIn("ad_hoc", json.dumps(self.schema))


class TestEndingARunReportV2(TextCase):
    def setUp(self):
        ending = self.section(self.skill, "## Ending a run", "## Marking ready")
        self.ending = ending
        self.step2 = self.step(ending, 2)

    def test_it_says_the_report_is_version_2(self):
        self.assertRegex(self.step2, r"[Vv]ersion 2")
        self.assertNotRegex(self.step2, r"`version` \(1\)")

    def test_prs_are_objects_with_url_and_closes(self):
        self.assertRegex(self.step2, r"`prs`[^.]{0,200}`url`[^.]{0,200}`closes`")
        self.assertNotRegex(self.step2, r"`prs`[^.]*lists? of strings")

    def test_closes_use_owner_repo_hash_references(self):
        self.assertIn("<owner>/<repo>#<n>", self.step2)

    def test_part_of_gives_an_empty_closes(self):
        self.assertRegex(self.step2, r"`Part of`[^.]{0,120}`\[\]`|`\[\]`[^.]{0,120}`Part of`")

    def test_an_existing_pr_run_lists_the_pr_it_works_on_whether_or_not_it_pushed(self):
        self.assertRegex(self.step2, r"`pr-feedback` run[^.;]{0,60}existing PR[^.;]{0,80}the PR the run works on")
        self.assertRegex(self.step2, r"whether or not this run pushed to it")
        self.assertNotRegex(self.step2, r"pr-feedback[^.;]{0,80}the PR it pushed to")

    def test_a_review_run_lists_no_pr(self):
        self.assertRegex(self.step2, r"A `review` run lists no PR")

    def test_cast_lists_each_role_launched_from_cast_json(self):
        self.assertRegex(self.step2, r"`cast`[^.]{0,300}cast\.json")
        for key in ("`member`", "`role`", "`ad_hoc`"):
            self.assertIn(key, self.step2)

    def test_resume_is_also_written_for_an_open_pr(self):
        self.assertRegex(self.step2, r"`resume`[^.]{0,300}open PR|open PR[^.]{0,300}`resume`")
        self.assertIn("moor", self.step2)

    def test_resume_never_carries_autopilot(self):
        self.assertIn("never with `--autopilot`", self.step2)

    def test_the_report_replaces_the_last_one_at_the_end_of_build_and_pr_feedback_runs(self):
        self.assertRegex(
            self.ending, r"Every run publishes one at its end \(the build and every `pr-feedback` run included\)"
        )
        self.assertRegex(self.ending, r"each publish replaces the last")

    def test_the_finished_run_resume_line_stays_for_u3(self):
        self.assertIn("A `/commodore resume` of a finished run says it's finished and stops.", self.ending)

    def test_an_unclosed_child_is_named_in_why_and_ends_partial(self):
        self.assertRegex(self.ending, r"(child|issue)[^.]{0,200}no PR closes[^.]{0,200}`why`")
        self.assertRegex(self.ending, r"no PR closes[^.]{0,300}`partial`|`partial`[^.]{0,300}no PR closes")

    def test_the_prs_closes_match_the_pr_bodies(self):
        self.assertRegex(self.step2, r"PR body|PR bodies")

    def test_no_other_commodore_text_calls_the_report_version_1_or_prs_strings(self):
        offenders = []
        for p in sorted(SKILL_DIR.rglob("*.md")):
            for n, ln in enumerate(p.read_text().splitlines(), 1):
                if "Admiral report" in ln and re.search(r"`version` \(1\)|version 1|`prs`[^.]*lists? of strings", ln):
                    offenders.append(f"{p.relative_to(REPO)}:{n}")
        self.assertEqual(offenders, [])


class TestReviewMissionReport(TextCase):
    def test_review_done_report_says_it_lists_no_pr(self):
        line = next(ln for ln in self.review.splitlines() if "Publish a `done` Admiral report" in ln)
        self.assertRegex(line, r"no `prs`|lists no PR|`prs` (empty|is empty|omitted)")


class TestSlices(TextCase):
    def setUp(self):
        self.table = self.section(self.build, "| The work | Mode | Delivery |", "Pick the mode in phase 1")
        self.step6 = self.step(self.section(self.build, "## Phase 2", "## Unit summary"), 6)
        self.gate = self.section(self.build, "2. Pass the completion gate", "3. Close every teammate")
        self.stack = re.split(r"\n## ", self.modes[self.modes.index("## Stack") :], maxsplit=1)[0]

    def test_the_mode_table_makes_a_slice_one_gh_stack_inside_admiral(self):
        self.assertRegex(self.table, r"(?i)inside Admiral, a slice[^|]{0,100}two or more issues")
        self.assertRegex(
            self.table,
            r"(?i)two or more issues[^|]{0,300}(always|even)[^|]{0,300}gh stack|gh stack[^|]{0,300}two or more issues",
        )

    def test_the_mode_table_says_a_slice_is_a_stack_even_when_the_issues_are_independent(self):
        self.assertRegex(self.table, r"(?i)even (when|if) (the issues|they) (don't|do not) build on each other")

    def test_the_independent_units_row_leaves_slices_out(self):
        row = next(ln for ln in self.table.splitlines() if "independent units" in ln)
        self.assertRegex(row, r"(?i)outside Admiral|not a slice|not inside Admiral")

    def test_modes_stack_names_the_slice_rule(self):
        self.assertRegex(self.stack, r"(?i)slice")
        self.assertRegex(self.stack, r"(?i)inside Admiral")

    def test_closes_rule_each_child_is_closed_by_exactly_one_pr(self):
        self.assertRegex(self.step6, r"(?i)slice")
        self.assertRegex(self.step6, r"exactly one PR")

    def test_closes_rule_other_prs_say_part_of_and_a_pr_may_close_several(self):
        self.assertRegex(self.step6, r"(?i)every other PR[^.]{0,80}`Part of")
        self.assertRegex(self.step6, r"(?i)may close several")
        self.assertRegex(self.step6, r"No child is closed by two PRs")

    def test_the_gate_fails_a_child_no_pr_closes_and_names_it_in_why(self):
        self.assertRegex(self.gate, r"no PR body closes, or that two do")
        self.assertRegex(self.gate, r"`why`")

    def test_the_gate_still_ends_the_run_partial(self):
        self.assertRegex(self.gate, r"the run is partial")

    def test_the_gate_does_not_bring_auto_merge_back(self):
        self.assertNotRegex(self.gate, r"(?i)auto-merge|merge --auto")

    def test_words_used_here_defines_slice_and_not_as_a_unit(self):
        words = self.section(self.skill, "## Words used here", "\n## ")
        line = next((ln for ln in words.splitlines() if "**slice**" in ln.lower()), "")
        self.assertTrue(line, "no 'slice' entry in Words used here")
        self.assertRegex(line, r"(?i)inside Admiral")
        self.assertRegex(line, r"(?i)two or more issues")
        self.assertRegex(line, r"(?i)not a unit")


class TestChangeset(unittest.TestCase):
    def test_the_changeset_exists_and_is_minor(self):
        p = REPO / ".changeset" / "admiral-report-v2-slices.md"
        self.assertTrue(p.is_file(), "no changeset")
        self.assertIn('"jasonbuffin-skills": minor', p.read_text())


if __name__ == "__main__":
    unittest.main()
