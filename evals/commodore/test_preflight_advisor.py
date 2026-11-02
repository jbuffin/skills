"""Tests for team-preflight.sh's advisor check under the same-family rule (issue #168): a model in the same family as
ADVISOR starts no probe and gets one `OK ... no advisor for <model> (<roles>): same family as ADVISOR=..., by design`
line; every other model probes as today; ADVISOR=none and a harness with no probe behave as today.

Seam: team-preflight.sh as a subprocess against a hand-written team.env, with ADVISOR_PROBE set to a stub that appends
`<run-dir> <model>` to a log and answers `ADVISOR ON <model>`. Expected behaviour comes from the Agent Brief on #168.

Traps the setup avoids:
- CLAUDECODE=1 is passed. Without it detect-harness.sh prints nothing, the preflight clears its harness check, no
  probe starts, and every "no probe" assertion would pass without testing anything. Each such test also asserts a
  companion: the by-design OK line, or the probe a different model did start.
- REPO is a git checkout with user.email set and REQUIRED_TOOLS=git, so the generic checks don't FAIL for an unrelated
  reason and "completes" can mean exit 0.

Run from the repo root: python3 -m unittest evals/commodore/test_preflight_advisor.py -v
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CO_SCRIPTS = REPO / "skills" / "engineering" / "commodore" / "scripts"
PREFLIGHT = CO_SCRIPTS / "team-preflight.sh"

# The roles and models team-init.sh writes for Claude, in its order.
DEFAULT_ROLES = [
    "MODEL_BRIEF_CHECKER=opus",
    "MODEL_TEST_WRITER=sonnet",
    "MODEL_IMPLEMENTER=sonnet",
    "MODEL_REVIEWER=opus",
    "MODEL_SECURITY_REVIEWER=opus",
    "MODEL_TRIAGER=opus",
    "MODEL_TARGET_STEWARD=sonnet",
    "MODEL_SCRIBE=sonnet",
]
OPUS_ROLES = ["brief-checker", "reviewer", "security-reviewer", "triager"]

# The claude driver's own preflight needs `claude` on PATH and `claude agents --json` to succeed.
FAKE_CLAUDE = """#!/bin/sh
[ "$1" = agents ] && echo "[]"
exit 0
"""

STUB = """#!/bin/sh
printf '%s %s\\n' "$1" "$2" >> "$PROBE_LOG"
echo "ADVISOR ON $2"
"""


class PreflightCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.team = self.root / "team"
        self.team.mkdir()
        self.repo = self.root / "checkout"
        self.repo.mkdir()
        git = ["git", "-C", str(self.repo)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "config", "user.email", "test@example.com"], check=True)
        subprocess.run([*git, "config", "user.name", "Test"], check=True)
        self.log = self.root / "probe.log"
        self.stub = self.root / "probe-stub"
        self.stub.write_text(STUB)
        self.stub.chmod(0o755)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "claude"
        fake.write_text(FAKE_CLAUDE)
        fake.chmod(0o755)

    def team_env(self, *lines, model="sonnet", advisor="opus", roles=DEFAULT_ROLES, harness="claude"):
        body = [
            f"HARNESS={harness}",
            f"REPO={self.repo}",
            "REQUIRED_TOOLS=git",
            "MODE=single",
            f"MODEL={model}",
            f"ADVISOR={advisor}",
            "REQUIRE_ROLE=1",
            *roles,
            *lines,
        ]
        (self.team / "team.env").write_text("\n".join(body) + "\n")

    def run_preflight(self, probe=True, claudecode="1", **extra):
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin",
            "HOME": str(self.home),
            "LANG": "en_US.UTF-8",
            "PROBE_LOG": str(self.log),
            "CLAUDECODE": claudecode,
        }
        if not claudecode:
            del env["CLAUDECODE"]
        if probe:
            env["ADVISOR_PROBE"] = str(self.stub)
        env.update(extra)
        return subprocess.run(
            [str(PREFLIGHT), str(self.team)],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def probed(self):
        """(run-dir, model) for every probe the stub logged, sorted."""
        if not self.log.exists():
            return []
        return sorted(tuple(line.split(" ", 1)) for line in self.log.read_text().splitlines())

    def lines(self, done, prefix):
        return [line for line in done.stdout.splitlines() if line.startswith(prefix)]

    def by_design(self, done, model):
        return [line for line in done.stdout.splitlines() if f"no advisor for {model} " in line]

    def assert_by_design_line(self, done, model, roles, advisor="opus"):
        found = self.by_design(done, model)
        self.assertEqual(len(found), 1, f"expected one by-design line for {model}:\n{done.stdout}")
        line = found[0]
        self.assertTrue(line.startswith("OK "), line)
        self.assertIn(f"same family as ADVISOR={advisor}", line)
        self.assertIn("by design", line)
        for role in roles:
            self.assertIn(role, line)

    def assert_no_off_warning(self, done):
        self.assertNotIn("ADVISOR OFF", done.stdout)
        self.assertNotIn("ADVISOR OFF", done.stderr)


class TestDefaultClaudeTeamEnv(PreflightCase):
    def test_default_team_env_probes_sonnet_once_and_opus_never(self):
        self.team_env()
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.probed(), [(str(self.team), "sonnet")])
        # companion: the probe ran and its result was reported, so the "no Opus probe" above isn't a skipped check
        self.assertEqual(len(self.lines(done, "OK    advisor on for sonnet")), 1, done.stdout)
        self.assert_by_design_line(done, "opus", OPUS_ROLES)
        self.assert_no_off_warning(done)

    def test_one_probe_per_non_opus_model_none_for_opus(self):
        # distinct non-Opus models, including a suffixed name and a full name, and the Opus roles
        self.team_env(
            "MODEL_SCRIBE=haiku",
            "MODEL_TARGET_STEWARD=sonnet[1m]",
            "MODEL_TRIAGER=claude-opus-5.5",
        )
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            self.probed(),
            sorted((str(self.team), m) for m in ("sonnet", "haiku", "sonnet[1m]")),
        )
        self.assertEqual(len(self.lines(done, "OK    advisor on for ")), 3, done.stdout)
        # both spellings of Opus get a by-design line, none of them a probe
        self.assert_by_design_line(done, "opus", ["brief-checker", "reviewer", "security-reviewer"])
        self.assert_by_design_line(done, "claude-opus-5.5", ["triager"])
        self.assert_no_off_warning(done)

    def test_results_stay_paired_with_their_models_when_a_same_family_model_comes_first(self):
        # the loops pair models with result files by index: an Opus model ahead of the probed ones must not shift them
        self.team_env(model="opus", roles=["MODEL_REVIEWER=opus", "MODEL_SCRIBE=haiku", "MODEL_IMPLEMENTER=sonnet"])
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.probed(), sorted([(str(self.team), "haiku"), (str(self.team), "sonnet")]))
        self.assertEqual(len(self.lines(done, "OK    advisor on for haiku")), 1, done.stdout)
        self.assertEqual(len(self.lines(done, "OK    advisor on for sonnet")), 1, done.stdout)
        self.assert_by_design_line(done, "opus", ["default", "reviewer"])
        self.assert_no_off_warning(done)

    def test_mixed_case_advisor_matches_a_lowercase_model(self):
        self.team_env(advisor="OPUS")
        done = self.run_preflight()
        self.assertEqual(self.probed(), [(str(self.team), "sonnet")])
        self.assertEqual(len(self.lines(done, "OK    advisor on for sonnet")), 1, done.stdout)
        self.assert_by_design_line(done, "opus", OPUS_ROLES, advisor="OPUS")
        self.assert_no_off_warning(done)


class TestAllSameFamily(PreflightCase):
    ALL_OPUS = (
        "MODEL_BRIEF_CHECKER=opus",
        "MODEL_TEST_WRITER=opus",
        "MODEL_IMPLEMENTER=opus",
        "MODEL_REVIEWER=opus",
        "MODEL_SECURITY_REVIEWER=opus",
        "MODEL_TRIAGER=opus",
        "MODEL_TARGET_STEWARD=opus",
        "MODEL_SCRIBE=opus",
    )

    def test_all_opus_team_env_starts_no_probes_and_completes(self):
        self.team_env(model="opus", roles=list(self.ALL_OPUS))
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.probed(), [])
        # companions: the by-design line shows the advisor check ran, and a later generic check shows the run completed
        self.assert_by_design_line(done, "opus", ["default", "brief-checker", "scribe"])
        self.assertTrue(self.lines(done, "OK    git found"), done.stdout)
        self.assert_no_off_warning(done)

    def test_all_same_family_across_spellings_starts_no_probes(self):
        self.team_env(model="claude-opus-5.5", roles=["MODEL_REVIEWER=Opus", "MODEL_SCRIBE=opus[1m]"])
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.probed(), [])
        self.assertEqual(len(self.by_design(done, "claude-opus-5.5")), 1, done.stdout)
        self.assertEqual(len(self.by_design(done, "Opus")), 1, done.stdout)
        self.assertEqual(len(self.by_design(done, "opus[1m]")), 1, done.stdout)
        self.assert_no_off_warning(done)

    def test_advisor_sonnet_with_sonnet_only_team_env_starts_no_probes(self):
        self.team_env(model="sonnet", advisor="sonnet", roles=["MODEL_IMPLEMENTER=sonnet[1m]"])
        done = self.run_preflight()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.probed(), [])
        self.assert_by_design_line(done, "sonnet", ["default"], advisor="sonnet")
        self.assert_by_design_line(done, "sonnet[1m]", ["implementer"], advisor="sonnet")
        self.assert_no_off_warning(done)


class TestStillProbed(PreflightCase):
    """Behaviour that stays as it is."""

    def test_fable_model_with_advisor_opus_still_probes(self):
        self.team_env(roles=["MODEL_REVIEWER=fable"])
        done = self.run_preflight()
        self.assertEqual(self.probed(), sorted([(str(self.team), "sonnet"), (str(self.team), "fable")]))
        self.assertEqual(len(self.lines(done, "OK    advisor on for fable")), 1, done.stdout)
        self.assertEqual(self.by_design(done, "fable"), [])

    def test_opus_model_with_advisor_haiku_still_probes(self):
        self.team_env(model="opus", advisor="haiku", roles=["MODEL_REVIEWER=opus"])
        done = self.run_preflight()
        self.assertEqual(self.probed(), [(str(self.team), "opus")])
        self.assertEqual(self.by_design(done, "opus"), [])

    def test_unrecognised_advisor_still_probes_every_model(self):
        self.team_env(advisor="mystery", roles=["MODEL_REVIEWER=opus"])
        done = self.run_preflight()
        self.assertEqual(self.probed(), sorted([(str(self.team), "sonnet"), (str(self.team), "opus")]))
        self.assertEqual(self.lines(done, "OK    no advisor for"), [])

    def test_unrecognised_model_still_probes(self):
        self.team_env(roles=["MODEL_REVIEWER=gpt-9"])
        done = self.run_preflight()
        self.assertEqual(self.probed(), sorted([(str(self.team), "sonnet"), (str(self.team), "gpt-9")]))
        self.assertEqual(self.lines(done, "OK    no advisor for"), [])

    def test_off_result_for_a_probed_model_still_warns(self):
        # the OFF warning stays for a model that should have the advisor: only same-family models drop out of it
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
