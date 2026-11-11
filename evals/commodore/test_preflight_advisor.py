"""team-preflight.sh's advisor check: a model in ADVISOR's family gets an OK line instead of a probe."""

import unittest

from crew_world import PreflightCase

OPUS_ROLES = ["brief-checker", "reviewer", "security-reviewer", "triager"]


class AdvisorCase(PreflightCase):
    def by_design(self, done, model):
        return [line for line in done.stdout.splitlines() if f"no advisor for {model} " in line]

    def assert_by_design_line(self, done, model, roles):
        found = self.by_design(done, model)
        self.assertEqual(len(found), 1, f"expected one by-design line for {model}:\n{done.stdout}")
        self.assertTrue(found[0].startswith("OK "), found[0])
        for role in roles:
            self.assertIn(role, found[0])


class TestSameFamily(AdvisorCase):
    def test_default_team_env_probes_sonnet_once_and_opus_never(self):
        self.team_env()
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.probed(), [(str(self.team), "sonnet")])
        self.assertEqual(len(self.lines(done, "OK    advisor on for sonnet")), 1, done.stdout)
        self.assert_by_design_line(done, "opus", OPUS_ROLES)
        self.assertNotIn("ADVISOR OFF", done.stdout + done.stderr)

    def test_results_stay_paired_with_their_models_when_a_same_family_model_comes_first(self):
        self.team_env(model="opus", roles=["MODEL_REVIEWER=opus", "MODEL_SCRIBE=haiku", "MODEL_IMPLEMENTER=sonnet"])
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.probed(), sorted([(str(self.team), "haiku"), (str(self.team), "sonnet")]))
        self.assertEqual(len(self.lines(done, "OK    advisor on for haiku")), 1, done.stdout)
        self.assertEqual(len(self.lines(done, "OK    advisor on for sonnet")), 1, done.stdout)
        self.assert_by_design_line(done, "opus", ["default", "reviewer"])

    def test_all_opus_team_env_starts_no_probes_and_completes(self):
        roles = [f"MODEL_{r}=opus" for r in ("BRIEF_CHECKER", "TEST_WRITER", "IMPLEMENTER", "REVIEWER", "SCRIBE")]
        self.team_env(model="opus", roles=roles)
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.probed(), [])
        self.assert_by_design_line(done, "opus", ["default", "brief-checker", "scribe"])
        self.assertTrue(self.lines(done, "OK    git found"), done.stdout)


class TestStillProbed(AdvisorCase):
    def test_off_result_for_a_probed_model_still_warns(self):
        self.stub.write_text(
            """#!/bin/sh
printf '%s %s\\n' "$1" "$2" >> "$PROBE_LOG"
echo "ADVISOR OFF $2: advisor unavailable (refused)"
"""
        )
        self.team_env(roles=["MODEL_REVIEWER=opus"])
        done = self.run_preflight()
        self.assertEqual(self.probed(), [(str(self.team), "sonnet")])
        self.assertEqual(len(self.lines(done, "WARN  ADVISOR OFF: sonnet")), 1, done.stdout)
        self.assertEqual(self.lines(done, "WARN  ADVISOR OFF: opus"), [])
        self.assert_by_design_line(done, "opus", ["reviewer"])

    def test_advisor_none_skips_the_check(self):
        self.team_env(advisor="none")
        done = self.run_preflight()
        self.assertEqual(self.probed(), [])
        self.assertEqual(len(self.lines(done, "OK    advisor check skipped (ADVISOR=none)")), 1, done.stdout)
        self.assertEqual(self.lines(done, "OK    no advisor for"), [])

    def test_harness_without_a_probe_is_still_na(self):
        self.team_env(harness="codex")
        done = self.run_preflight(probe=False, claudecode="", CODEX_THREAD_ID="t-1")
        self.assertEqual(self.probed(), [])
        self.assertEqual(len(self.lines(done, "OK    ADVISOR n/a (codex)")), 1, done.stdout)
        self.assertEqual(self.lines(done, "OK    no advisor for"), [])


if __name__ == "__main__":
    unittest.main()
