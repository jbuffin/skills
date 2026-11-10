"""Tests for setup-commodore's `crew-draft.sh` (issue #199, unit u2): the verbs init, skills, check and save over a
directory of member files. Expected values come from the u2 spec section 4 and the section 8 rulings.

Seam: `crew-draft.sh` as a subprocess in a temp world (evals/commodore/crew_world.py) with a git checkout as the working
directory, a fake driver (`has-skill` answers from `<scratch run>/installed.txt`, `list-skills` prints a fixed list),
and the member files it reads and writes.

Run from the repo root: python3 -m unittest discover -s evals/commodore -p 'test_crew_draft.py' -v
"""

import unittest
from pathlib import Path

from crew_world import WorldCase, member_text, parse_table


class DraftCase(WorldCase):
    def setUp(self):
        super().setUp()
        self.git_init(self.w.repo)
        self.draft_sh = self.w.skills / "setup-commodore" / "scripts" / "crew-draft.sh"
        self.user_dir = self.w.layer_dirs["user"]
        self.repo_dir = self.w.repo / ".commodore" / "crew"

    def draft(self, *args):
        return self.w.sh([self.draft_sh, *args], cwd=self.w.repo)

    def init(self, target="user", harness="claude"):
        done = self.draft("init", target, harness)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        return Path(lines[0]), lines

    def put(self, directory, name, role=None, **kw):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.md").write_text(member_text(name, role or name, **kw))

    def check(self, run):
        done = self.draft("check", run)
        return done, done.stdout + done.stderr

    def lines(self, done):
        return (done.stdout + done.stderr).splitlines()


class TestInit(DraftCase):
    def test_a_new_target_prints_the_run_dir_new_and_roles(self):
        run, lines = self.init("user")
        self.assertTrue((run / "team.env").is_file())
        self.assertTrue((run / "draft").is_dir())
        self.assertEqual(list((run / "draft").iterdir()), [])
        self.assertEqual(lines[1], f"NEW {self.user_dir}")
        self.assertEqual(lines[2], f"ROLES {self.w.skills / 'commodore' / 'references' / 'roles.md'}")
        self.assertEqual(len(lines), 3)

    def test_the_repo_target_is_the_checkouts_commodore_crew_directory(self):
        _, lines = self.init("repo")
        self.assertEqual(lines[1], f"NEW {self.repo_dir}")

    def test_an_existing_target_is_copied_into_the_draft(self):
        self.put(self.user_dir, "reviewer", skills=["code-review"], body="Review.")
        self.put(self.user_dir, "implementer", skills=["tdd"])
        self.put(self.user_dir, "fix-checker")
        self.put(self.user_dir, "docs-writer", "docs-writer", based_on="scribe")
        self.put(self.user_dir, "rev-strict", "reviewer")
        run, lines = self.init("user")
        self.assertEqual(lines[1], f"FROM {self.user_dir}")
        self.assertEqual(sorted(p.name for p in (run / "draft").iterdir()), ["implementer.md", "reviewer.md"])
        self.assertEqual((run / "draft" / "reviewer.md").read_text(), (self.user_dir / "reviewer.md").read_text())

    def test_a_leftover_roles_json_at_the_target_is_reported(self):
        for target, base in (("user", self.user_dir.parent), ("repo", self.w.repo / ".commodore")):
            with self.subTest(target=target):
                base.mkdir(parents=True, exist_ok=True)
                legacy = base / "roles.json"
                legacy.write_text("{}")
                _, lines = self.init(target)
                self.assertIn(f"ROLESJSON {legacy}", lines)
                legacy.unlink()

    def test_no_leftover_no_roles_json_line(self):
        _, lines = self.init("user")
        self.assertFalse([ln for ln in lines if ln.startswith("ROLESJSON")])

    def test_a_bad_call_exits_5(self):
        for args in ([], ["init"], ["init", "nowhere", "claude"], ["frobnicate"]):
            with self.subTest(args=args):
                done = self.draft(*args)
                self.assertEqual(done.returncode, 5, done.stderr)


