"""Tests for `crew.py cast` (issue #199, unit u2): who fills each role, pins, picks, skills,
models and the files it saves.

Seam: `crew.py cast --run <run>` as a subprocess in a temp world (evals/commodore/crew_world.py): its stdout table, its
stderr ERROR/WARN lines, its exit code, and the files it writes (`cast.json`, `team.env`). Expected values come from the
unit spec (docs/adr/0007, ADR 0009, the u2 spec sections 1, 2 and 8), never from running the code.

Run from the repo root: python3 -m unittest discover -s evals/commodore -p 'test_crew_cast.py' -v
"""

import json
import os
import re
import unittest

from crew_world import (
    HEADER,
    NINE,
    ROLES_JSON_WARNING,
    SEPARATOR,
    WorldCase,
    is_root,
    parse_table,
    zsh_value,
)

BAD_MODELS = ["-bad", "has space", "a$b", 'a"b', "a`b", "a" * 129, "'quoted'"]


class TestTable(WorldCase):
    def test_built_ins_fill_the_nine_roles_in_order(self):
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        header, sep, rows, order = parse_table(done.stdout)
        self.assertEqual(header, HEADER)
        self.assertEqual(sep, SEPARATOR)
        self.assertEqual(order, NINE)
        for role in NINE:
            cells = rows[role]
            self.assertEqual(len(cells), 8, cells)
            self.assertEqual(cells[1], role)  # the built-in member is named after its role
            self.assertEqual(cells[2], "-")  # Based on
            self.assertEqual(cells[5:], ["-", "-", "built-in"], cells)  # Model, Harness, Source

    def test_skills_cell_for_a_role_without_skills(self):
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["implementer"][3], "none (fallback procedure)")
        self.assertEqual(rows["security-reviewer"][3], "none: not launched")
        self.assertEqual(rows["fix-checker"][3], "none")

    def test_fix_checker_instructions_cell_is_a_dash(self):
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["fix-checker"][4], "-")

    def test_security_reviewer_without_a_skill_warns(self):
        done = self.w.cast()
        self.assertIn(
            "WARN  security-reviewer has no role skill: no security review this run", done.stderr.splitlines()
        )

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

    def test_a_driver_without_a_prefix_gets_a_slash(self):
        self.w.stub_driver("bare", prefix=None)
        self.w.team_env(harness="bare")
        self.w.install("code-review")
        self.w.write_member("user", "reviewer", skills=["code-review"])
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["reviewer"][3], "`/code-review`")

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
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][3], "`/code-review`")
        self.assertIn("WARN  reviewer: skill /nope is not available on claude; dropped", done.stderr.splitlines())

    def test_a_role_whose_skills_are_all_dropped_uses_the_fallback_cell(self):
        self.w.write_member("user", "triager", skills=["nope"])
        done = self.w.cast()
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["triager"][3], "none (fallback procedure)")
        self.assertIn("WARN  triager: skill /nope is not available on claude; dropped", done.stderr.splitlines())

    def test_the_drop_warning_names_the_harness_and_prefix(self):
        self.w.stub_driver("fake", prefix="$")
        self.w.team_env(harness="fake")
        self.w.write_member("user", "scribe", skills=["nope"])
        done = self.w.cast()
        self.assertIn("WARN  scribe: skill $nope is not available on fake; dropped", done.stderr.splitlines())

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

    def test_empty_instructions_are_a_dash(self):
        self.w.write_member("user", "scribe", body="")
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["scribe"][4], "-")

    def test_a_valid_model_shows_in_the_model_cell(self):
        self.w.write_member("user", "scribe", model="claude-haiku-5.5")
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["scribe"][5], "claude-haiku-5.5")


