"""Tests for `admiral-io.sh report`: which version-2 reports it publishes to ADMIRAL_REPORT and which it refuses."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILL_DIR = REPO / "skills" / "engineering" / "commodore"
SCRIPTS = SKILL_DIR / "scripts"
IO = SCRIPTS / "admiral-io.sh"


def ref(repo, n):
    """An issue reference as the report writes it: `<owner>/<repo>#<n>`."""
    return f"{repo}#{n}"


DONE = {
    "version": 2,
    "result": "done",
    "why": "Built and shipped.",
    "prs": [
        {"url": "https://github.com/example/fixture/pull/7", "closes": [ref("example/fixture", 12)]},
        {"url": "https://github.com/example/fixture/pull/8", "closes": []},
    ],
    "cast": [
        {"member": "ada", "role": "implementer", "ad_hoc": False},
        {"member": "tmp-scribe", "role": "scribe", "ad_hoc": True},
    ],
    "resume": "/commodore resume fixture-run",
}
URL = "https://github.com/example/fixture/pull/7"
NOTE = {
    "member": "ada",
    "role": "implementer",
    "scope": "repo",
    "repo": "example/fixture",
    "note": "Run the tests with `make test`.",
    "replaces": None,
    "ad-hoc": False,
}
PATTERN = r"^/prs/0/closes/0: .*doesn't match pattern"
KEEP = {
    "name": "docs-audit",
    "scope": "fleet",
    "repo": None,
    "text": "---\nname: docs-audit\n---\n\nAudit the docs.\n",
}
MAX_TEXT = 65536


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
        self.assertAccepted(with_(result="partial", why="A child is closed by no PR."))

    def test_a_minimal_report_needs_no_prs_or_cast(self):
        self.assertAccepted({"version": 2, "result": "failed", "why": "Repo gone."})

    def test_an_extra_top_level_key_is_accepted(self):
        self.assertAccepted(with_(later="field"))

    def test_a_codex_resume_line_is_accepted(self):
        self.assertAccepted(with_(resume="$commodore resume fixture.run_2"))

    def test_a_cross_repo_issue_reference_with_dots_and_hyphens_is_accepted(self):
        closes = [ref("my-org/my.repo_x", 1234), ref("example/.github", 12)]
        self.assertAccepted(with_(prs=[{"url": URL, "closes": closes}]))

    def test_a_report_with_a_crew_note_proposal_is_published(self):
        self.assertAccepted(with_(notes=[NOTE, {**NOTE, "scope": "fleet", "repo": None}]))

    def test_a_report_naming_an_ad_hoc_mission_is_published(self):
        self.assertAccepted(with_(mission={"name": "docs-audit", "ad_hoc": True}))


class TestKeepProposals(ReportCase):
    def test_a_fleet_and_a_repo_keep_proposal_are_published(self):
        repo_item = {**KEEP, "scope": "repo", "repo": "example/fixture"}
        self.assertAccepted(with_(missions=[KEEP]))
        self.assertAccepted(with_(missions=[repo_item]))
        self.assertAccepted(with_(missions=[{**KEEP, "repo": "example/fixture"}]))

    def test_a_report_without_missions_is_still_published(self):
        self.assertAccepted(DONE)

    def test_text_of_exactly_the_limit_is_published(self):
        self.assertAccepted(with_(missions=[{**KEEP, "text": "a" * MAX_TEXT}]))

    def test_the_limit_counts_characters_not_bytes(self):
        self.assertAccepted(with_(missions=[{**KEEP, "text": "é" * MAX_TEXT}]))
        self.assertAccepted(with_(missions=[{**KEEP, "text": "\U0001f600" * MAX_TEXT}]))

    def test_text_over_the_limit_is_rejected(self):
        self.assertRejected(with_(missions=[{**KEEP, "text": "a" * (MAX_TEXT + 1)}]), r"^/missions/0/text")
        self.assertRejected(with_(missions=[{**KEEP, "text": "é" * (MAX_TEXT + 1)}]), r"^/missions/0/text")

    def test_empty_text_is_rejected(self):
        self.assertRejected(with_(missions=[{**KEEP, "text": ""}]), r"^/missions/0/text")

    def test_a_keep_proposal_missing_a_field_is_rejected(self):
        for key in KEEP:
            with self.subTest(key=key):
                item = {k: v for k, v in KEEP.items() if k != key}
                self.assertRejected(with_(missions=[item]), rf"^/missions/0: missing required property '{key}'")

    def test_a_keep_proposal_with_an_extra_field_is_rejected(self):
        self.assertRejected(with_(missions=[{**KEEP, "layer": "repo"}]), r"^/missions/0")

    def test_an_unknown_scope_is_rejected(self):
        for scope in ("user-global", "everywhere"):
            with self.subTest(scope=scope):
                self.assertRejected(with_(missions=[{**KEEP, "scope": scope}]), r"^/missions/0/scope")

    def test_a_bad_name_is_rejected(self):
        for name in ("", "Docs Audit", "docs_audit", "../x", "-docs", "a" * 65):
            with self.subTest(name=name):
                self.assertRejected(with_(missions=[{**KEEP, "name": name}]), r"^/missions/0/name")

    def test_a_repo_keep_proposal_without_an_owner_slash_repo_is_rejected(self):
        for repo in (None, "fixture"):
            with self.subTest(repo=repo):
                self.assertRejected(with_(missions=[{**KEEP, "scope": "repo", "repo": repo}]), r"^/missions/0/repo")

    def test_missions_that_is_not_an_array_of_objects_is_rejected(self):
        self.assertRejected(with_(missions=KEEP), r"^/missions")
        self.assertRejected(with_(missions=["docs-audit"]), r"^/missions/0")


class TestInvalidReports(ReportCase):
    def test_version_1_is_rejected(self):
        self.assertRejected(with_(version=1), r"^/version")

    def test_a_prs_string_entry_is_rejected(self):
        self.assertRejected(with_(prs=[URL]), r"^/prs/0: .*not of type object")

    def test_a_pr_object_without_closes_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL}]), r"/prs/0: missing required property 'closes'")

    def test_a_bare_hash_reference_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": [ref("", 12)]}]), PATTERN)

    def test_a_dot_dot_owner_or_repo_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": [ref("../..", 12)]}]), PATTERN)

    def test_a_url_that_is_not_a_github_pull_url_is_rejected(self):
        for url in ("https://evil.example/example/fixture/pull/7", "https://github.com/example/fixture/issues/7"):
            with self.subTest(url=url):
                self.assertRejected(with_(prs=[{"url": url, "closes": []}]), r"^/prs/0/url: .*doesn't match pattern")

    def test_a_resume_that_is_not_a_commodore_resume_line_is_rejected(self):
        for text in ("/commodore resume fixture-run --autopilot", "/commodore resume fixture-run; rm -rf ~"):
            with self.subTest(resume=text):
                self.assertRejected(with_(resume=text), r"^/resume: .*doesn't match pattern")

    def test_a_cast_entry_without_ad_hoc_is_rejected(self):
        self.assertRejected(
            with_(cast=[{"member": "ada", "role": "implementer"}]), r"/cast/0: missing required property 'ad_hoc'"
        )

    def test_partial_without_resume_is_rejected(self):
        self.assertRejected(without("resume", with_(result="partial")), r"missing required property 'resume'")

    def test_a_missing_result_is_rejected(self):
        self.assertRejected(without("result"), r"missing required property 'result'")

    def test_an_unknown_result_is_rejected(self):
        self.assertRejected(with_(result="maybe"), r"^/result")

    def test_a_note_proposal_missing_a_key_is_rejected(self):
        item = {k: v for k, v in NOTE.items() if k != "replaces"}
        self.assertRejected(with_(notes=[item]), r"^/notes/0: missing required property 'replaces'")

    def test_a_note_proposal_with_an_extra_key_is_rejected(self):
        self.assertRejected(with_(notes=[{**NOTE, "why": "x"}]), r"^/notes/0")

    def test_a_repo_note_proposal_without_an_owner_slash_repo_is_rejected(self):
        for repo in (None, "fixture"):
            with self.subTest(repo=repo):
                self.assertRejected(with_(notes=[{**NOTE, "repo": repo}]), r"^/notes/0/repo")

    def test_a_mission_without_a_name_is_rejected(self):
        self.assertRejected(with_(mission={"ad_hoc": True}), r"^/mission: missing required property 'name'")

    def test_a_mission_with_a_non_boolean_ad_hoc_is_rejected(self):
        self.assertRejected(with_(mission={"name": "build", "ad_hoc": "yes"}), r"^/mission/ad_hoc")

    def test_a_mission_with_an_empty_name_is_rejected(self):
        self.assertRejected(with_(mission={"name": "", "ad_hoc": False}), r"^/mission/name")

    def test_a_mission_with_an_extra_key_is_rejected(self):
        self.assertRejected(with_(mission={"name": "build", "ad_hoc": False, "file": "build.md"}), r"^/mission")

    def test_a_mission_that_is_not_an_object_is_rejected(self):
        self.assertRejected(with_(mission="build"), r"^/mission: .*not of type object")


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


if __name__ == "__main__":
    unittest.main()
