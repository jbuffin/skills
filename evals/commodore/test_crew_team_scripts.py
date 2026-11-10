"""Tests for the team scripts around the crew (issue #199, unit u2): `team-preflight.sh` passing `crew.py cast`'s
warnings through and failing on its errors, and `team-init.sh` writing the Admiral crew variables into `team.env`.
Expected values come from the u2 spec section 5 and the section 8 rulings (each value as `KEY='value'`; a value with
`'` or a newline is not written and the script warns, naming the variable).

Seams: both scripts as subprocesses. The preflight runs against the repo's own scripts with the advisor check off
(`ADVISOR=none`) and the setup test_preflight_advisor.py uses; the init runs in a temp world
(evals/commodore/crew_world.py).

Run from the repo root: python3 -m unittest discover -s evals/commodore -p 'test_crew_team_scripts.py' -v
"""

import unittest

from crew_world import ROLES_JSON_WARNING, WorldCase, parse_table, zsh_value
from test_preflight_advisor import PreflightCase

SECURITY_WARNING = "WARN  security-reviewer has no role skill: no security review this run"


class TestPreflightPassThrough(PreflightCase):
    def setUp(self):
        super().setUp()
        self.team_env(advisor="none")
        self.user_crew = self.home / ".config" / "commodore" / "crew"

    def put(self, directory, name, role, skills=()):
        directory.mkdir(parents=True, exist_ok=True)
        listed = f"skills: [{', '.join(skills)}]\n" if skills else ""
        (directory / f"{name}.md").write_text(
            f"---\nname: {name}\nrole: {role}\npick-me-when: Pick {name}.\n{listed}---\n\nBody.\n"
        )

    def test_cast_warnings_appear_in_the_preflight_output(self):
        self.put(self.user_crew, "reviewer", "reviewer", skills=["zzz-not-installed"])
        done = self.run_preflight(probe=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        lines = done.stdout.splitlines()
        self.assertIn("WARN  reviewer: skill /zzz-not-installed is not available on claude; dropped", lines)
        self.assertIn(SECURITY_WARNING, lines)

    def test_a_leftover_roles_json_warning_passes_through(self):
        legacy = self.repo / ".commodore" / "roles.json"
        legacy.parent.mkdir()
        legacy.write_text("{}")
        done = self.run_preflight(probe=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn(
            ROLES_JSON_WARNING.format(path=legacy),
            done.stdout.splitlines(),
        )

    def test_a_cast_error_fails_the_preflight(self):
        self.user_crew.mkdir(parents=True)
        (self.user_crew / "broken.md").write_text("---\nrole: reviewer\npick-me-when: x\n---\n")
        done = self.run_preflight(probe=False)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertTrue([ln for ln in done.stdout.splitlines() if ln.startswith("FAIL")], done.stdout)
        self.assertIn("broken.md", done.stdout)

    def test_two_run_layer_members_for_one_role_fail_the_preflight(self):
        run_crew = self.team / "crew"
        self.put(run_crew, "pin-a", "reviewer")
        self.put(run_crew, "pin-b", "reviewer")
        done = self.run_preflight(probe=False)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("pin-a, pin-b", done.stdout)


class TestTeamInitAdmiralVars(WorldCase):
    def setUp(self):
        super().setUp()
        self.teams = self.w.root / "teams"
        self.init_sh = self.w.scripts / "team-init.sh"
        self.fleet = self.w.root / "fleet dir"
        self.run_crew = self.w.root / "run crew"
        self.w.layer_dirs.update({"fleet": self.fleet, "admiral-run": self.run_crew})  # where write_member puts them

    def init(self, name="ship-run", **extra):
        env = self.w.env(
            AGENT_TEAMS_DIR=str(self.teams), HARNESS="claude", CMUX_BUNDLED_CLI_PATH="/nonexistent", **extra
        )
        done = self.w.sh([self.init_sh, name, self.w.repo], env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return done, self.teams / name / "team.env"

    def ship_env(self, **extra):
        return {
            "ADMIRAL_SHIP": "ship-1",
            "ADMIRAL_CREW_DIR": str(self.fleet),
            "ADMIRAL_RUN_CREW": str(self.run_crew),
            **extra,
        }

    def test_inside_a_ship_the_three_variables_are_written_in_single_quotes(self):
        _, team_env = self.init(**self.ship_env())
        lines = team_env.read_text().splitlines()
        self.assertIn("ADMIRAL_SHIP='ship-1'", lines)
        self.assertIn(f"ADMIRAL_CREW_DIR='{self.fleet}'", lines)
        self.assertIn(f"ADMIRAL_RUN_CREW='{self.run_crew}'", lines)

    def test_zsh_reads_the_same_values_back(self):
        _, team_env = self.init(**self.ship_env())
        self.assertEqual(
            zsh_value(team_env, "ADMIRAL_SHIP", "ADMIRAL_CREW_DIR", "ADMIRAL_RUN_CREW", "HARNESS"),
            ["ship-1", str(self.fleet), str(self.run_crew), "claude"],
        )

    def test_outside_a_ship_none_of_them_is_written(self):
        for ship in (None, ""):
            with self.subTest(ship=ship):
                extra = {"ADMIRAL_CREW_DIR": str(self.fleet), "ADMIRAL_RUN_CREW": str(self.run_crew)}
                if ship is not None:
                    extra["ADMIRAL_SHIP"] = ship
                _, team_env = self.init(name=f"plain-{ship!r}".replace("'", ""), **extra)
                self.assertNotIn("ADMIRAL_", team_env.read_text())

    def test_a_value_with_a_quote_is_not_written_and_the_script_names_the_variable(self):
        done, team_env = self.init(**self.ship_env(ADMIRAL_CREW_DIR="/it's/fleet"))
        text = team_env.read_text()
        self.assertNotIn("ADMIRAL_CREW_DIR", text)
        self.assertNotIn("/it's/fleet", text)
        self.assertIn("ADMIRAL_CREW_DIR", done.stdout + done.stderr)
        self.assertIn("ADMIRAL_SHIP='ship-1'", text.splitlines())  # the others are still written
        self.assertIn(f"ADMIRAL_RUN_CREW='{self.run_crew}'", text.splitlines())

    def test_a_value_with_a_newline_is_not_written_and_the_script_names_the_variable(self):
        done, team_env = self.init(**self.ship_env(ADMIRAL_RUN_CREW="/run\ncrew"))
        text = team_env.read_text()
        self.assertNotIn("ADMIRAL_RUN_CREW", text)
        self.assertNotIn("/run\n", text)
        self.assertIn("ADMIRAL_RUN_CREW", done.stdout + done.stderr)
        self.assertIn(f"ADMIRAL_CREW_DIR='{self.fleet}'", text.splitlines())

    def test_a_clean_value_prints_no_warning_about_the_variables(self):
        done, _ = self.init(**self.ship_env())
        self.assertNotIn("ADMIRAL_CREW_DIR", done.stdout + done.stderr)

    def test_a_rerun_keeps_the_existing_team_env(self):
        _, team_env = self.init(**self.ship_env())
        first = team_env.read_text()
        self.init(**self.ship_env(ADMIRAL_CREW_DIR="/somewhere/else"))
        self.assertEqual(team_env.read_text(), first)

    def test_a_resumed_run_casts_from_the_same_layers_without_the_environment(self):
        _, team_env = self.init(**self.ship_env())
        self.w.write_member("fleet", "fleet-rev", "reviewer")
        self.w.write_member("admiral-run", "pinned-scribe", "scribe")
        done = self.w.cast(run=team_env.parent, env=self.w.env())  # no ADMIRAL_* in the environment now
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["reviewer"][1], rows["reviewer"][7]), ("fleet-rev", "fleet"))
        self.assertEqual((rows["scribe"][1], rows["scribe"][7]), ("pinned-scribe", "run (pinned)"))


if __name__ == "__main__":
    unittest.main()