class TestPicking(WorldCase):
    def test_no_pick_takes_the_latest_layer_and_warns(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("repo", "rev-b", "reviewer")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "rev-b")
        self.assertEqual(rows["reviewer"][7], "repo")
        self.assertIn("WARN  pick: reviewer: 3 candidates and no pick; took rev-b (repo)", done.stderr.splitlines())

    def test_a_tie_in_the_latest_layer_goes_to_the_first_name_in_byte_order(self):
        self.w.write_member("repo", "bbb-rev", "reviewer")
        self.w.write_member("repo", "aaa-rev", "reviewer")
        done = self.w.cast()
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "aaa-rev")
        self.assertIn("WARN  pick: reviewer: 3 candidates and no pick; took aaa-rev (repo)", done.stderr.splitlines())

    def test_one_candidate_needs_no_pick_and_no_warning(self):
        done = self.assert_cast_works()
        self.assertNotIn("no pick", done.stderr)

    def test_a_pick_wins_over_the_default_and_silences_the_warning(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("repo", "rev-b", "reviewer")
        done = self.w.cast("--pick", "reviewer=rev-a")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "rev-a")
        self.assertEqual(rows["reviewer"][7], "user-global")
        self.assertNotIn("no pick", done.stderr)

    def test_picks_for_several_roles(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("user", "impl-a", "implementer")
        done = self.w.cast("--pick", "reviewer=rev-a", "--pick", "implementer=impl-a")
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["implementer"][1]), ("rev-a", "impl-a"))

    def test_a_pick_of_the_built_in_member_is_allowed(self):
        self.w.write_member("repo", "rev-b", "reviewer")
        done = self.w.cast("--pick", "reviewer=reviewer")
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("reviewer", "built-in"))

    def test_a_pick_of_a_member_with_another_role_is_a_usage_error(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("user", "impl-a", "implementer")
        done = self.w.cast("--pick", "reviewer=impl-a")
        self.assertEqual(done.returncode, 5)
        self.assertEqual(done.stdout, "")
        self.assertIn("rev-a", done.stderr)  # the message names the role's candidates

    def test_a_pick_of_a_missing_member_is_a_usage_error(self):
        done = self.w.cast("--pick", "reviewer=nobody")
        self.assertEqual(done.returncode, 5)
        self.assertEqual(done.stdout, "")
        self.assertIn("reviewer", done.stderr)

    def test_two_picks_for_one_role_are_a_usage_error(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.assert_cast_works("--pick", "reviewer=rev-a")
        done = self.w.cast("--pick", "reviewer=rev-a", "--pick", "reviewer=reviewer")
        self.assertEqual(done.returncode, 5)
        self.assertEqual(done.stdout, "")

    def test_a_pick_without_an_equals_sign_is_a_usage_error(self):
        self.assert_cast_works("--pick", "reviewer=reviewer")
        done = self.w.cast("--pick", "reviewer")
        self.assertEqual((done.returncode, done.stdout), (5, ""))

    def test_a_pick_names_a_role_that_has_no_member_as_a_usage_error(self):
        self.assert_cast_works("--pick", "reviewer=reviewer")
        done = self.w.cast("--pick", "captain=reviewer")
        self.assertEqual((done.returncode, done.stdout), (5, ""))


class TestPins(WorldCase):
    def test_a_run_layer_member_wins_over_a_pick_and_warns(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("run", "pinned-rev", "reviewer")
        done = self.w.cast("--pick", "reviewer=rev-a")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "pinned-rev")
        self.assertEqual(rows["reviewer"][7], "run (pinned)")
        self.assertIn(
            "WARN  pin: reviewer: run-layer member pinned-rev wins over the pick rev-a", done.stderr.splitlines()
        )

    def test_a_pin_needs_no_pick_and_no_warning(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("run", "pinned-rev", "reviewer")
        done = self.w.cast()
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("pinned-rev", "run (pinned)"))
        self.assertNotIn("WARN  pin:", done.stderr)
        self.assertNotIn("no pick", done.stderr)

    def test_a_pick_of_the_pinned_member_itself_does_not_warn(self):
        self.w.write_member("run", "pinned-rev", "reviewer")
        done = self.w.cast("--pick", "reviewer=pinned-rev")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("WARN  pin:", done.stderr)

    def test_a_run_member_named_like_a_built_in_is_a_pin(self):
        self.w.install("tdd")
        self.w.write_member("run", "implementer", skills=["tdd"])
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual(rows["implementer"][3], "`/tdd`")
        self.assertEqual(rows["implementer"][7], "run (pinned)")

    def test_two_pins_without_a_pick_exit_1(self):
        self.w.write_member("run", "pin-a", "reviewer")
        self.w.write_member("run", "pin-b", "reviewer")
        done = self.w.cast()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertIn("ERROR pin: reviewer has run-layer members pin-a, pin-b: pick one", done.stderr.splitlines())

    def test_two_pins_with_a_pick_of_one_of_them_work(self):
        self.w.write_member("run", "pin-a", "reviewer")
        self.w.write_member("run", "pin-b", "reviewer")
        done = self.w.cast("--pick", "reviewer=pin-b")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("pin-b", "run (pinned)"))

    def test_two_pins_with_a_pick_of_someone_else_exit_1(self):
        self.w.write_member("user", "rev-a", "reviewer")
        self.w.write_member("run", "pin-a", "reviewer")
        self.w.write_member("run", "pin-b", "reviewer")
        done = self.w.cast("--pick", "reviewer=rev-a")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        self.assertIn("ERROR pin: reviewer has run-layer members pin-a, pin-b: pick one", done.stderr.splitlines())

    def test_inside_admiral_the_run_layer_comes_from_admiral_run_crew(self):
        self.w.write_member("admiral-run", "pinned-rev", "reviewer")
        self.w.write_member("run", "ignored-rev", "reviewer")  # <run>/crew is not the run layer inside Admiral
        done = self.w.cast(env=self.w.admiral_env())
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("pinned-rev", "run (pinned)"))

    def test_inside_admiral_the_fleet_layer_is_read_and_the_user_layer_is_not(self):
        self.w.write_member("fleet", "fleet-rev", "reviewer")
        self.w.write_member("user", "user-rev", "reviewer")
        done = self.w.cast(env=self.w.admiral_env())
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("fleet-rev", "fleet"))
        self.assertIn("2 candidates and no pick; took fleet-rev (fleet)", done.stderr)


