"""Tests for `crew.py cast`: who fills each role, pins, picks, skills, models and the files it saves."""

import os
import re
import unittest

from crew_world import NINE, WorldCase, parse_table, zsh_value


class CastCase(WorldCase):
    def assert_line(self, done, prefix, *names):
        """One stderr line starts with `prefix` and names every one of `names`."""
        found = [ln for ln in done.stderr.splitlines() if ln.startswith(prefix) and all(n in ln for n in names)]
        self.assertTrue(found, f"no {prefix!r} line naming {names}:\n{done.stderr}")


class TestTable(CastCase):
    def test_built_ins_fill_the_nine_roles_in_order(self):
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, order = parse_table(done.stdout)
        self.assertEqual(order, NINE)
        for role in NINE:
            self.assertEqual((rows[role][1], rows[role][7]), (role, "built-in"))

    def test_security_reviewer_without_a_skill_warns(self):
        self.assert_line(self.w.cast(), "WARN", "security-reviewer")

    def test_security_reviewer_with_a_skill_does_not_warn(self):
        self.w.install("security-review")
        self.w.write_member("repo", "security-reviewer", skills=["security-review"])
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("no role skill", done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["security-reviewer"][3], "`/security-review`")

    def test_skills_are_joined_in_member_order_with_the_claude_prefix(self):
        self.w.install("code-review", "simplify")
        self.w.write_member("user", "reviewer", skills=["simplify", "code-review"])
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][3], "`/simplify`, `/code-review`")
        self.assertEqual(rows["reviewer"][6:], ["-", "user-global"])

    def test_prefix_comes_from_the_drivers_skill_prefix(self):
        self.w.stub_driver("fake", prefix="$")
        self.w.team_env(harness="fake")
        self.w.install("code-review")
        self.w.write_member("user", "reviewer", skills=["code-review"])
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["reviewer"][3], "`$code-review`")

    def test_harness_defaults_to_claude_and_is_read_from_team_env_alone(self):
        self.w.team_env(harness=None)
        self.w.stub_driver("fake", prefix="$")
        self.w.install("code-review")
        self.w.write_member("user", "reviewer", skills=["code-review"])
        for env in (self.w.env(), self.w.env(HARNESS="fake")):
            done = self.w.cast(env=env)
            self.assertEqual(done.returncode, 0, done.stderr)
            _, _, rows, _ = parse_table(done.stdout)
            self.assertEqual(rows["reviewer"][3], "`/code-review`")

    def test_a_skill_the_driver_rejects_is_dropped_with_a_warning(self):
        self.w.install("code-review")
        self.w.write_member("user", "reviewer", skills=["code-review", "nope"])
        self.w.write_member("user", "triager", skills=["nope"])
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][3], "`/code-review`")
        self.assertEqual(rows["triager"][3], "none (fallback procedure)")
        self.assert_line(done, "WARN  reviewer:", "/nope", "claude")
        self.assert_line(done, "WARN  triager:", "/nope", "claude")

    def test_a_driver_without_has_skill_keeps_every_skill_with_one_warning(self):
        self.w.stub_driver("nocheck", prefix="/", has_skill=False)
        self.w.team_env(harness="nocheck")
        self.w.write_member("user", "reviewer", skills=["a-skill", "b-skill"])
        self.w.write_member("user", "scribe", skills=["c-skill"])
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][3], "`/a-skill`, `/b-skill`")
        self.assertEqual(rows["scribe"][3], "`/c-skill`")
        extra = [w for w in self.warns(done) if "security-reviewer has no role skill" not in w]
        self.assertEqual(len(extra), 1, done.stderr)
        self.assertIn("nocheck", extra[0])

    def test_instructions_become_one_table_cell(self):
        self.w.write_member("user", "scribe", body="line one\nline|two\n\tindented")
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["scribe"][4], "line one<br>line\\|two<br> indented")


