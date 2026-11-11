"""Tests for setup-commodore's crew-draft.sh: the verbs init, skills, check and save over member files."""

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
        base = self.w.repo / ".commodore"
        base.mkdir(parents=True)
        legacy = base / "roles.json"
        legacy.write_text("{}")
        _, lines = self.init("repo")
        self.assertIn(f"ROLESJSON {legacy}", lines)

    def test_a_symlinked_member_is_not_copied_and_a_warning_goes_to_stderr(self):
        secret = self.w.root / "secret.md"
        secret.write_text(member_text("implementer", "implementer", body="PRIVATE"))
        self.user_dir.mkdir(parents=True)
        (self.user_dir / "implementer.md").symlink_to(secret)
        self.put(self.user_dir, "reviewer", skills=["code-review"])
        done = self.draft("init", "user", "claude")
        self.assertEqual(done.returncode, 0, done.stderr)
        run = Path(done.stdout.splitlines()[0])  # the first stdout line is still the run dir
        self.assertEqual(sorted(p.name for p in (run / "draft").iterdir()), ["reviewer.md"])
        warns = [ln for ln in done.stderr.splitlines() if ln.startswith("WARN")]
        self.assertEqual(len(warns), 1, done.stderr)
        self.assertIn(str(self.user_dir / "implementer.md"), warns[0])
        self.assertNotIn("WARN", done.stdout)

    def test_a_bad_call_exits_5(self):
        done = self.draft("init", "nowhere", "claude")
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

    def test_shadowed_on_the_user_target_when_the_repo_has_a_member_of_the_same_name(self):
        self.put(self.repo_dir, "reviewer", skills=["a-skill"])
        for target, shadowed in (("user", True), ("repo", False)):
            with self.subTest(target=target):
                run, _ = self.init(target)
                self.put(run / "draft", "reviewer", skills=[])
                _, out = self.check(run)
                if shadowed:
                    self.assertRegex(out, r"(?m)^SHADOWED reviewer\b")
                else:
                    self.assertNotIn("SHADOWED", out)

    def test_outranked_when_the_repo_has_a_differently_named_member_with_that_role(self):
        self.put(self.repo_dir, "rev-strict", "reviewer")
        run, _ = self.init("user")
        self.put(run / "draft", "reviewer", skills=[])
        _, out = self.check(run)
        self.assertRegex(out, r"(?m)^OUTRANKED reviewer: rev-strict$")
        self.assertNotIn("SHADOWED", out)
        self.put(self.repo_dir, "aaa-writer", "scribe")
        run, _ = self.init("repo")
        self.put(run / "draft", "scribe", skills=[])
        _, out = self.check(run)
        self.assertRegex(out, r"(?m)^OUTRANKED scribe: aaa-writer$")
        self.assertNotRegex(out, r"(?m)^OUTRANKED reviewer")  # the draft holds no reviewer

    def test_check_casts_the_draft_even_with_the_admiral_variables_set(self):
        self.put(self.repo_dir, "rev-strict", "reviewer")
        run, _ = self.init("user")
        self.put(run / "draft", "scribe", skills=[], body="Mine.")
        self.w.write_member("fleet", "fleet-scribe", "scribe")
        self.w.write_member("admiral-run", "pinned-scribe", "scribe")
        self.put(run / "draft", "reviewer", skills=[])
        done = self.w.sh([self.draft_sh, "check", run], cwd=self.w.repo, env=self.w.admiral_env())
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["scribe"][1], rows["scribe"][7]), ("scribe", "run (pinned)"))
        self.assertRegex(done.stdout, r"(?m)^OUTRANKED reviewer: rev-strict$")

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
        self.assertTrue([ln for ln in out.splitlines() if ln.startswith("WARN") and "nope" in ln], out)
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

    def assert_save_refused(self, run, snapshot):
        done = self.draft("save", run)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertNotRegex(done.stdout, r"SAVED|REMOVED")
        self.assertIn("symlink", done.stderr)
        self.assertEqual(snapshot(), self.snap_before)

    def snap(self, *roots):
        found = sorted(str(p) for root in roots for p in Path(root).rglob("*"))
        return found

    def test_save_refuses_when_the_target_dir_or_its_parent_is_a_symlink(self):
        real = self.w.root / "real-crew"
        self.put(real, "implementer", skills=["tdd"])
        self.user_dir.parent.mkdir(parents=True)
        self.user_dir.symlink_to(real)
        run, _ = self.init("user")
        (run / "draft" / "implementer.md").unlink()  # leaving it out would remove it
        self.put(run / "draft", "scribe", skills=[])
        self.snap_before = self.snap(real)
        self.assert_save_refused(run, lambda: self.snap(real))
        self.assertTrue((real / "implementer.md").is_file())
        self.user_dir.unlink()
        self.user_dir.parent.rmdir()
        real_parent = self.w.root / "real-commodore"
        real_parent.mkdir()
        self.user_dir.parent.symlink_to(real_parent)
        run, _ = self.init("user")
        self.put(run / "draft", "scribe", skills=[])
        self.snap_before = self.snap(real_parent)
        self.assert_save_refused(run, lambda: self.snap(real_parent))

    def test_save_does_not_refuse_a_symlinked_config_root(self):
        real = self.w.root / "dotfiles-config"
        real.mkdir()
        if self.w.xdg.exists():
            self.w.xdg.rmdir()
        self.w.xdg.symlink_to(real)
        run, _ = self.init("user")
        self.put(run / "draft", "scribe", skills=[])
        done = self.draft("save", run)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((real / "commodore" / "crew" / "scribe.md").is_file())

    def test_save_refuses_when_a_file_it_would_write_or_remove_is_a_symlink(self):
        victim = self.w.root / "victim" / "authorized_keys"
        victim.parent.mkdir()
        self.user_dir.mkdir(parents=True)
        (self.user_dir / "scribe.md").symlink_to(victim)  # dangling
        run, _ = self.init("user")
        self.put(run / "draft", "scribe", skills=[])
        self.put(run / "draft", "reviewer", skills=[])
        self.snap_before = self.snap(self.user_dir, victim.parent)
        self.assert_save_refused(run, lambda: self.snap(self.user_dir, victim.parent))
        self.assertFalse(victim.exists())
        (self.user_dir / "scribe.md").unlink()
        other = self.w.root / "other.md"
        other.write_text("mine\n")
        (self.user_dir / "implementer.md").symlink_to(other)
        run, _ = self.init("user")  # the symlink is not copied, so the draft leaves implementer out
        self.put(run / "draft", "scribe", skills=[])
        self.snap_before = self.snap(self.user_dir)
        self.assert_save_refused(run, lambda: self.snap(self.user_dir))
        self.assertEqual(other.read_text(), "mine\n")

    def test_save_leaves_no_temp_file_and_keeps_readable_modes(self):
        run, _ = self.init("user")
        self.put(run / "draft", "scribe", skills=[])
        self.assertEqual(self.draft("save", run).returncode, 0)
        self.assertEqual([p.name for p in self.user_dir.iterdir()], ["scribe.md"])
        self.assertEqual((self.user_dir / "scribe.md").stat().st_mode & 0o777, 0o644)

    def test_saved_files_resolve_when_the_crew_is_cast(self):
        run, _ = self.init("repo")
        self.put(run / "draft", "scribe", skills=["unslop"], body="Polish.")
        self.draft("save", run)
        self.w.install("unslop")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["scribe"][3], rows["scribe"][4], rows["scribe"][7]), ("`/unslop`", "Polish.", "repo"))


if __name__ == "__main__":
    unittest.main()