class TestCustomRoles(WorldCase):
    def setUp(self):
        super().setUp()
        self.w.install("unslop")
        self.w.write_member(
            "user", "docs-writer", "docs-writer", based_on="scribe", skills=["unslop"], body="Write the docs."
        )

    def test_an_unpicked_custom_role_is_not_in_the_cast(self):
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, _, order = parse_table(done.stdout)
        self.assertEqual(order, NINE)
        self.assertNotIn("docs-writer", done.stderr)

    def test_a_picked_custom_role_is_listed_after_the_nine(self):
        done = self.w.cast("--pick", "docs-writer=docs-writer")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, order = parse_table(done.stdout)
        self.assertEqual(order, [*NINE, "docs-writer"])
        self.assertEqual(
            rows["docs-writer"],
            ["docs-writer", "docs-writer", "scribe", "`/unslop`", "Write the docs.", "-", "-", "user-global"],
        )

    def test_custom_roles_follow_the_nine_in_name_order(self):
        self.w.write_member("user", "zeta-role", "zeta-role", based_on="scribe")
        self.w.write_member("user", "alpha-role", "alpha-role", based_on="reviewer")
        done = self.w.cast(
            "--pick", "zeta-role=zeta-role", "--pick", "alpha-role=alpha-role", "--pick", "docs-writer=docs-writer"
        )
        _, _, _, order = parse_table(done.stdout)
        self.assertEqual(order, [*NINE, "alpha-role", "docs-writer", "zeta-role"])

    def test_a_pinned_custom_role_needs_no_pick(self):
        self.w.write_member("run", "run-helper", "run-helper", based_on="triager")
        done = self.w.cast()
        _, _, rows, order = parse_table(done.stdout)
        self.assertEqual(order, [*NINE, "run-helper"])
        self.assertEqual((rows["run-helper"][2], rows["run-helper"][7]), ("triager", "run (pinned)"))

    def test_a_custom_member_is_not_a_candidate_for_its_based_on_role(self):
        self.assert_cast_works("--pick", "docs-writer=docs-writer")
        done = self.w.cast("--pick", "scribe=docs-writer")
        self.assertEqual((done.returncode, done.stdout), (5, ""))

    def test_a_custom_role_never_writes_team_env(self):
        self.w.write_member("user", "fast-docs", "fast-docs", based_on="scribe", model="claude-haiku-5.5")
        before = (self.w.run / "team.env").read_text()
        done = self.w.cast("--pick", "fast-docs=fast-docs", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("FAST_DOCS", (self.w.run / "team.env").read_text())
        self.assertNotIn("MODEL_SCRIBE", (self.w.run / "team.env").read_text())
        self.assertTrue((self.w.run / "team.env").read_text().startswith(before))
        entry = next(e for e in self.w.read_json()["cast"] if e["role"] == "fast-docs")
        self.assertEqual(
            (entry["model"], entry["based-on"], entry["member"]), ("claude-haiku-5.5", "scribe", "fast-docs")
        )


class TestResolutionPassThrough(WorldCase):
    def test_an_error_prints_on_stderr_and_exits_1_with_nothing_on_stdout(self):
        d = self.w.layer_dirs["repo"]
        d.mkdir(parents=True)
        (d / "broken.md").write_text("---\nrole: reviewer\npick-me-when: x\n---\n")
        done = self.w.cast()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(done.stdout, "")
        errors = [ln for ln in done.stderr.splitlines() if ln.startswith("ERROR")]
        self.assertEqual(len(errors), 1, done.stderr)
        self.assertRegex(errors[0], r"^ERROR repo broken\.md: missing-field ")

    @unittest.skipIf(is_root(), "root can list any directory")
    def test_an_error_without_a_file_prints_a_dash(self):
        d = self.w.layer_dirs["repo"]
        d.mkdir(parents=True)
        d.chmod(0)
        self.addCleanup(d.chmod, 0o755)
        done = self.w.cast()
        self.assertEqual((done.returncode, done.stdout), (1, ""))
        self.assertRegex(done.stderr, r"(?m)^ERROR repo -: unreadable ")

    def test_a_resolution_warning_prints_on_stderr_as_a_warn_line(self):
        self.w.write_member("user", "rev-a", "reviewer", extra="color: red\n")
        done = self.w.cast("--pick", "reviewer=rev-a")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(done.stderr, r"(?m)^WARN  user-global rev-a\.md: unknown-field ")
        self.assertNotIn("unknown-field", done.stdout)

    def test_no_run_option_is_a_usage_error(self):
        self.assert_cast_works()
        done = self.w.sh([self.w.crew_py, "cast"])
        self.assertEqual((done.returncode, done.stdout), (5, ""))
        self.assertTrue(done.stderr)

    def test_a_missing_team_env_is_a_usage_error(self):
        self.assert_cast_works()
        (self.w.run / "team.env").unlink()
        done = self.w.cast()
        self.assertEqual((done.returncode, done.stdout), (5, ""))

    def test_a_bad_harness_is_a_usage_error(self):
        for harness in ("Claude", "a b", "../claude", "x;y"):
            with self.subTest(harness=harness):
                self.w.team_env()
                self.assert_cast_works()
                self.w.team_env(harness=harness)
                done = self.w.cast()
                self.assertEqual((done.returncode, done.stdout), (5, ""))

    def test_an_unknown_option_is_a_usage_error(self):
        self.assert_cast_works()
        done = self.w.cast("--frobnicate")
        self.assertEqual((done.returncode, done.stdout), (5, ""))


class TestLeftoverRolesJson(WorldCase):
    def paths(self):
        return {
            "user": self.w.xdg / "commodore" / "roles.json",
            "repo": self.w.repo / ".commodore" / "roles.json",
            "run": self.w.run / "roles.json",
        }

    def put(self, which, content='{"reviewer": {"skills": ["code-review"]}}'):
        path = self.paths()[which]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_each_leftover_file_warns_once(self):
        for which in ("user", "repo", "run"):
            with self.subTest(which=which):
                path = self.put(which)
                done = self.w.cast()
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stderr.splitlines().count(ROLES_JSON_WARNING.format(path=path)), 1, done.stderr)
                self.assertNotIn("roles.json", done.stdout)
                path.unlink()

    def test_all_three_warn_together_and_none_is_read(self):
        wanted = [ROLES_JSON_WARNING.format(path=self.put(which)) for which in ("user", "repo", "run")]
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        for line in wanted:
            self.assertIn(line, done.stderr.splitlines())
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][3], "none (fallback procedure)")

    def test_an_invalid_roles_json_is_still_not_read(self):
        path = self.put("repo", "{ not json")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(ROLES_JSON_WARNING.format(path=path), done.stderr.splitlines())

    def test_inside_admiral_the_user_global_file_is_ignored_silently(self):
        user = self.put("user")
        repo = self.put("repo")
        run = self.put("run")
        done = self.w.cast(env=self.w.admiral_env())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn(str(user), done.stderr)
        self.assertIn(ROLES_JSON_WARNING.format(path=repo), done.stderr.splitlines())
        self.assertIn(ROLES_JSON_WARNING.format(path=run), done.stderr.splitlines())

    def test_no_file_no_warning(self):
        self.assertNotIn("roles.json", self.assert_cast_works().stderr)