class TestPicking(CastCase):
    def test_no_pick_takes_the_latest_layer_and_warns(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("repo", "rev-b", "reviewer")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("rev-b", "repo"))
        self.assert_line(done, "WARN  pick: reviewer:", "rev-b")

    def test_a_tie_in_the_latest_layer_goes_to_the_first_name_in_byte_order(self):
        self.w.write_member("repo", "bbb-rev", "reviewer")
        self.w.write_member("repo", "aaa-rev", "reviewer")
        done = self.w.cast()
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "aaa-rev")
        self.assert_line(done, "WARN  pick: reviewer:", "aaa-rev")

    def test_a_pick_wins_over_the_default_and_silences_the_warning(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("repo", "rev-b", "reviewer")
        done = self.w.cast("--pick", "reviewer=rev-a")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("rev-a", "user-global"))
        self.assertNotIn("no pick", done.stderr)

    def test_a_pick_of_a_member_with_another_role_is_a_usage_error(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("user", "impl-a", "implementer")
        done = self.w.cast("--pick", "reviewer=impl-a")
        self.assertEqual((done.returncode, done.stdout), (5, ""))
        self.assertIn("rev-a", done.stderr)  # the message names the role's candidates

    def test_a_pick_of_a_missing_member_is_a_usage_error(self):
        done = self.w.cast("--pick", "reviewer=nobody")
        self.assertEqual((done.returncode, done.stdout), (5, ""))
        self.assertIn("reviewer", done.stderr)

    def test_malformed_picks_are_usage_errors(self):
        self.w.write_member("user", "rev-a", "reviewer")
        for args in (
            ("--pick", "reviewer=rev-a", "--pick", "reviewer=reviewer"),
            ("--pick", "reviewer"),
            ("--pick", "captain=reviewer"),
        ):
            with self.subTest(args=args):
                done = self.w.cast(*args)
                self.assertEqual((done.returncode, done.stdout), (5, ""))


class TestPins(CastCase):
    def test_a_run_layer_member_wins_over_a_pick_and_warns(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("run", "pinned-rev", "reviewer")
        done = self.w.cast("--pick", "reviewer=rev-a", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("pinned-rev", "run (pinned)"))
        self.assert_line(done, "WARN  pin: reviewer:", "pinned-rev", "rev-a")
        reviewer = next(e for e in self.w.read_json()["cast"] if e["role"] == "reviewer")
        self.assertEqual((reviewer["member"], reviewer["layer"], reviewer["pinned"]), ("pinned-rev", "run", True))

    def test_two_pins_without_a_pick_exit_1(self):
        self.w.write_member("run", "pin-a", "reviewer")
        self.w.write_member("run", "pin-b", "reviewer")
        done = self.w.cast()
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assert_line(done, "ERROR pin: reviewer", "pin-a", "pin-b")

    def test_two_pins_with_a_pick_of_one_of_them_work(self):
        self.w.write_member("run", "pin-a", "reviewer")
        self.w.write_member("run", "pin-b", "reviewer")
        done = self.w.cast("--pick", "reviewer=pin-b")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("pin-b", "run (pinned)"))


class TestCustomRoles(CastCase):
    def setUp(self):
        super().setUp()
        self.w.install("unslop")
        self.w.write_member(
            "user", "docs-writer", "docs-writer", based_on="scribe", skills=["unslop"], body="Write the docs."
        )

    def test_only_picked_custom_roles_are_cast_after_the_nine_in_name_order_and_the_pick_is_saved(self):
        self.w.write_member("user", "zeta-role", "zeta-role", based_on="scribe")
        self.w.write_member("user", "alpha-role", "alpha-role", based_on="reviewer")
        _, _, _, order = parse_table(self.w.cast().stdout)
        self.assertEqual(order, NINE)
        done = self.w.cast("--pick", "zeta-role=zeta-role", "--pick", "docs-writer=docs-writer", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, order = parse_table(done.stdout)
        self.assertEqual(order, [*NINE, "docs-writer", "zeta-role"])
        self.assertEqual(
            rows["docs-writer"],
            ["docs-writer", "docs-writer", "scribe", "`/unslop`", "Write the docs.", "-", "-", "user-global"],
        )
        _, _, _, order = parse_table(self.w.cast().stdout)
        self.assertEqual(order, [*NINE, "docs-writer", "zeta-role"])

    def test_a_custom_member_is_not_a_candidate_for_its_based_on_role(self):
        done = self.w.cast("--pick", "scribe=docs-writer")
        self.assertEqual((done.returncode, done.stdout), (5, ""))

    def test_a_custom_role_never_writes_team_env(self):
        self.w.stub_driver("codex", prefix="$")
        (self.w.drivers / "codex" / "driver.env").write_text("LIVE_MESSAGING=0\nSEND=script\nSKILL_PREFIX=$\n")
        available = self.w.drivers / "codex" / "available"
        available.write_text("#!/bin/sh\nexit 0\n")
        available.chmod(0o755)
        lock = "harness: codex\n"
        self.w.write_member("user", "fast-docs", "fast-docs", based_on="scribe", model="claude-haiku-5.5", extra=lock)
        self.w.write_member("user", "lock-impl", "implementer", model="gpt-5.5", extra=lock)
        before = (self.w.run / "team.env").read_text()
        done = self.w.cast("--pick", "fast-docs=fast-docs", "--pick", "implementer=lock-impl", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = (self.w.run / "team.env").read_text()
        self.assertTrue(text.startswith(before))
        self.assertIn("HARNESS_IMPLEMENTER='codex'", text)
        self.assertNotIn("FAST_DOCS", text)
        self.assertNotIn("MODEL_SCRIBE", text)
        entry = next(e for e in self.w.read_json()["cast"] if e["role"] == "fast-docs")
        self.assertEqual(
            (entry["model"], entry["based-on"], entry["member"]), ("claude-haiku-5.5", "scribe", "fast-docs")
        )


class TestResolutionPassThrough(CastCase):
    def test_an_error_prints_on_stderr_and_exits_1_with_nothing_on_stdout(self):
        d = self.w.layer_dirs["repo"]
        d.mkdir(parents=True)
        (d / "broken.md").write_text("---\nrole: reviewer\npick-me-when: x\n---\n")
        done = self.w.cast()
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        errors = [ln for ln in done.stderr.splitlines() if ln.startswith("ERROR")]
        self.assertEqual(len(errors), 1, done.stderr)
        self.assertRegex(errors[0], r"^ERROR repo broken\.md: missing-field ")

    def test_a_resolution_warning_prints_on_stderr_as_a_warn_line(self):
        self.w.write_member("user", "rev-a", "reviewer", extra="color: red\n")
        done = self.w.cast("--pick", "reviewer=rev-a")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stderr, r"(?m)^WARN  user-global rev-a\.md: unknown-field ")
        self.assertNotIn("unknown-field", done.stdout)

    def test_no_run_option_is_a_usage_error(self):
        done = self.w.sh([self.w.crew_py, "cast"])
        self.assertEqual((done.returncode, done.stdout), (5, ""))
        self.assertTrue(done.stderr)

    def test_a_bad_harness_is_a_usage_error(self):
        self.w.team_env(harness="../claude")
        done = self.w.cast()
        self.assertEqual((done.returncode, done.stdout), (5, ""))


class TestLeftoverRolesJson(CastCase):
    def put(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"reviewer": {"skills": ["code-review"]}}')
        return path

    def test_all_three_warn_together_and_none_is_read(self):
        paths = [
            self.put(self.w.xdg / "commodore" / "roles.json"),
            self.put(self.w.repo / ".commodore" / "roles.json"),
            self.put(self.w.run / "roles.json"),
        ]
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        for path in paths:
            self.assertEqual(len(self.roles_json_warnings(done, path)), 1, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][3], "none (fallback procedure)")

    def test_inside_admiral_the_user_global_file_is_ignored_silently(self):
        user = self.put(self.w.xdg / "commodore" / "roles.json")
        repo = self.put(self.w.repo / ".commodore" / "roles.json")
        run = self.put(self.w.run / "roles.json")
        done = self.w.cast(env=self.w.admiral_env())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn(str(user), done.stderr)
        self.assertTrue(self.roles_json_warnings(done, repo), done.stderr)
        self.assertTrue(self.roles_json_warnings(done, run), done.stderr)


class TestModels(CastCase):
    def test_a_bad_model_is_ignored_with_a_warning_and_never_written(self):
        for model in ("-bad", 'a"b'):
            with self.subTest(model=model):
                self.w.team_env()
                self.w.write_member("repo", "implementer", model=model)
                done = self.w.cast("--save")
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assert_line(done, "WARN  implementer:", "is not a model name")
                _, _, rows, _ = parse_table(done.stdout)
                self.assertEqual(rows["implementer"][5], "-")
                env_text = (self.w.run / "team.env").read_text()
                self.assertNotIn("MODEL_IMPLEMENTER", env_text)
                self.assertNotIn(model, env_text)

    def test_a_valid_model_pattern_is_accepted(self):
        model = "anthropic/claude-opus-5.5@v1:[1m]"
        self.w.write_member("repo", "reviewer", model=model)
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("is not a model name", done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][5], model)
        self.assertEqual(zsh_value(self.w.run / "team.env", "MODEL_REVIEWER"), [model])

    def test_the_fix_checker_follows_the_implementers_model_and_ignores_its_own(self):
        self.w.write_member("repo", "implementer", model="claude-opus-5.5")
        self.w.write_member("repo", "fix-checker", model="opus")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_line(done, "WARN  fix-checker:", '"opus"', "fix-checker ignored")
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["fix-checker"][5], "-")
        self.assertEqual(
            zsh_value(self.w.run / "team.env", "MODEL_IMPLEMENTER", "MODEL_FIX_CHECKER"),
            ["claude-opus-5.5", "claude-opus-5.5"],
        )


