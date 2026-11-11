"""team-preflight.sh passing crew.py cast's warnings and errors through, and team-init.sh's Admiral variables."""

import unittest

from crew_world import PreflightCase, WorldCase, parse_table, zsh_value


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
        warns = self.lines(done, "WARN  ")
        self.assertTrue([ln for ln in warns if "reviewer" in ln and "/zzz-not-installed" in ln], done.stdout)
        self.assertTrue([ln for ln in warns if ln.startswith("WARN  security-reviewer")], done.stdout)

    def test_a_cast_error_fails_the_preflight(self):
        self.user_crew.mkdir(parents=True)
        (self.user_crew / "broken.md").write_text("---\nrole: reviewer\npick-me-when: x\n---\n")
        done = self.run_preflight(probe=False)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertTrue([ln for ln in done.stdout.splitlines() if ln.startswith("FAIL")], done.stdout)
        self.assertIn("broken.md", done.stdout)

    def test_a_bad_call_to_cast_reports_the_reason_not_the_usage_text(self):
        self.team_env(advisor="none", harness="Not A Harness")
        done = self.run_preflight(probe=False)
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        fails = [ln for ln in done.stdout.splitlines() if ln.startswith("FAIL") and "crew" in ln]
        self.assertEqual(len(fails), 1, done.stdout)
        self.assertIn("HARNESS", fails[0])
        self.assertNotIn("--admiral", done.stdout)

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

    def test_a_value_with_a_quote_or_newline_is_not_written_and_the_script_names_the_variable(self):
        done, team_env = self.init(**self.ship_env(ADMIRAL_CREW_DIR="/it's/fleet", ADMIRAL_RUN_CREW="/run\ncrew"))
        text = team_env.read_text()
        self.assertNotIn("ADMIRAL_CREW_DIR", text)
        self.assertNotIn("ADMIRAL_RUN_CREW", text)
        self.assertIn("ADMIRAL_CREW_DIR", done.stdout + done.stderr)
        self.assertIn("ADMIRAL_RUN_CREW", done.stdout + done.stderr)
        self.assertIn("ADMIRAL_SHIP='ship-1'", text.splitlines())

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
