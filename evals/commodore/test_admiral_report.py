"""admiral-io.sh report publishes a version 2 Admiral report only when it fits the schema."""

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

    def assertRejected(self, report, pointer):
        r = self.publish(report)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertFalse(self.out.exists(), "an invalid report must publish nothing")
        self.assertIn(pointer, r.stderr)


class TestValidReports(ReportCase):
    def test_a_done_report_with_pr_objects_and_a_cast_is_published(self):
        self.assertAccepted(DONE)

    def test_a_partial_report_with_resume_is_published(self):
        self.assertAccepted(with_(result="partial", why="Child example/fixture#13 closed by no PR."))

    def test_a_minimal_report_needs_no_prs_or_cast(self):
        self.assertAccepted({"version": 2, "result": "failed", "why": "Repo gone."})

    def test_extra_keys_are_accepted(self):
        pr = {"url": URL, "closes": [], "draft": True}
        self.assertAccepted(with_(prs=[pr], later="field"))

    def test_a_codex_resume_line_is_accepted(self):
        self.assertAccepted(with_(resume="$commodore resume fixture.run_2"))

    def test_an_issue_reference_with_dots_hyphens_and_a_dot_repo_is_accepted(self):
        self.assertAccepted(with_(prs=[{"url": URL, "closes": ["my-org/my.repo_x#1234", "example/.github#12"]}]))


class TestInvalidReports(ReportCase):
    def test_version_1_is_rejected(self):
        self.assertRejected(with_(version=1), "/version")

    def test_a_prs_string_entry_is_rejected(self):
        self.assertRejected(with_(prs=[URL]), "/prs/0")

    def test_a_pr_object_without_closes_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL}]), "/prs/0")

    def test_a_url_that_is_not_a_github_pull_url_is_rejected(self):
        url = "https://github.com/example/fixture/issues/7"
        self.assertRejected(with_(prs=[{"url": url, "closes": []}]), "/prs/0/url")

    def test_a_reference_without_an_owner_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": ["#12"]}]), "/prs/0/closes/0")

    def test_a_dot_dot_owner_or_repo_is_rejected(self):
        self.assertRejected(with_(prs=[{"url": URL, "closes": ["../..#12"]}]), "/prs/0/closes/0")

    def test_a_resume_with_autopilot_is_rejected(self):
        self.assertRejected(with_(resume="/commodore resume fixture-run --autopilot"), "/resume")

    def test_a_resume_with_a_dot_dot_run_name_is_rejected(self):
        self.assertRejected(with_(resume="/commodore resume ../x"), "/resume")

    def test_a_cast_entry_without_ad_hoc_is_rejected(self):
        self.assertRejected(with_(cast=[{"member": "ada", "role": "implementer"}]), "/cast/0")

    def test_partial_without_resume_is_rejected(self):
        self.assertRejected(without("resume", with_(result="partial")), "resume")

    def test_an_unknown_result_is_rejected(self):
        self.assertRejected(with_(result="maybe"), "/result")


class TestPublishing(ReportCase):
    def test_a_second_publish_replaces_the_first(self):
        self.assertAccepted(DONE)
        self.assertAccepted(with_(result="partial", why="Second.", prs=[]))

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