class TestSave(CastCase):
    def setUp(self):
        super().setUp()
        self.w.install("code-review", "simplify")
        self.w.write_member("user", "rev-a", "reviewer", skills=["code-review", "nope"], body="Do a review.")
        self.w.write_member("user", "impl-a", "implementer", model="claude-sonnet-5.5")

    def team_env_text(self):
        return (self.w.run / "team.env").read_text()

    def test_without_save_nothing_is_written(self):
        before = self.team_env_text()
        done = self.w.cast("--pick", "reviewer=rev-a")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.w.run / "cast.json").exists())
        self.assertEqual(self.team_env_text(), before)

    def test_save_writes_cast_json(self):
        done = self.w.cast("--pick", "reviewer=rev-a", "--pick", "implementer=impl-a", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        data = self.w.read_json()
        self.assertEqual(data["picks"], {"implementer": "impl-a", "reviewer": "rev-a"})
        self.assertEqual([e["role"] for e in data["cast"]], NINE)
        reviewer = next(e for e in data["cast"] if e["role"] == "reviewer")
        self.assertEqual(reviewer["member"], "rev-a")
        self.assertEqual(reviewer["skills"], ["code-review"])  # bare names, after the harness filter
        self.assertEqual(reviewer["instructions"], "Do a review.")
        self.assertEqual((reviewer["layer"], reviewer["pinned"]), ("user-global", False))
        self.assertIn(reviewer["based-on"], (None, ""))
        implementer = next(e for e in data["cast"] if e["role"] == "implementer")
        self.assertEqual(implementer["model"], "claude-sonnet-5.5")
        fix = next(e for e in data["cast"] if e["role"] == "fix-checker")
        self.assertEqual((fix["skills"], fix["instructions"], fix["layer"]), ([], "", "built-in"))

    def test_saved_picks_are_kept_by_a_later_call(self):
        self.w.cast("--pick", "reviewer=rev-a", "--save")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "rev-a")
        self.assertNotIn("pick: reviewer:", done.stderr)  # the unpicked implementer still warns

    def test_a_new_pick_replaces_the_saved_one(self):
        self.w.write_member("user", "rev-c", "reviewer")
        self.w.cast("--pick", "reviewer=rev-a", "--save")
        done = self.w.cast("--pick", "reviewer=rev-c", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "rev-c")
        self.assertEqual(self.w.read_json()["picks"], {"reviewer": "rev-c"})

    def test_a_saved_pick_whose_member_is_gone_is_dropped_with_a_warning(self):
        for gone in ("deleted", "changed role"):
            with self.subTest(gone=gone):
                self.w.write_member("user", "rev-a", "reviewer")
                self.w.cast("--pick", "reviewer=rev-a", "--save")
                if gone == "deleted":
                    (self.w.layer_dirs["user"] / "rev-a.md").unlink()
                else:
                    self.w.write_member("user", "rev-a", "scribe")
                done = self.w.cast()
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assert_line(done, "WARN  pick: reviewer:", "rev-a")
                _, _, rows, _ = parse_table(done.stdout)
                self.assertEqual(rows["reviewer"][1], "reviewer")

    def test_save_writes_the_model_block_to_team_env(self):
        self.w.write_member("user", "test-writer", model="m-1")
        self.w.write_member("user", "security-reviewer", model="m-2")
        before = self.team_env_text()
        done = self.w.cast("--pick", "implementer=impl-a", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(self.team_env_text().startswith(before))  # existing lines stay as they were
        self.assertEqual(
            zsh_value(
                self.w.run / "team.env",
                "MODEL_IMPLEMENTER",
                "MODEL_FIX_CHECKER",
                "MODEL_TEST_WRITER",
                "MODEL_SECURITY_REVIEWER",
                "HARNESS",
            ),
            ["claude-sonnet-5.5", "claude-sonnet-5.5", "m-1", "m-2", "claude"],
        )

    def test_the_model_block_overrides_an_earlier_default(self):
        self.w.team_env(lines=["MODEL_IMPLEMENTER=sonnet", "MODEL_FIX_CHECKER=sonnet", "MODEL_SCRIBE=sonnet"])
        self.w.write_member("user", "scribe", model="claude-haiku-5.5")
        self.w.cast("--pick", "implementer=impl-a", "--save")
        self.assertEqual(
            zsh_value(self.w.run / "team.env", "MODEL_IMPLEMENTER", "MODEL_FIX_CHECKER", "MODEL_SCRIBE"),
            ["claude-sonnet-5.5", "claude-sonnet-5.5", "claude-haiku-5.5"],
        )

    def test_a_second_save_rewrites_the_block(self):
        self.w.write_member("user", "scribe", model="claude-haiku-5.5")
        self.w.cast("--pick", "implementer=impl-a", "--save")
        first = self.team_env_text()
        self.w.cast("--save")
        self.assertEqual(self.team_env_text(), first)
        self.w.write_member("user", "impl-a", "implementer", model="claude-opus-5.5")
        self.w.write_member("user", "scribe")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = self.team_env_text()
        self.assertEqual(text.count("MODEL_IMPLEMENTER='"), 1)
        self.assertEqual(text.count("MODEL_FIX_CHECKER='"), 1)
        self.assertNotIn("MODEL_SCRIBE='", text)
        self.assertEqual(
            zsh_value(self.w.run / "team.env", "MODEL_IMPLEMENTER", "MODEL_FIX_CHECKER"),
            ["claude-opus-5.5", "claude-opus-5.5"],
        )

    def test_save_leaves_team_env_alone_on_an_error(self):
        self.w.write_member("run", "pin-a", "reviewer")
        self.w.write_member("run", "pin-b", "reviewer")
        before = self.team_env_text()
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.team_env_text(), before)
        self.assertFalse((self.w.run / "cast.json").exists())


class TestEnvironment(CastCase):
    def test_cast_runs_from_any_directory(self):
        done = self.w.sh([self.w.crew_py, "cast", "--run", self.w.run], cwd=os.sep)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(re.search(r"^\| implementer \|", done.stdout, re.M))


if __name__ == "__main__":
    unittest.main()
