"""Tests for setup-commodore's `convert-roles.py` (issue #199, unit u2): a `roles.json` becomes crew member files.

Seam: `convert-roles.py <roles.json> <crew-dir>` as a subprocess (stdout lines, stderr warnings, exit code, the files
it writes), and `crew.py resolve --layer repo=<crew-dir>` over what it wrote for the round trip. The expected skills and
instructions are written out by hand from the old resolver's rules (u2 spec section 3 and the rulings in section 8): one
leading `/` or `$` stripped, a name the old pattern rejects dropped, instructions verbatim. `role-skills.sh` is deleted
in this unit, so no expected value comes from running it.

Run from the repo root: python3 -m unittest discover -s evals/commodore -p 'test_convert_roles.py' -v
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CONVERT = REPO / "skills" / "engineering" / "setup-commodore" / "scripts" / "convert-roles.py"
CREW_PY = REPO / "skills" / "engineering" / "commodore" / "scripts" / "crew.py"
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"

# (case, roles.json entry for `role`, skills after the old resolver's filtering and u1's dedupe, instructions after
# trimming leading and trailing blank lines)
ROUND_TRIPS = [
    (
        "one skill and instructions",
        "reviewer",
        {"skills": ["code-review"], "instructions": "Run code-review.\nThen summarise."},
        ["code-review"],
        "Run code-review.\nThen summarise.",
    ),
    ("slash and dollar prefixes", "implementer", {"skills": ["/tdd", "$simplify"]}, ["tdd", "simplify"], ""),
    ("a skill given as a string", "scribe", {"skills": "unslop"}, ["unslop"], ""),
    ("a prefixed string skill", "scribe", {"skills": "/unslop", "instructions": "Polish."}, ["unslop"], "Polish."),
    (
        "plugin and dotted names",
        "test-writer",
        {"skills": ["mattpocock-skills:tdd", "v1.2-x"]},
        ["mattpocock-skills:tdd", "v1.2-x"],
        "",
    ),
    ("instructions only", "triager", {"instructions": "Be careful."}, [], "Be careful."),
    (
        "an empty skills list",
        "target-steward",
        {"skills": [], "instructions": "Check the target."},
        [],
        "Check the target.",
    ),
    (
        "duplicate skills are written once",
        "brief-checker",
        {"skills": ["tdd", "/tdd", "simplify"]},
        ["tdd", "simplify"],
        "",
    ),
    (
        "outer blank lines are the allowed difference",
        "reviewer",
        {"skills": ["a-skill"], "instructions": "\n\nBody.\n\n"},
        ["a-skill"],
        "Body.",
    ),
    ("whitespace-only instructions", "reviewer", {"instructions": "  \n \t\n"}, [], ""),
    (
        "a markdown-looking body",
        "security-reviewer",
        {
            "skills": ["security-review"],
            "instructions": "Step 1: run `x`.\n---\n# Not a heading\ncol | col\n\tindented\nüñí ✓",
        },
        ["security-review"],
        "Step 1: run `x`.\n---\n# Not a heading\ncol | col\n\tindented\nüñí ✓",
    ),
    (
        "a body that starts with a frontmatter fence",
        "scribe",
        {"instructions": "---\nname: evil\nrole: reviewer\n---\nmore"},
        [],
        "---\nname: evil\nrole: reviewer\n---\nmore",
    ),
    (
        "a leading-space first line",
        "reviewer",
        {"instructions": "  indented first\nsecond"},
        [],
        "  indented first\nsecond",
    ),
    ("null skills mean no skills", "reviewer", {"skills": None, "instructions": "keep me"}, [], "keep me"),
    ("false skills mean no skills", "reviewer", {"skills": False, "instructions": "keep me"}, [], "keep me"),
    ("null instructions are absent", "reviewer", {"skills": ["a-skill"], "instructions": None}, ["a-skill"], ""),
    ("blank lines inside the body stay", "reviewer", {"instructions": "one\n\n\ntwo"}, [], "one\n\n\ntwo"),
]


class ConvertCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="convert-roles-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.root = Path(tmp).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.roles_json = self.project / "roles.json"
        self.crew = self.root / "out" / "crew"

    def env(self):
        return {"PATH": BASE_PATH, "HOME": str(self.root), "LANG": "en_US.UTF-8"}

    def write(self, data, path=None):
        (path or self.roles_json).write_text(data if isinstance(data, str) else json.dumps(data))

    def convert(self, *args):
        args = args or (self.roles_json, self.crew)
        return subprocess.run(
            [str(CONVERT), *[str(a) for a in args]],
            env=self.env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def resolve(self):
        done = subprocess.run(
            [str(CREW_PY), "resolve", "--layer", f"repo={self.crew}"],
            env=self.env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def written(self):
        return sorted(p.name for p in self.crew.glob("*")) if self.crew.exists() else []

    def warns(self, done, word):
        return [ln for ln in done.stderr.splitlines() if ln.startswith("WARN") and word in ln]

    def tree(self):
        # Apple's python3 shim writes its bytecode cache under $HOME/Library even for a script that imports nothing.
        paths = (p.relative_to(self.root) for p in self.root.rglob("*"))
        return sorted(str(p) for p in paths if p.parts[0] != "Library")


class TestRoundTrip(ConvertCase):
    def test_each_case_resolves_to_the_same_skills_and_instructions(self):
        for case, role, entry, skills, instructions in ROUND_TRIPS:
            with self.subTest(case=case):
                shutil.rmtree(self.crew, ignore_errors=True)
                self.write({role: entry})
                done = self.convert()
                self.assertEqual(done.returncode, 0, done.stderr)
                result = self.resolve()
                self.assertEqual(result["warnings"], [])
                members = {m["name"]: m for m in result["members"]}
                self.assertEqual(list(members), [role])
                member = members[role]
                self.assertEqual(member["role"], role)
                self.assertEqual(member["skills"], skills)
                self.assertEqual(member["instructions"], instructions)
                self.assertEqual(member["layer"], "repo")
                self.assertIsNone(member["model"])
                self.assertIsNone(member["harness"])
                self.assertIsNone(member["based-on"])

    def test_every_role_in_one_file_round_trips(self):
        roles = {
            "implementer": ["tdd"],
            "test-writer": ["tdd", "testing-strategy"],
            "reviewer": ["code-review"],
            "security-reviewer": ["security-review"],
            "brief-checker": [],
            "triager": ["/triage"],
            "target-steward": ["$target-evaluation"],
            "scribe": ["unslop"],
        }
        self.write({r: {"skills": s, "instructions": f"Instructions for {r}."} for r, s in roles.items()})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.written(), sorted(f"{r}.md" for r in roles))
        members = {m["name"]: m for m in self.resolve()["members"]}
        self.assertEqual(sorted(members), sorted(roles))
        for role, skills in roles.items():
            self.assertEqual(members[role]["skills"], [s.lstrip("/$") for s in skills], role)
            self.assertEqual(members[role]["instructions"], f"Instructions for {role}.")

    def test_a_member_replaces_the_built_in_of_the_same_name_whole(self):
        self.write({"reviewer": {"skills": ["code-review"], "instructions": "Mine."}})
        self.convert()
        done = subprocess.run(
            [
                str(CREW_PY),
                "resolve",
                "--layer",
                f"built-in={REPO / 'skills' / 'engineering' / 'commodore' / 'crew'}",
                "--layer",
                f"repo={self.crew}",
            ],
            env=self.env(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        reviewers = [m for m in json.loads(done.stdout)["members"] if m["name"] == "reviewer"]
        self.assertEqual(len(reviewers), 1)
        self.assertEqual((reviewers[0]["layer"], reviewers[0]["instructions"]), ("repo", "Mine."))

    def test_the_file_is_the_documented_shape(self):
        self.write({"reviewer": {"skills": ["/code-review", "simplify"], "instructions": "Do it.\n"}})
        self.convert()
        text = (self.crew / "reviewer.md").read_text()
        self.assertTrue(text.startswith("---\nname: reviewer\nrole: reviewer\n"), text)
        self.assertIn("pick-me-when: Converted from project/roles.json.\n", text)
        self.assertRegex(text, r"(?m)^skills: \[code-review, simplify\]$")
        self.assertNotRegex(text, r"(?m)^(model|harness|based-on):")
        self.assertTrue(text.endswith("---\n\nDo it.\n"), text)
        self.assertEqual(self.resolve()["members"][0]["pick-me-when"], "Converted from project/roles.json.")

    def test_a_non_ascii_body_is_written_as_utf_8(self):
        self.write({"scribe": {"instructions": "Écris en français — avec soin ✓"}})
        self.convert()
        self.assertEqual(
            (self.crew / "scribe.md").read_bytes().decode("utf-8").splitlines()[-1], "Écris en français — avec soin ✓"
        )


class TestOutput(ConvertCase):
    def test_prints_one_wrote_line_per_file_then_the_next_line(self):
        self.write({"reviewer": {"skills": ["a-skill"]}, "scribe": {"instructions": "x"}})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertEqual(set(lines[:-1]), {f"WROTE {self.crew / 'reviewer.md'}", f"WROTE {self.crew / 'scribe.md'}"})
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1], f"NEXT delete {self.roles_json} once the members resolve")

    def test_creates_the_crew_directory_and_writes_only_there(self):
        self.write({"reviewer": {"skills": ["a-skill"]}})
        before = set(self.tree())
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        added = set(self.tree()) - before
        self.assertEqual(added, {"out", "out/crew", "out/crew/reviewer.md"})

    def test_writes_into_an_existing_crew_directory_and_keeps_its_other_files(self):
        self.crew.mkdir(parents=True)
        (self.crew / "other.md").write_text("keep me\n")
        self.write({"reviewer": {"skills": ["a-skill"]}})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.crew / "other.md").read_text(), "keep me\n")
        self.assertEqual(self.written(), ["other.md", "reviewer.md"])

    def test_never_deletes_or_changes_roles_json(self):
        self.write({"reviewer": {"skills": ["a-skill"]}})
        before = self.roles_json.read_bytes()
        self.convert()
        self.assertEqual(self.roles_json.read_bytes(), before)

    def test_the_script_is_executable(self):
        self.assertTrue(os.access(CONVERT, os.X_OK))


class TestSkipped(ConvertCase):
    def test_an_unknown_role_is_skipped_with_a_warning(self):
        self.write({"captain": {"skills": ["a-skill"]}, "reviewer": {"skills": ["b-skill"]}})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.written(), ["reviewer.md"])
        self.assertEqual(len(self.warns(done, "captain")), 1, done.stderr)

    def test_the_fix_checker_entry_is_skipped_with_a_warning(self):
        self.write({"fix-checker": {"skills": ["a-skill"], "instructions": "x"}, "reviewer": {"skills": ["b-skill"]}})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.written(), ["reviewer.md"])
        self.assertEqual(len(self.warns(done, "fix-checker")), 1, done.stderr)

    def test_an_entry_that_is_not_an_object_is_skipped_with_a_warning(self):
        self.write(
            {"reviewer": "code-review", "scribe": ["x"], "triager": None, "implementer": {"skills": ["a-skill"]}}
        )
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.written(), ["implementer.md"])
        for role in ("reviewer", "scribe", "triager"):
            self.assertEqual(len(self.warns(done, role)), 1, (role, done.stderr))

    def test_an_unknown_key_is_dropped_with_a_warning_and_the_entry_kept(self):
        self.write({"reviewer": {"skills": ["a-skill"], "instructions": "Go.", "color": "red"}})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.warns(done, "color")), 1, done.stderr)
        self.assertNotIn("color", (self.crew / "reviewer.md").read_text())
        member = self.resolve()["members"][0]
        self.assertEqual((member["skills"], member["instructions"]), (["a-skill"], "Go."))

    def test_skills_that_are_neither_a_list_nor_a_string_skip_the_entry(self):
        for bad in (5, {"a": 1}, True):
            with self.subTest(skills=bad):
                shutil.rmtree(self.crew, ignore_errors=True)
                self.write({"reviewer": {"skills": bad, "instructions": "x"}, "scribe": {"skills": ["a-skill"]}})
                done = self.convert()
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(self.written(), ["scribe.md"])
                self.assertEqual(len(self.warns(done, "reviewer")), 1, done.stderr)

    def test_instructions_that_are_not_a_string_are_ignored_and_the_skills_kept(self):
        self.write({"reviewer": {"skills": ["a-skill"], "instructions": ["step one", "step two"]}})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.warns(done, "reviewer")), 1, done.stderr)
        member = self.resolve()["members"][0]
        self.assertEqual((member["skills"], member["instructions"]), (["a-skill"], ""))

    def test_a_skill_the_old_resolver_would_drop_is_dropped_with_a_warning(self):
        self.write({"triager": {"skills": ["good", "bad name", "-lead", 5, "ok.name"]}})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.warns(done, "triager")), 3, done.stderr)
        self.assertEqual(self.resolve()["members"][0]["skills"], ["good", "ok.name"])

    def test_a_file_with_nothing_to_write_exits_0_and_writes_nothing(self):
        self.write({"captain": {"skills": ["a-skill"]}})
        done = self.convert()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.written(), [])
        self.assertNotIn("WROTE", done.stdout)


class TestRefusals(ConvertCase):
    def assert_refused(self, done, before):
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertNotIn("WROTE", done.stdout)
        self.assertTrue(done.stderr.strip())
        self.assertEqual(self.tree(), before)

    def test_invalid_json_is_refused(self):
        for text in ("{ not json", "", "   \n", '{"reviewer": {"skills": ["a-skill"]},}'):
            with self.subTest(text=text):
                self.write(text)
                before = self.tree()
                self.assert_refused(self.convert(), before)

    def test_json_that_is_not_an_object_is_refused(self):
        for text in ("[]", '"reviewer"', "5", "null", '[{"reviewer": {}}]'):
            with self.subTest(text=text):
                self.write(text)
                before = self.tree()
                self.assert_refused(self.convert(), before)

    def test_an_existing_target_file_refuses_everything_and_changes_nothing(self):
        self.crew.mkdir(parents=True)
        (self.crew / "scribe.md").write_text("mine\n")
        self.write({"reviewer": {"skills": ["a-skill"]}, "scribe": {"skills": ["b-skill"]}})
        before = self.tree()
        self.assert_refused(self.convert(), before)
        self.assertEqual((self.crew / "scribe.md").read_text(), "mine\n")
        self.assertFalse((self.crew / "reviewer.md").exists())

    def test_null_instructions_print_no_warning(self):
        self.write({"reviewer": {"skills": ["a-skill"], "instructions": None}})
        done = self.convert()
        self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_a_dangling_symlink_at_a_target_refuses_and_is_not_followed(self):
        self.crew.mkdir(parents=True)
        victim = self.root / "victim" / "authorized_keys"
        victim.parent.mkdir()
        (self.crew / "scribe.md").symlink_to(victim)
        self.write({"reviewer": {"skills": ["a-skill"]}, "scribe": {"skills": ["b-skill"]}})
        before = self.tree()
        self.assert_refused(self.convert(), before)
        self.assertFalse(victim.exists())
        self.assertFalse((self.crew / "reviewer.md").exists())

    def test_a_symlink_to_an_existing_file_refuses_and_leaves_it_alone(self):
        self.crew.mkdir(parents=True)
        other = self.root / "other.md"
        other.write_text("mine\n")
        (self.crew / "scribe.md").symlink_to(other)
        self.write({"scribe": {"skills": ["b-skill"]}})
        before = self.tree()
        self.assert_refused(self.convert(), before)
        self.assertEqual(other.read_text(), "mine\n")

    def test_a_symlinked_crew_dir_refuses_and_writes_nothing_through_it(self):
        real = self.root / "real-crew"
        real.mkdir()
        self.crew.parent.mkdir()
        self.crew.symlink_to(real)
        self.write({"reviewer": {"skills": ["a-skill"]}})
        before = self.tree()
        self.assert_refused(self.convert(), before)
        self.assertEqual(list(real.iterdir()), [])

    def test_a_dangling_symlinked_crew_dir_refuses_and_is_not_created(self):
        real = self.root / "not-there"
        self.crew.parent.mkdir()
        self.crew.symlink_to(real)
        self.write({"reviewer": {"skills": ["a-skill"]}})
        before = self.tree()
        self.assert_refused(self.convert(), before)
        self.assertFalse(real.exists())

    def test_a_body_over_65536_bytes_is_refused(self):
        self.write({"reviewer": {"instructions": "a" * 65537}, "scribe": {"skills": ["a-skill"]}})
        before = self.tree()
        self.assert_refused(self.convert(), before)

    def test_a_directory_name_with_a_newline_is_refused(self):
        odd = self.root / "two\nlines"
        odd.mkdir()
        path = odd / "roles.json"
        self.write({"reviewer": {"skills": ["a-skill"]}}, path)
        before = self.tree()
        self.assert_refused(self.convert(path, self.crew), before)


class TestUsage(ConvertCase):
    def test_wrong_argument_counts_exit_5(self):
        self.write({"reviewer": {"skills": ["a-skill"]}})
        before = self.tree()
        for args in ([], [self.roles_json], [self.roles_json, self.crew, "extra"]):
            with self.subTest(args=args):
                done = subprocess.run(
                    [str(CONVERT), *[str(a) for a in args]],
                    env=self.env(),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(done.returncode, 5, done.stderr)
                self.assertEqual(done.stdout, "")
                self.assertTrue(re.search(r"usage", done.stderr, re.I), done.stderr)
                self.assertEqual(self.tree(), before)


if __name__ == "__main__":
    unittest.main()