class TestModels(WorldCase):
    def test_a_bad_model_is_ignored_with_a_warning_and_never_written(self):
        for model in BAD_MODELS:
            with self.subTest(model=model):
                self.w.team_env()
                self.w.write_member("repo", "implementer", model=model)
                done = self.w.cast("--save")
                self.assertEqual(done.returncode, 0, done.stderr)
                warn = (
                    f"WARN  implementer: model {json.dumps(model)} of implementer is not a model name; "
                    "the role keeps its default"
                )
                self.assertIn(warn, done.stderr.splitlines())
                _, _, rows, _ = parse_table(done.stdout)
                self.assertEqual(rows["implementer"][5], "-")
                env_text = (self.w.run / "team.env").read_text()
                self.assertNotIn("MODEL_IMPLEMENTER", env_text)
                self.assertNotIn("MODEL_FIX_CHECKER", env_text)
                self.assertNotIn(model, env_text)
                entry = next(e for e in self.w.read_json()["cast"] if e["role"] == "implementer")
                self.assertIn(entry["model"], (None, ""))

    def test_a_valid_model_pattern_is_accepted(self):
        for model in ("sonnet", "claude-opus-5.5", "anthropic/claude-opus-5.5@v1:[1m]", "a" * 128, "gpt-6.1-sol"):
            with self.subTest(model=model):
                self.w.team_env()
                self.w.write_member("repo", "reviewer", model=model)
                done = self.w.cast("--save")
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertNotIn("is not a model name", done.stderr)
                _, _, rows, _ = parse_table(done.stdout)
                self.assertEqual(rows["reviewer"][5], model)
                self.assertEqual(zsh_value(self.w.run / "team.env", "MODEL_REVIEWER"), [model])

    def test_a_fix_checker_member_model_is_ignored_with_a_warning(self):
        self.w.write_member("repo", "fix-checker", model="opus")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(
            'WARN  fix-checker: the fix checker runs on the implementer\'s model; model "opus" of fix-checker ignored',
            done.stderr.splitlines(),
        )
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["fix-checker"][5], "-")
        self.assertNotIn("opus", (self.w.run / "team.env").read_text())

    def test_the_fix_checker_follows_the_implementers_model(self):
        self.w.write_member("repo", "implementer", model="claude-opus-5.5")
        self.w.write_member("repo", "fix-checker", model="opus")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(
            zsh_value(self.w.run / "team.env", "MODEL_IMPLEMENTER", "MODEL_FIX_CHECKER"),
            ["claude-opus-5.5", "claude-opus-5.5"],
        )

    def test_a_model_for_a_role_the_capability_rule_cares_about_is_written_anyway(self):
        for role in ("reviewer", "security-reviewer", "brief-checker", "triager"):
            with self.subTest(role=role):
                self.w.team_env()
                self.w.write_member("repo", role, model="claude-haiku-5.5")
                done = self.w.cast("--save")
                self.assertEqual(done.returncode, 0, done.stderr)
                var = "MODEL_" + role.upper().replace("-", "_")
                self.assertEqual(zsh_value(self.w.run / "team.env", var), ["claude-haiku-5.5"])


