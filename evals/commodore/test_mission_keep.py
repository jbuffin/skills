"""Tests for `mission.py keep`: saving a run's ad hoc mission file into the user-global or repo layer."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from crew_world import BASE_PATH
from test_mission_files import ERRORS, MISSION_PY, OK, USAGE, mission_text

REFUSED = ERRORS


class KeepCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="mission-keep-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.tmp = Path(tmp).resolve()
        self.xdg = self.tmp / "xdg"
        self.user_dir = self.xdg / "commodore" / "missions"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.repo_dir = self.repo / ".commodore" / "missions"
        self.worktree = self.tmp / "worktree"
        self.worktree.mkdir()
        self.run_dir = self.tmp / "run"
        self.missions = self.run_dir / "missions"
        self.missions.mkdir(parents=True)
        self.cwd = self.tmp / "cwd"
        self.cwd.mkdir()
        self.team_env()

    def team_env(self, *extra, repo=None):
        lines = [f"REPO={repo or self.repo}", f"WORKTREE={self.worktree}", *extra]
        (self.run_dir / "team.env").write_text("\n".join(lines) + "\n")

    def mission_file(self, name="docs-audit", text=None, filename=None):
        path = self.missions / (filename or f"{name}.md")
        path.write_text(mission_text(name) if text is None else text, encoding="utf-8", newline="")
        return path

    def env(self, extra=None, xdg=None):
        environ = {"PATH": BASE_PATH, "HOME": str(self.tmp), "LANG": "en_US.UTF-8"}
        environ["XDG_CONFIG_HOME"] = str(self.xdg if xdg is None else xdg)
        for key, value in (extra or {}).items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        return environ

    def mission(self, *args, env=None, xdg=None):
        proc = subprocess.run(
            [str(MISSION_PY), *[str(a) for a in args]],
            env=self.env(env, xdg),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            cwd=self.cwd,
        )
        self.assertNotIn("Traceback", proc.stderr)
        return proc

    def keep(self, path, layer, *, env=None, xdg=None):
        return self.mission("keep", "--run", self.run_dir, "--file", path, "--layer", layer, env=env, xdg=xdg)

    def assertRefused(self, proc):
        self.assertEqual(proc.returncode, REFUSED, proc.stdout + proc.stderr)
        self.assertTrue(
            any(line.startswith("ERROR") for line in (proc.stdout + proc.stderr).splitlines()),
            proc.stdout + proc.stderr,
        )

    def written(self):
        """Every file under the user-global and repo layer roots, so a refusal can prove nothing was written."""
        found = []
        for root in (self.xdg, self.repo / ".commodore", self.worktree / ".commodore"):
            if root.exists():
                found += [str(p) for p in root.rglob("*") if p.is_file()]
        return sorted(found)

    def listed(self, *args):
        proc = self.mission("list", *args)
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        return {m["name"]: m for m in json.loads(proc.stdout)["missions"]}


class TestKeepWrites(KeepCase):
    def test_keeping_into_user_global_writes_the_file_and_list_shows_it(self):
        src = self.mission_file()
        proc = self.keep(src, "user-global")
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        target = self.user_dir / "docs-audit.md"
        self.assertIn(f"wrote {target}", proc.stdout.splitlines())
        self.assertEqual(target.read_bytes(), src.read_bytes())
        self.assertEqual(self.listed()["docs-audit"]["layer"], "user-global")

    def test_keeping_into_repo_writes_under_the_checkout_and_list_shows_it(self):
        src = self.mission_file()
        proc = self.keep(src, "repo")
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        target = self.repo_dir / "docs-audit.md"
        self.assertIn(f"wrote {target}", proc.stdout.splitlines())
        self.assertEqual(target.read_bytes(), src.read_bytes())
        self.assertEqual(self.listed("--repo-dir", self.repo)["docs-audit"]["layer"], "repo")
        self.assertFalse(self.worktree.joinpath(".commodore").exists(), "the repo is team.env's REPO, not WORKTREE")

    def test_a_keep_leaves_no_temp_file_beside_the_saved_one(self):
        self.keep(self.mission_file(), "user-global")
        self.assertEqual([Path(p).name for p in self.written()], ["docs-audit.md"])


class TestKeepRefusals(KeepCase):
    def assertNothingWritten(self, proc):
        self.assertRefused(proc)
        self.assertEqual(self.written(), [])

    def test_a_built_in_name_is_refused(self):
        self.assertNothingWritten(self.keep(self.mission_file("build"), "user-global"))

    def test_a_name_the_target_layer_already_holds_is_refused_and_the_file_kept(self):
        src = self.mission_file()
        for layer, directory in (("user-global", self.user_dir), ("repo", self.repo_dir)):
            with self.subTest(layer=layer):
                directory.mkdir(parents=True, exist_ok=True)
                existing = directory / "docs-audit.md"
                existing.write_bytes(b"keep me\n")
                self.assertRefused(self.keep(src, layer))
                self.assertEqual(existing.read_bytes(), b"keep me\n")
                self.assertEqual([p.name for p in directory.iterdir()], ["docs-audit.md"])

    def test_a_name_held_by_the_other_layer_is_not_a_clash(self):
        self.user_dir.mkdir(parents=True)
        (self.user_dir / "docs-audit.md").write_text(mission_text("docs-audit"), encoding="utf-8")
        proc = self.keep(self.mission_file(), "repo")
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)

    def test_an_invalid_file_is_refused(self):
        self.assertNothingWritten(self.keep(self.mission_file(text=mission_text("docs-audit", builder=None)), "repo"))

    def test_a_stem_that_differs_from_the_name_is_refused(self):
        src = self.mission_file("docs-audit", filename="other-name.md")
        self.assertNothingWritten(self.keep(src, "user-global"))

    def test_inside_admiral_is_refused_from_team_env_and_from_the_environment(self):
        src = self.mission_file()
        with self.subTest(source="team.env"):
            self.team_env("ADMIRAL_SHIP=ship-1")
            self.assertNothingWritten(self.keep(src, "user-global"))
        with self.subTest(source="environment"):
            self.team_env()
            self.assertNothingWritten(self.keep(src, "repo", env={"ADMIRAL_SHIP": "ship-1"}))

    def test_a_file_outside_the_runs_missions_directory_is_refused(self):
        outside = self.tmp / "docs-audit.md"
        outside.write_text(mission_text("docs-audit"), encoding="utf-8")
        in_run = self.run_dir / "docs-audit.md"
        in_run.write_text(mission_text("docs-audit"), encoding="utf-8")
        for path in (outside, in_run):
            with self.subTest(path=str(path)):
                self.assertNothingWritten(self.keep(path, "user-global"))

    def test_a_symlink_in_missions_that_points_outside_is_refused(self):
        real = self.tmp / "docs-audit.md"
        real.write_text(mission_text("docs-audit"), encoding="utf-8")
        link = self.missions / "docs-audit.md"
        link.symlink_to(real)
        self.assertNothingWritten(self.keep(link, "user-global"))

    def test_a_file_that_is_not_regular_is_refused(self):
        fifo = self.missions / "docs-audit.md"
        os.mkfifo(fifo)
        self.assertNothingWritten(self.keep(fifo, "user-global"))


class TestKeepTargetPaths(KeepCase):
    def assertNothingWritten(self, proc):
        self.assertRefused(proc)
        self.assertEqual(self.written(), [])

    def test_a_symlinked_commodore_or_missions_directory_in_user_global_is_refused(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        src = self.mission_file()
        with self.subTest(link="commodore"):
            self.xdg.mkdir()
            (self.xdg / "commodore").symlink_to(elsewhere)
            self.assertNothingWritten(self.keep(src, "user-global"))
            self.assertEqual(list(elsewhere.rglob("*")), [])
        with self.subTest(link="missions"):
            (self.xdg / "commodore").unlink(missing_ok=True)
            (self.xdg / "commodore").mkdir(parents=True, exist_ok=True)
            (self.xdg / "commodore" / "missions").symlink_to(elsewhere)
            self.assertNothingWritten(self.keep(src, "user-global"))
            self.assertEqual(list(elsewhere.rglob("*")), [])

    def test_a_user_global_directory_inside_the_repo_or_worktree_is_refused(self):
        src = self.mission_file()
        for root in (self.repo, self.worktree):
            with self.subTest(root=root.name):
                self.assertNothingWritten(self.keep(src, "user-global", xdg=root / "cfg"))

    def test_a_user_global_directory_inside_a_dot_commodore_directory_is_refused(self):
        src = self.mission_file()
        xdg = self.tmp / ".commodore" / "cfg"
        self.assertRefused(self.keep(src, "user-global", xdg=xdg))
        self.assertEqual([p for p in xdg.rglob("*") if p.is_file()] if xdg.exists() else [], [])

    def test_a_symlinked_dot_commodore_or_missions_directory_in_the_repo_is_refused(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        src = self.mission_file()
        with self.subTest(link=".commodore"):
            (self.repo / ".commodore").symlink_to(elsewhere)
            self.assertNothingWritten(self.keep(src, "repo"))
            self.assertEqual(list(elsewhere.rglob("*")), [])
        with self.subTest(link="missions"):
            (self.repo / ".commodore").unlink(missing_ok=True)
            (self.repo / ".commodore").mkdir(exist_ok=True)
            (self.repo / ".commodore" / "missions").symlink_to(elsewhere)
            self.assertNothingWritten(self.keep(src, "repo"))
            self.assertEqual(list(elsewhere.rglob("*")), [])

    def test_a_repo_that_does_not_exist_is_refused_and_not_created(self):
        gone = self.tmp / "gone"
        self.team_env(repo=gone)
        self.assertNothingWritten(self.keep(self.mission_file(), "repo"))
        self.assertFalse(gone.exists())

    def test_a_symlink_to_a_directory_inside_the_repo_is_still_refused(self):
        inside = self.repo / "real-missions"
        inside.mkdir()
        (self.repo / ".commodore").mkdir()
        (self.repo / ".commodore" / "missions").symlink_to(inside)
        self.assertNothingWritten(self.keep(self.mission_file(), "repo"))
        self.assertEqual(list(inside.iterdir()), [])


class TestKeepUsage(KeepCase):
    def test_a_missing_run_or_file_or_an_unknown_layer_is_a_usage_error(self):
        src = self.mission_file()
        cases = {
            "no --run": ["keep", "--file", src, "--layer", "repo"],
            "no --file": ["keep", "--run", self.run_dir, "--layer", "repo"],
            "unknown layer": ["keep", "--run", self.run_dir, "--file", src, "--layer", "fleet"],
        }
        for label, argv in cases.items():
            with self.subTest(case=label):
                proc = self.mission(*argv)
                self.assertEqual(proc.returncode, USAGE, proc.stdout + proc.stderr)
                self.assertEqual(self.written(), [])


if __name__ == "__main__":
    unittest.main()
