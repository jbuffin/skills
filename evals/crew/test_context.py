"""What crew's context.sh prints and exits with for a repo, a fence, a ship and an autopilot setting."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "skills" / "engineering" / "crew" / "scripts" / "context.sh"
KEYS = ["fenced", "teammate", "ship", "autopilot", "top"]
OK, USAGE = 0, 5


class ContextCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True, env=self.env())
        self.sub = self.repo / "src" / "deep"
        self.sub.mkdir(parents=True)
        self.plain = self.tmp / "plain"
        self.plain.mkdir()

    def env(self, **extra):
        base = {k: v for k, v in os.environ.items() if not k.startswith(("ADMIRAL_", "GIT_"))}
        base.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
        base.update(extra)
        return base

    def run_script(self, cwd=None, args=(), autopilot=None, ship=None):
        extra = {}
        if autopilot is not None:
            extra["ADMIRAL_AUTOPILOT"] = autopilot
        if ship is not None:
            extra["ADMIRAL_SHIP"] = ship
        self.assertTrue(SCRIPT.is_file(), f"missing {SCRIPT}")
        return subprocess.run(
            [str(SCRIPT), *args],
            cwd=cwd or self.repo,
            env=self.env(**extra),
            capture_output=True,
            text=True,
            check=False,
        )

    def facts(self, **kw):
        done = self.run_script(**kw)
        self.assertEqual(done.returncode, OK, done.stderr)
        lines = done.stdout.splitlines()
        self.assertEqual([ln.split(":", 1)[0] for ln in lines], KEYS, done.stdout)
        return {ln.split(":", 1)[0]: ln.split(":", 1)[1].removeprefix(" ") for ln in lines}

    def fence(self):
        return self.repo / ".admiral" / "untrusted"


class TestFence(ContextCase):
    def test_repo_without_untrusted_is_not_fenced(self):
        self.assertEqual(self.facts()["fenced"], "no")

    def test_untrusted_directory_with_files_fences(self):
        self.fence().mkdir(parents=True)
        (self.fence() / "event.md").write_text("event\n")
        self.assertEqual(self.facts()["fenced"], "yes")

    def test_empty_untrusted_directory_fences(self):
        self.fence().mkdir(parents=True)
        self.assertEqual(self.facts()["fenced"], "yes")

    def test_untrusted_file_fences(self):
        self.fence().parent.mkdir()
        self.fence().write_text("x\n")
        self.assertEqual(self.facts()["fenced"], "yes")

    def test_dangling_untrusted_symlink_fences(self):
        self.fence().parent.mkdir()
        self.fence().symlink_to(self.tmp / "missing")
        self.assertEqual(self.facts()["fenced"], "yes")

    def test_fence_is_found_from_a_subdirectory(self):
        self.fence().mkdir(parents=True)
        facts = self.facts(cwd=self.sub)
        self.assertEqual((facts["fenced"], facts["top"]), ("yes", str(self.repo)))

    def test_admiral_dir_without_untrusted_is_not_fenced(self):
        (self.repo / ".admiral").mkdir()
        self.assertEqual(self.facts()["fenced"], "no")

    def test_non_repo_fails_closed_with_empty_top(self):
        facts = self.facts(cwd=self.plain)
        self.assertEqual((facts["fenced"], facts["top"]), ("yes", ""))


class TestTop(ContextCase):
    def test_top_is_the_repo_top_level_from_a_subdirectory(self):
        self.assertEqual(self.facts(cwd=self.sub)["top"], str(self.repo))


class TestShipAndAutopilot(ContextCase):
    def test_no_environment_is_all_no(self):
        facts = self.facts()
        self.assertEqual((facts["ship"], facts["autopilot"], facts["teammate"]), ("no", "no", "no"))

    def test_non_empty_ship_is_yes(self):
        self.assertEqual(self.facts(ship="ship-1")["ship"], "yes")

    def test_empty_ship_is_no(self):
        self.assertEqual(self.facts(ship="")["ship"], "no")

    def test_autopilot_only_exactly_one_is_yes(self):
        for value, want in [("1", "yes"), ("0", "no"), ("true", "no"), ("", "no"), (None, "no")]:
            with self.subTest(autopilot=value):
                self.assertEqual(self.facts(autopilot=value)["autopilot"], want)


class TestTeammate(ContextCase):
    def test_autopilot_without_a_ship_is_a_teammate(self):
        self.assertEqual(self.facts(autopilot="1")["teammate"], "yes")

    def test_autopilot_with_empty_ship_is_a_teammate(self):
        self.assertEqual(self.facts(autopilot="1", ship="")["teammate"], "yes")

    def test_autopilot_on_a_ship_is_not_a_teammate(self):
        self.assertEqual(self.facts(autopilot="1", ship="ship-1")["teammate"], "no")

    def test_ship_without_autopilot_is_not_a_teammate(self):
        self.assertEqual(self.facts(ship="ship-1")["teammate"], "no")

    def test_autopilot_other_than_one_is_not_a_teammate(self):
        for value in ("0", "true", ""):
            with self.subTest(autopilot=value):
                self.assertEqual(self.facts(autopilot=value)["teammate"], "no")


class TestOutput(ContextCase):
    def test_prints_five_lines_in_order_with_exact_values(self):
        done = self.run_script(cwd=self.sub, autopilot="1", ship="ship-1")
        self.assertEqual(done.returncode, OK, done.stderr)
        self.assertEqual(
            done.stdout,
            f"fenced: no\nteammate: no\nship: yes\nautopilot: yes\ntop: {self.repo}\n",
        )

    def test_non_repo_prints_an_empty_top_line(self):
        done = self.run_script(cwd=self.plain)
        self.assertEqual(done.stdout.splitlines()[-1].rstrip(), "top:")


class TestUsage(ContextCase):
    def test_any_argument_prints_usage_and_exits_5(self):
        for args in (["x"], ["--help"], ["a", "b"]):
            with self.subTest(args=args):
                done = self.run_script(args=args)
                self.assertEqual(done.returncode, USAGE, done.stderr)
                self.assertTrue(done.stdout.startswith("usage:"), done.stdout)
                self.assertNotIn("fenced:", done.stdout)


if __name__ == "__main__":
    unittest.main()