class TestSave(WorldCase):
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
        raw = (self.w.run / "cast.json").read_text()
        data = json.loads(raw)
        self.assertEqual(raw.strip(), json.dumps(data, sort_keys=True, indent=2))
        self.assertEqual(data["picks"], {"implementer": "impl-a", "reviewer": "rev-a"})
        self.assertEqual([e["role"] for e in data["cast"]], NINE)
        for entry in data["cast"]:
            self.assertEqual(
                set(entry),
                {"role", "member", "based-on", "skills", "instructions", "model", "harness", "layer", "pinned"},
            )
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

    def test_a_pinned_member_is_marked_in_cast_json(self):
        self.w.write_member("run", "pinned-rev", "reviewer")
        done = self.w.cast("--pick", "reviewer=rev-a", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        data = self.w.read_json()
        reviewer = next(e for e in data["cast"] if e["role"] == "reviewer")
        self.assertEqual((reviewer["member"], reviewer["layer"], reviewer["pinned"]), ("pinned-rev", "run", True))

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

    def test_a_saved_pick_for_a_deleted_member_is_dropped_with_a_warning(self):
        self.w.cast("--pick", "reviewer=rev-a", "--save")
        (self.w.layer_dirs["user"] / "rev-a.md").unlink()
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("WARN  pick: reviewer: saved pick rev-a is gone; dropped", done.stderr.splitlines())
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "reviewer")

    def test_a_saved_pick_whose_member_changed_role_is_dropped_with_a_warning(self):
        self.w.cast("--pick", "reviewer=rev-a", "--save")
        self.w.write_member("user", "rev-a", "scribe")
        done = self.w.cast()
        self.assertIn("WARN  pick: reviewer: saved pick rev-a is gone; dropped", done.stderr.splitlines())

    def test_save_writes_the_model_block_to_team_env(self):
        before = self.team_env_text()
        done = self.w.cast("--pick", "implementer=impl-a", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = self.team_env_text()
        self.assertTrue(text.startswith(before))  # existing lines stay as they were
        self.assertEqual(text.count("# crew models (crew.py cast)"), 1)
        self.assertIn("MODEL_IMPLEMENTER='claude-sonnet-5.5'\n", text)
        self.assertIn("MODEL_FIX_CHECKER='claude-sonnet-5.5'\n", text)
        self.assertEqual(
            zsh_value(self.w.run / "team.env", "MODEL_IMPLEMENTER", "MODEL_FIX_CHECKER", "HARNESS"),
            ["claude-sonnet-5.5", "claude-sonnet-5.5", "claude"],
        )

    def test_the_model_block_overrides_an_earlier_default(self):
        self.w.team_env(lines=["MODEL_IMPLEMENTER=sonnet", "MODEL_FIX_CHECKER=sonnet", "MODEL_SCRIBE=sonnet"])
        self.w.write_member("user", "scribe", model="claude-haiku-5.5")
        self.w.cast("--pick", "implementer=impl-a", "--save")
        self.assertEqual(
            zsh_value(self.w.run / "team.env", "MODEL_IMPLEMENTER", "MODEL_FIX_CHECKER", "MODEL_SCRIBE"),
            ["claude-sonnet-5.5", "claude-sonnet-5.5", "claude-haiku-5.5"],
        )

    def test_role_names_become_upper_case_variable_names(self):
        self.w.write_member("user", "test-writer", model="m-1")
        self.w.write_member("user", "security-reviewer", model="m-2")
        self.w.write_member("user", "target-steward", model="m-3")
        self.w.cast("--save")
        self.assertEqual(
            zsh_value(self.w.run / "team.env", "MODEL_TEST_WRITER", "MODEL_SECURITY_REVIEWER", "MODEL_TARGET_STEWARD"),
            ["m-1", "m-2", "m-3"],
        )

    def test_a_second_save_rewrites_the_block_instead_of_appending(self):
        self.w.cast("--pick", "implementer=impl-a", "--save")
        self.w.write_member("user", "impl-a", "implementer", model="claude-opus-5.5")
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        text = self.team_env_text()
        self.assertEqual(text.count("# crew models (crew.py cast)"), 1)
        self.assertEqual(text.count("MODEL_IMPLEMENTER='"), 1)
        self.assertEqual(text.count("MODEL_FIX_CHECKER='"), 1)
        self.assertIn("MODEL_IMPLEMENTER='claude-opus-5.5'", text)
        self.assertIn("MODEL_FIX_CHECKER='claude-opus-5.5'", text)
        self.assertNotIn("claude-sonnet-5.5", text)

    def test_a_second_save_drops_a_model_the_member_no_longer_has(self):
        self.w.write_member("user", "scribe", model="claude-haiku-5.5")
        self.w.cast("--save")
        self.assertIn("MODEL_SCRIBE='claude-haiku-5.5'", self.team_env_text())
        self.w.write_member("user", "scribe")
        self.w.cast("--save")
        self.assertNotIn("MODEL_SCRIBE='", self.team_env_text())

    def test_the_block_is_the_same_after_saving_twice(self):
        self.w.cast("--pick", "implementer=impl-a", "--save")
        first = self.team_env_text()
        self.assertIn("MODEL_IMPLEMENTER='claude-sonnet-5.5'", first)
        self.w.cast("--save")
        self.assertEqual(self.team_env_text(), first)

    def test_no_model_anywhere_writes_no_model_lines(self):
        (self.w.layer_dirs["user"] / "impl-a.md").unlink()
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("MODEL_", self.team_env_text())

    def test_save_leaves_team_env_alone_on_an_error(self):
        self.w.write_member("run", "pin-a", "reviewer")
        self.w.write_member("run", "pin-b", "reviewer")
        before = self.team_env_text()
        done = self.w.cast("--save")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.team_env_text(), before)
        self.assertFalse((self.w.run / "cast.json").exists())

    def test_cast_json_survives_a_custom_role_and_keeps_picks_for_it(self):
        self.w.write_member("user", "docs-writer", "docs-writer", based_on="scribe")
        self.w.cast("--pick", "docs-writer=docs-writer", "--save")
        done = self.w.cast()
        _, _, _, order = parse_table(done.stdout)
        self.assertEqual(order, [*NINE, "docs-writer"])
        self.assertEqual(self.w.read_json()["picks"], {"docs-writer": "docs-writer"})


class TestEnvironment(WorldCase):
    def test_the_caller_cannot_move_the_run_layer_outside_admiral(self):
        self.w.write_member("admiral-run", "x-rev", "reviewer")
        done = self.w.cast(env=self.w.env(ADMIRAL_RUN_CREW=str(self.w.layer_dirs["admiral-run"])))
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(rows["reviewer"][1], "reviewer")

    def test_cast_runs_from_any_directory(self):
        done = self.w.sh([self.w.crew_py, "cast", "--run", self.w.run], cwd=os.sep)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(re.search(r"^\| implementer \|", done.stdout, re.M))


if __name__ == "__main__":
    unittest.main()
