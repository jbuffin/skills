"""Tests for `mission.py list` and `mission.py validate` over Markdown mission files."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from crew_world import BASE_PATH

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MISSION_PY = REPO / "skills" / "engineering" / "commodore" / "scripts" / "mission.py"

OK, ERRORS, USAGE = 0, 1, 5
MAX_BYTES = 65536
ROLES = [
    "implementer",
    "test-writer",
    "reviewer",
    "security-reviewer",
    "brief-checker",
    "triager",
    "target-steward",
    "scribe",
    "fix-checker",
]
FIELDS = ["name", "pick-me-when", "source-of-truth", "task-force", "builder", "checker", "stop-rule", "delivery"]
DEFAULTS = {
    "name": "build",
    "pick-me-when": "The engineer wants a change built.",
    "source-of-truth": "The issue's acceptance criteria.",
    "task-force": "[implementer, reviewer]",
    "builder": "implementer",
    "checker": "reviewer",
    "stop-rule": "The PR is open and CI is green.",
    "delivery": "A pull request.",
}
BODY = "## Phase 1\n\nRead the issue.\n\n## Phase 2\n\nBuild it.\n"
KEYS = {"code", "field", "file", "message"}


def mission_text(name="build", body=BODY, extra="", **fields):
    """A mission file; a field set to None is left out, and `extra` is raw frontmatter appended."""
    values = {**DEFAULTS, "name": name, **fields}
    lines = [f"{key}: {values[key]}" for key in FIELDS if values[key] is not None]
    return "---\n" + "\n".join(lines) + "\n" + extra + "---\n\n" + body


class MissionCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="mission-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.tmp = Path(tmp).resolve()
        self.dir = self.tmp / "missions"
        self.dir.mkdir()

    def mission(self, args):
        env = {"PATH": BASE_PATH, "HOME": str(self.tmp), "LANG": "en_US.UTF-8"}
        try:
            proc = subprocess.run(
                [str(MISSION_PY), *[str(a) for a in args]],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                cwd=self.tmp,
            )
        except FileNotFoundError:
            self.fail(f"{MISSION_PY} does not exist")
        self.assertNotIn("Traceback", proc.stderr)
        return proc

    def run_json(self, args, code):
        proc = self.mission(args)
        self.assertEqual(proc.returncode, code, proc.stderr)
        return json.loads(proc.stdout)

    def write(self, name, content, directory=None):
        path = (directory or self.dir) / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="")
        return path

    def listed(self):
        return self.run_json(["list", "--dir", self.dir], OK)

    def one_error(self, args):
        out = self.run_json(args, ERRORS)
        self.assertNotIn("missions", out)
        self.assertEqual(len(out["errors"]), 1, out)
        return out["errors"][0]

    def refused(self, text, name="build.md"):
        """The single error `list` reports for a directory holding just this file."""
        for child in self.dir.iterdir():
            child.unlink()
        self.write(name, text)
        return self.one_error(["list", "--dir", self.dir])


class ListTests(MissionCase):
    def test_lists_a_valid_file_with_every_field_and_its_procedure(self):
        self.write("build.md", mission_text())
        out = self.listed()
        self.assertEqual(out["warnings"], [])
        self.assertEqual(
            out["missions"],
            [
                {
                    "name": "build",
                    "pick-me-when": DEFAULTS["pick-me-when"],
                    "source-of-truth": DEFAULTS["source-of-truth"],
                    "task-force": ["implementer", "reviewer"],
                    "builder": "implementer",
                    "checker": "reviewer",
                    "stop-rule": DEFAULTS["stop-rule"],
                    "delivery": DEFAULTS["delivery"],
                    "file": "build.md",
                    "procedure": BODY.strip("\n"),
                }
            ],
        )

    def test_reads_a_block_list_task_force_and_crlf_line_endings(self):
        text = mission_text(**{"task-force": "\n  - implementer\n  - reviewer"})
        self.write("build.md", text.replace("\n", "\r\n"))
        mission = self.listed()["missions"][0]
        self.assertEqual(mission["task-force"], ["implementer", "reviewer"])
        self.assertNotIn("\r", mission["procedure"])

    def test_engineer_is_accepted_as_a_checker_outside_the_task_force(self):
        fields = {"task-force": "[reviewer]", "builder": "reviewer", "checker": "engineer"}
        self.write("review.md", mission_text("review", **fields))
        mission = self.listed()["missions"][0]
        self.assertEqual(mission["checker"], "engineer")
        self.assertEqual(mission["task-force"], ["reviewer"])

    def test_missions_are_sorted_by_name(self):
        for name in ("review", "build", "pr-feedback"):
            self.write(f"{name}.md", mission_text(name))
        names = [m["name"] for m in self.listed()["missions"]]
        self.assertEqual(names, ["build", "pr-feedback", "review"])

    def test_empty_directory_lists_nothing(self):
        self.assertEqual(self.listed(), {"missions": [], "warnings": []})

    def test_skips_what_is_not_a_regular_markdown_file(self):
        self.write("build.md", mission_text())
        self.write("._review.md", b"\x00\x01 not a mission")
        self.write("notes.txt", "not a mission")
        self.write("UPPER.MD", "not a mission")
        (self.dir / "sub.md").mkdir()
        self.write("inner.md", mission_text("inner"), self.dir / "sub.md")
        (self.dir / "dirlink.md").symlink_to(self.dir / "sub.md")
        (self.dir / "broken.md").symlink_to(self.dir / "nowhere")
        out = self.listed()
        self.assertEqual([m["file"] for m in out["missions"]], ["build.md"])
        self.assertEqual(out["warnings"], [])

    def test_a_symlink_to_a_file_inside_the_directory_is_listed(self):
        self.write("real.md", mission_text("alias"))
        (self.dir / "alias.md").symlink_to(self.dir / "real.md")
        files = [m["file"] for m in self.listed()["missions"]]
        self.assertEqual(files, ["alias.md", "real.md"])

    def test_a_missing_directory_is_one_unreadable_error(self):
        error = self.one_error(["list", "--dir", self.tmp / "absent"])
        self.assertEqual(error["code"], "unreadable")
        self.assertIsNone(error["file"])
        self.assertEqual(set(error), KEYS)

    def test_a_symlink_pointing_outside_the_directory_is_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        target = self.write("build.md", mission_text(), outside)
        (self.dir / "build.md").symlink_to(target)
        error = self.one_error(["list", "--dir", self.dir])
        self.assertEqual((error["code"], error["file"]), ("outside-layer", "build.md"))

    def test_the_default_directory_is_the_missions_directory_next_to_the_scripts(self):
        # Without --dir the call reads skills/engineering/commodore/missions/, which may not exist yet.
        proc = self.mission(["list"])
        self.assertIn(proc.returncode, (OK, ERRORS))
        out = json.loads(proc.stdout)
        if proc.returncode == OK:
            self.assertIn("missions", out)
        else:
            self.assertEqual([e["code"] for e in out["errors"]], ["unreadable"])


class ValidateTests(MissionCase):
    def test_validates_a_valid_file(self):
        path = self.write("build.md", mission_text())
        out = self.run_json(["validate", path], OK)
        self.assertEqual(out["warnings"], [])
        self.assertEqual([(m["name"], m["file"]) for m in out["missions"]], [("build", "build.md")])
        self.assertEqual(out["missions"][0]["procedure"], BODY.strip("\n"))

    def test_validates_several_files_and_sorts_missions_by_name(self):
        paths = [self.write(f"{n}.md", mission_text(n)) for n in ("review", "build")]
        out = self.run_json(["validate", *paths], OK)
        self.assertEqual([m["name"] for m in out["missions"]], ["build", "review"])

    def test_one_bad_file_makes_the_whole_call_an_error(self):
        good = self.write("build.md", mission_text())
        bad = self.write("review.md", mission_text("review", checker=None))
        out = self.run_json(["validate", good, bad], ERRORS)
        self.assertNotIn("missions", out)
        self.assertEqual([(e["file"], e["code"]) for e in out["errors"]], [("review.md", "no-checker")])

    def test_a_missing_file_is_unreadable(self):
        error = self.one_error(["validate", self.dir / "absent.md"])
        self.assertEqual((error["code"], error["file"]), ("unreadable", "absent.md"))

    def test_a_symlink_outside_the_directory_is_not_refused(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        target = self.write("build.md", mission_text(), outside)
        link = self.dir / "build.md"
        link.symlink_to(target)
        out = self.run_json(["validate", link], OK)
        self.assertEqual(out["missions"][0]["name"], "build")


class CheckerTests(MissionCase):
    def test_no_checker_is_refused(self):
        for checker in (None, "", "   ", " \t"):
            with self.subTest(checker=checker):
                error = self.refused(mission_text(checker=checker))
                self.assertEqual((error["code"], error["file"]), ("no-checker", "build.md"))
                self.assertEqual(error["field"], "checker")

    def test_checker_equal_to_builder_is_refused(self):
        error = self.refused(mission_text(builder="implementer", checker="implementer"))
        self.assertEqual(error["code"], "checker-is-builder")

    def test_the_builder_can_be_the_engineer_only_as_a_checker(self):
        error = self.refused(mission_text(builder="engineer", checker="reviewer"))
        self.assertEqual((error["code"], error["field"]), ("bad-field", "builder"))

    def test_builder_or_checker_outside_the_task_force_is_refused(self):
        cases = [
            ("builder", mission_text(builder="scribe")),
            ("checker", mission_text(checker="scribe")),
            ("builder", mission_text(builder="wizard")),
            ("checker", mission_text(checker="wizard")),
            ("checker", mission_text(checker="Engineer")),
        ]
        for field, text in cases:
            with self.subTest(field=field, text=text):
                error = self.refused(text)
                self.assertEqual((error["code"], error["field"]), ("bad-field", field))

    def test_a_list_checker_is_refused(self):
        error = self.refused(mission_text(checker="[reviewer]"))
        self.assertEqual((error["code"], error["field"]), ("bad-field", "checker"))


class RequiredFieldTests(MissionCase):
    def test_each_missing_or_blank_required_field_is_missing_field(self):
        for field in FIELDS:
            if field == "checker":
                continue
            for value in (None, "", "   ", " \t"):
                with self.subTest(field=field, value=value):
                    error = self.refused(mission_text(**{field: value}))
                    self.assertEqual((error["code"], error["field"]), ("missing-field", field))

    def test_a_list_or_boolean_in_a_string_field_is_bad_field(self):
        for field in ("pick-me-when", "source-of-truth", "stop-rule", "delivery"):
            for value in ("[a, b]", "true", "false"):
                with self.subTest(field=field, value=value):
                    error = self.refused(mission_text(**{field: value}))
                    self.assertEqual((error["code"], error["field"]), ("bad-field", field))

    def test_a_missing_body_is_missing_field_body(self):
        for body in ("", "\n\n  \t\n"):
            with self.subTest(body=body):
                error = self.refused(mission_text(body=body))
                self.assertEqual((error["code"], error["field"]), ("missing-field", "body"))

    def test_a_bad_name_is_refused(self):
        error = self.refused(mission_text(name="Build"), "Build.md")
        self.assertEqual((error["code"], error["field"]), ("bad-name", "name"))

    def test_a_name_that_differs_from_the_file_name_is_refused(self):
        error = self.refused(mission_text(name="review"), "build.md")
        self.assertEqual((error["code"], error["field"]), ("name-mismatch", "name"))

    def test_a_name_checked_before_the_other_fields(self):
        error = self.refused(mission_text(name="review", checker=None, delivery=None), "build.md")
        self.assertEqual(error["code"], "name-mismatch")

    def test_only_the_first_failing_field_in_table_order_is_reported(self):
        error = self.refused(mission_text(**{"source-of-truth": None, "stop-rule": None, "checker": None}))
        self.assertEqual((error["code"], error["field"]), ("missing-field", "source-of-truth"))


class TaskForceTests(MissionCase):
    def test_a_task_force_that_is_not_a_list_of_distinct_roles_is_bad_field(self):
        cases = {
            "string": "implementer",
            "boolean": "true",
            "empty list": "[]",
            "repeat": "[implementer, reviewer, implementer]",
            "not a role": "[implementer, wizard]",
            "engineer": "[implementer, engineer]",
        }
        for label, value in cases.items():
            with self.subTest(label):
                error = self.refused(mission_text(**{"task-force": value}))
                self.assertEqual((error["code"], error["field"]), ("bad-field", "task-force"))

    def test_every_role_is_accepted(self):
        text = mission_text(**{"task-force": "[" + ", ".join(ROLES) + "]"})
        self.write("build.md", text)
        self.assertEqual(self.listed()["missions"][0]["task-force"], ROLES)


class WarningTests(MissionCase):
    def test_an_unknown_key_warns_and_the_mission_still_lists(self):
        self.write("build.md", mission_text(extra="owner: nobody\n"))
        out = self.listed()
        self.assertEqual([m["name"] for m in out["missions"]], ["build"])
        self.assertEqual(
            [(w["code"], w["field"], w["file"]) for w in out["warnings"]], [("unknown-field", "owner", "build.md")]
        )
        self.assertEqual(set(out["warnings"][0]), KEYS)

    def test_warnings_are_sorted_by_file_then_field(self):
        self.write("review.md", mission_text("review", extra="beta: 1\n"))
        self.write("build.md", mission_text("build", extra="zeta: 1\nalpha: 1\n"))
        out = self.listed()
        self.assertEqual(
            [(w["file"], w["field"]) for w in out["warnings"]],
            [("build.md", "alpha"), ("build.md", "zeta"), ("review.md", "beta")],
        )

    def test_warnings_are_dropped_when_any_file_has_an_error(self):
        self.write("build.md", mission_text(extra="owner: nobody\n"))
        self.write("review.md", mission_text("review", checker=None))
        out = self.run_json(["list", "--dir", self.dir], ERRORS)
        self.assertEqual(out["warnings"], [])
        self.assertEqual([e["file"] for e in out["errors"]], ["review.md"])

    def test_a_file_with_an_error_gets_no_warnings(self):
        error_only = mission_text(checker=None, extra="owner: nobody\n")
        self.write("build.md", error_only)
        out = self.run_json(["list", "--dir", self.dir], ERRORS)
        self.assertEqual(out["warnings"], [])


class ErrorOutputTests(MissionCase):
    def test_errors_are_sorted_by_file_in_byte_order(self):
        for name in ("review", "build", "pr-feedback"):
            self.write(f"{name}.md", mission_text(name, checker=None))
        out = self.run_json(["list", "--dir", self.dir], ERRORS)
        self.assertEqual([e["file"] for e in out["errors"]], ["build.md", "pr-feedback.md", "review.md"])
        self.assertTrue(all(set(e) == KEYS for e in out["errors"]))

    def test_validate_errors_are_sorted_by_file_not_by_argument_order(self):
        out = self.run_json(["validate", self.dir / "z.md", self.dir / "a.md"], ERRORS)
        self.assertEqual([e["file"] for e in out["errors"]], ["a.md", "z.md"])


class UnreadableFileTests(MissionCase):
    def test_bad_utf8_is_refused(self):
        error = self.refused(mission_text().encode("utf-8") + b"\xff\xfe\n")
        self.assertEqual(error["code"], "bad-frontmatter")

    def test_a_byte_order_mark_is_refused(self):
        error = self.refused(b"\xef\xbb\xbf" + mission_text().encode("utf-8"))
        self.assertEqual(error["code"], "bad-frontmatter")

    def test_a_file_over_the_size_cap_is_refused(self):
        error = self.refused(mission_text(body="x" * MAX_BYTES))
        self.assertEqual((error["code"], error["file"]), ("too-large", "build.md"))

    def test_a_file_of_exactly_the_size_cap_is_read(self):
        head = mission_text(body="")
        filler = "x" * (MAX_BYTES - len(head.encode("utf-8")))
        text = head + filler
        self.assertEqual(len(text.encode("utf-8")), MAX_BYTES)
        self.write("build.md", text)
        self.assertEqual(self.listed()["missions"][0]["procedure"], filler)

    def test_frontmatter_that_does_not_parse_is_refused(self):
        cases = {
            "no opening fence": "name: build\n---\nbody\n",
            "no closing fence": "---\nname: build\nbody\n",
            "repeated key": mission_text(extra="delivery: again\n"),
            "unclosed quote": mission_text(delivery='"open'),
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.assertEqual(self.refused(text)["code"], "bad-frontmatter")


class NoExecutionTests(MissionCase):
    def test_python_and_shell_text_in_a_mission_file_is_never_run(self):
        marker = self.tmp / "marker"
        py = f"__import__('pathlib').Path({str(marker)!r}).touch()"
        sh = f"touch {marker}"
        hostile_pick = f"$(touch {marker}) `touch {marker}` ; touch {marker}"
        body = f"```python\n{py}\n```\n\n```sh\n{sh}\n```\n\n$({sh})\n`{sh}`\n"
        self.write(
            "build.md",
            mission_text(
                **{
                    "pick-me-when": hostile_pick,
                    "stop-rule": py,
                    "delivery": f"!!python/object/apply:os.system [{sh!r}]",
                },
                body=body,
            ),
        )
        out = self.listed()
        mission = out["missions"][0]
        self.assertEqual(mission["pick-me-when"], hostile_pick)
        self.assertEqual(mission["stop-rule"], py)
        self.assertEqual(mission["procedure"], body.strip("\n"))
        self.assertFalse(marker.exists())

    def test_validate_never_runs_a_mission_file_either(self):
        marker = self.tmp / "marker"
        sh = f"touch {marker}"
        path = self.write("build.md", mission_text(**{"source-of-truth": f"$({sh})"}, body=f"{sh}\n"))
        out = self.run_json(["validate", path], OK)
        self.assertEqual(out["missions"][0]["source-of-truth"], f"$({sh})")
        self.assertFalse(marker.exists())

    def test_a_python_module_beside_the_missions_is_never_imported(self):
        marker = self.tmp / "marker"
        for name in ("json.py", "os.py", "sitecustomize.py", "build.py"):
            self.write(name, f"import pathlib\npathlib.Path({str(marker)!r}).touch()\n")
        self.write("build.md", mission_text())
        self.listed()
        self.assertFalse(marker.exists())


class UsageTests(MissionCase):
    def test_a_bad_call_prints_usage_and_exits_5(self):
        calls = [
            [],
            ["bogus"],
            ["list", "--bogus"],
            ["list", "--dir"],
            ["list", "stray"],
            ["validate"],
            ["validate", "--bogus", "x.md"],
        ]
        for args in calls:
            with self.subTest(args=args):
                proc = self.mission(args)
                self.assertEqual(proc.returncode, USAGE, proc.stderr)
                self.assertTrue(proc.stderr.strip())
                self.assertEqual(proc.stdout, "")


if __name__ == "__main__":
    unittest.main()