class TestSkills(DraftCase):
    def test_lists_the_harnesss_skills_with_their_descriptions(self):
        skill_file = self.w.root / "alpha" / "SKILL.md"
        skill_file.parent.mkdir()
        skill_file.write_text("---\nname: alpha\ndescription: Alpha does things\n---\n# Alpha\n")
        self.w.stub_driver("fake", prefix="$", list_skills=[f"alpha\t{skill_file}", "beta\t-"])
        run, _ = self.init("user", "fake")
        done = self.draft("skills", run)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(), [f"alpha\t{skill_file}\tAlpha does things", "beta\t-\t-"])

    def test_a_harness_without_list_skills_exits_3(self):
        self.w.stub_driver("nolist", prefix="/")
        run, _ = self.init("user", "nolist")
        self.assertEqual(self.draft("skills", run).returncode, 3)


class TestCheck(DraftCase):
    def test_the_table_comes_from_cast_with_the_draft_as_the_run_layer(self):
        run, _ = self.init("user")
        (run / "installed.txt").write_text("code-review\n")
        self.put(run / "draft", "reviewer", skills=["code-review"], body="Review it.")
        done, out = self.check(run)
        self.assertEqual(done.returncode, 0, out)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "reviewer")
        self.assertEqual(rows["reviewer"][3], "`/code-review`")
        self.assertEqual(rows["reviewer"][4], "Review it.")
        self.assertEqual(rows["reviewer"][7], "run (pinned)")

    def test_a_role_without_a_draft_file_is_unset_but_never_the_fix_checker(self):
        run, _ = self.init("user")
        self.put(run / "draft", "reviewer", skills=[])
        done, out = self.check(run)
        self.assertEqual(done.returncode, 0, out)
        unset = [ln.split()[1].rstrip(":") for ln in out.splitlines() if ln.startswith("UNSET ")]
        self.assertEqual(
            sorted(unset),
            sorted(
                [
                    "implementer",
                    "test-writer",
                    "security-reviewer",
                    "brief-checker",
                    "triager",
                    "target-steward",
                    "scribe",
                ]
            ),
        )
        self.assertIn("| fix-checker |", done.stdout)

    def test_leaving_a_role_out_differs_from_clearing_it_with_an_empty_list(self):
        run, _ = self.init("user")
        cleared = member_text(
            "triager",
            "triager",
            pick="Clears triager's skills, so the role uses its fallback procedure.",
            skills=[],
            body="",
        )
        (run / "draft" / "triager.md").write_text(cleared)
        done, out = self.check(run)
        self.assertEqual(done.returncode, 0, out)
        self.assertNotIn("UNSET triager", out)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["triager"][3], "none (fallback procedure)")

    def test_shadowed_when_the_repo_has_a_member_of_the_same_name(self):
        self.put(self.repo_dir, "reviewer", skills=["a-skill"])
        run, _ = self.init("user")
        self.put(run / "draft", "reviewer", skills=[])
        _, out = self.check(run)
        self.assertRegex(out, r"(?m)^SHADOWED reviewer\b")

    def test_shadowed_is_only_for_the_user_target(self):
        self.put(self.repo_dir, "reviewer", skills=["a-skill"])
        run, _ = self.init("repo")
        self.put(run / "draft", "reviewer", skills=[])
        _, out = self.check(run)
        self.assertNotIn("SHADOWED", out)

    def test_outranked_when_the_repo_has_a_differently_named_member_with_that_role(self):
        self.put(self.repo_dir, "rev-strict", "reviewer")
        run, _ = self.init("user")
        self.put(run / "draft", "reviewer", skills=[])
        _, out = self.check(run)
        self.assertRegex(out, r"(?m)^OUTRANKED reviewer: rev-strict$")
        self.assertNotIn("SHADOWED", out)

    def test_a_clean_draft_prints_clean(self):
        run, _ = self.init("user")
        (run / "installed.txt").write_text("code-review\n")
        self.put(run / "draft", "reviewer", skills=["code-review"])
        done, out = self.check(run)
        self.assertEqual(done.returncode, 0, out)
        self.assertIn("CLEAN", self.lines(done))

    def test_a_skill_the_harness_lacks_is_a_warning_and_not_clean(self):
        run, _ = self.init("user")
        self.put(run / "draft", "reviewer", skills=["nope"])
        done, out = self.check(run)
        self.assertEqual(done.returncode, 0, out)
        self.assertIn("skill /nope is not available on claude; dropped", out)
        self.assertNotIn("CLEAN", self.lines(done))

    def test_a_draft_fix_checker_with_skills_does_not_read_as_clean(self):
        run, _ = self.init("user")
        self.put(run / "draft", "fix-checker", skills=["code-review"], body="be thorough")
        done, out = self.check(run)
        self.assertEqual(done.returncode, 0, out)
        self.assertRegex(out, r"(?m)^WARN .*fix-checker")
        self.assertNotIn("CLEAN", self.lines(done))

    def test_exit_1_when_cast_does_(self):
        run, _ = self.init("user")
        (run / "draft" / "reviewer.md").write_text("---\nrole: reviewer\npick-me-when: x\n---\n")
        done, out = self.check(run)
        self.assertEqual(done.returncode, 1, out)
        self.assertNotIn("CLEAN", self.lines(done))

    def test_check_does_not_touch_the_target(self):
        self.put(self.user_dir, "reviewer", skills=["a-skill"])
        before = (self.user_dir / "reviewer.md").read_text()
        run, _ = self.init("user")
        self.put(run / "draft", "scribe", skills=[])
        self.check(run)
        self.assertEqual(sorted(p.name for p in self.user_dir.iterdir()), ["reviewer.md"])
        self.assertEqual((self.user_dir / "reviewer.md").read_text(), before)

    def test_a_bad_run_dir_exits_5(self):
        self.assertEqual(self.draft("check", self.w.root / "nowhere").returncode, 5)


class TestSave(DraftCase):
    def test_writes_each_draft_file_and_removes_the_ones_the_draft_left_out(self):
        self.put(self.user_dir, "implementer", skills=["tdd"])
        self.put(self.user_dir, "reviewer", skills=["old-skill"])
        self.put(self.user_dir, "docs-writer", "docs-writer", based_on="scribe")
        self.put(self.user_dir, "rev-strict", "reviewer")
        run, _ = self.init("user")
        (run / "draft" / "implementer.md").unlink()
        new_reviewer = member_text("reviewer", "reviewer", skills=["new-skill"], body="New.")
        (run / "draft" / "reviewer.md").write_text(new_reviewer)
        self.put(run / "draft", "scribe", skills=["unslop"])
        done = self.draft("save", run)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            sorted(done.stdout.splitlines()),
            sorted(
                [
                    f"SAVED {self.user_dir / 'reviewer.md'}",
                    f"SAVED {self.user_dir / 'scribe.md'}",
                    f"REMOVED {self.user_dir / 'implementer.md'}",
                ]
            ),
        )
        self.assertEqual((self.user_dir / "reviewer.md").read_text(), new_reviewer)
        self.assertTrue((self.user_dir / "scribe.md").is_file())
        self.assertFalse((self.user_dir / "implementer.md").exists())
        # members the draft never held are not touched
        self.assertTrue((self.user_dir / "docs-writer.md").is_file())
        self.assertTrue((self.user_dir / "rev-strict.md").is_file())

    def test_creates_the_target_directory(self):
        run, _ = self.init("repo")
        self.put(run / "draft", "scribe", skills=["unslop"])
        done = self.draft("save", run)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(), [f"SAVED {self.repo_dir / 'scribe.md'}"])
        self.assertTrue((self.repo_dir / "scribe.md").is_file())

    def test_saved_files_resolve_when_the_crew_is_cast(self):
        run, _ = self.init("repo")
        self.put(run / "draft", "scribe", skills=["unslop"], body="Polish.")
        self.draft("save", run)
        self.w.install("unslop")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["scribe"][3], rows["scribe"][4], rows["scribe"][7]), ("`/unslop`", "Polish.", "repo"))

    def test_save_does_not_touch_a_leftover_roles_json(self):
        self.user_dir.parent.mkdir(parents=True)
        legacy = self.user_dir.parent / "roles.json"
        legacy.write_text('{"reviewer": {}}')
        run, _ = self.init("user")
        self.put(run / "draft", "scribe", skills=[])
        self.draft("save", run)
        self.assertEqual(legacy.read_text(), '{"reviewer": {}}')

    def test_a_bad_run_dir_exits_5(self):
        self.assertEqual(self.draft("save", self.w.root / "nowhere").returncode, 5)


if __name__ == "__main__":
    unittest.main()
