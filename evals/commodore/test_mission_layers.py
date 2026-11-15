"""Tests for `mission.py list` resolving missions over the built-in, user-global, fleet and repo layers."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from crew_world import BASE_PATH
from test_mission_files import ERRORS, MISSION_PY, OK, mission_text

SCRIPTS = MISSION_PY.parent
BUILTIN_DIR = SCRIPTS.parent / "missions"
BUILTIN = {"build", "review", "pr-feedback"}
LAYER_ORDER = ["built-in", "user-global", "fleet", "repo"]
BUILTIN_NAME_WARNING = "builtin-name"
TODAY_KEYS = {
    "name",
    "pick-me-when",
    "source-of-truth",
    "task-force",
    "builder",
    "checker",
    "stop-rule",
    "delivery",
    "file",
    "procedure",
}


class LayerCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="mission-layers-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.tmp = Path(tmp).resolve()
        self.xdg = self.tmp / "xdg"
        self.user_dir = self.xdg / "commodore" / "missions"
        self.repo = self.tmp / "repo"
        self.repo_dir = self.repo / ".commodore" / "missions"
        self.fleet_dir = self.tmp / "fleet"
        self.cwd = self.tmp / "cwd"
        self.cwd.mkdir()

    def run_list(self, *args, env=None, cwd=None, script=MISSION_PY):
        """Run `mission.py list`; `env` overrides the scratch environment, and a None value removes the variable."""
        environ = {"PATH": BASE_PATH, "HOME": str(self.tmp), "LANG": "en_US.UTF-8", "XDG_CONFIG_HOME": str(self.xdg)}
        for key, value in (env or {}).items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        proc = subprocess.run(
            [str(script), "list", *[str(a) for a in args]],
            env=environ,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd or self.cwd,
        )
        self.assertNotIn("Traceback", proc.stderr)
        return proc

    def listed(self, *args, code=OK, **kwargs):
        proc = self.run_list(*args, **kwargs)
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def save(self, directory, name, text=None):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.md"
        path.write_text(mission_text(name) if text is None else text, encoding="utf-8", newline="")
        return path

    def by_name(self, out):
        return {m["name"]: m for m in out["missions"]}


class ResolveTests(LayerCase):
    def test_no_saved_layers_lists_exactly_the_built_ins_with_layer_and_path(self):
        out = self.listed()
        missions = self.by_name(out)
        self.assertEqual(set(missions), BUILTIN)
        self.assertEqual(len(out["missions"]), len(BUILTIN))
        for name, mission in missions.items():
            self.assertEqual(mission["layer"], "built-in")
            self.assertEqual(mission["path"], os.path.join(str(BUILTIN_DIR), f"{name}.md"))
        self.assertEqual(out["warnings"], [])

    def test_user_global_and_repo_missions_list_with_their_layers_and_paths(self):
        self.save(self.user_dir, "deploy")
        self.save(self.repo_dir, "release")
        missions = self.by_name(self.listed("--repo-dir", self.repo))
        self.assertEqual(set(missions), BUILTIN | {"deploy", "release"})
        self.assertEqual(missions["deploy"]["layer"], "user-global")
        self.assertEqual(missions["deploy"]["path"], os.path.join(str(self.user_dir), "deploy.md"))
        self.assertEqual(missions["release"]["layer"], "repo")
        self.assertEqual(
            missions["release"]["path"], os.path.join(str(self.repo), ".commodore", "missions", "release.md")
        )
        self.assertEqual(missions["release"]["file"], "release.md")

    def test_summary_carries_layer_and_path_beside_the_summary_keys(self):
        self.save(self.repo_dir, "release")
        out = self.listed("--summary", "--repo-dir", self.repo)
        release = self.by_name(out)["release"]
        self.assertEqual(
            set(release),
            {"name", "pick-me-when", "builder", "checker", "delivery", "file", "layer", "path"},
        )
        self.assertEqual(release["layer"], "repo")

    def test_inside_admiral_reads_the_fleet_dir_and_not_the_user_global_one(self):
        self.save(self.fleet_dir, "fleetwide")
        self.save(self.user_dir, "personal")
        env = {"ADMIRAL_SHIP": "ship-1", "ADMIRAL_MISSIONS_DIR": str(self.fleet_dir)}
        missions = self.by_name(self.listed(env=env))
        self.assertEqual(set(missions), BUILTIN | {"fleetwide"})
        self.assertEqual(missions["fleetwide"]["layer"], "fleet")
        self.assertEqual(missions["fleetwide"]["path"], os.path.join(str(self.fleet_dir), "fleetwide.md"))

    def test_outside_admiral_ignores_the_fleet_dir(self):
        self.save(self.fleet_dir, "fleetwide")
        env = {"ADMIRAL_SHIP": None, "ADMIRAL_MISSIONS_DIR": str(self.fleet_dir)}
        self.assertEqual(set(self.by_name(self.listed(env=env))), BUILTIN)

    def test_an_empty_admiral_ship_counts_as_outside_admiral(self):
        self.save(self.user_dir, "personal")
        env = {"ADMIRAL_SHIP": "", "ADMIRAL_MISSIONS_DIR": str(self.fleet_dir)}
        self.assertEqual(self.by_name(self.listed(env=env))["personal"]["layer"], "user-global")

    def test_inside_admiral_an_empty_or_unset_missions_dir_gives_no_fleet_layer(self):
        self.save(self.user_dir, "personal")
        for value in ("", None):
            with self.subTest(missions_dir=value):
                env = {"ADMIRAL_SHIP": "ship-1", "ADMIRAL_MISSIONS_DIR": value}
                out = self.listed(env=env)
                self.assertEqual(set(self.by_name(out)), BUILTIN)
                self.assertEqual(out["warnings"], [])

    def test_an_empty_xdg_config_home_counts_as_unset(self):
        self.save(self.tmp / ".config" / "commodore" / "missions", "personal")
        for value in ("", None):
            with self.subTest(xdg=value):
                missions = self.by_name(self.listed(env={"XDG_CONFIG_HOME": value}))
                self.assertEqual(missions["personal"]["layer"], "user-global")

    def test_a_later_saved_layer_replaces_an_earlier_one_of_the_same_name(self):
        self.save(self.user_dir, "deploy", mission_text("deploy", **{"pick-me-when": "From the user layer."}))
        self.save(self.repo_dir, "deploy", mission_text("deploy", **{"pick-me-when": "From the repo layer."}))
        deploys = [m for m in self.listed("--repo-dir", self.repo)["missions"] if m["name"] == "deploy"]
        self.assertEqual([(m["layer"], m["pick-me-when"]) for m in deploys], [("repo", "From the repo layer.")])

    def test_the_repo_is_never_derived_from_the_current_directory(self):
        checkout = self.tmp / "checkout"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
        self.save(checkout / ".commodore" / "missions", "release")
        self.assertEqual(set(self.by_name(self.listed(cwd=checkout))), BUILTIN)

    def test_a_repo_dir_without_saved_missions_adds_nothing_and_is_no_error(self):
        self.repo.mkdir()
        self.assertEqual(set(self.by_name(self.listed("--repo-dir", self.repo))), BUILTIN)

    def test_a_broken_built_in_layer_is_one_unreadable_error(self):
        broken = self.tmp / "install" / "scripts"
        shutil.copytree(SCRIPTS, broken, ignore=shutil.ignore_patterns("__pycache__"))
        out = self.listed(script=broken / "mission.py", code=ERRORS)
        self.assertNotIn("missions", out)
        self.assertEqual(
            [(e["code"], e["file"], e["layer"]) for e in out["errors"]], [("unreadable", None, "built-in")]
        )


class RefusalTests(LayerCase):
    def test_a_valid_saved_mission_named_like_a_built_in_is_dropped_with_a_warning(self):
        cases = [
            ("user-global", self.user_dir, [], "build"),
            ("repo", self.repo_dir, ["--repo-dir", self.repo], "pr-feedback"),
        ]
        for layer, directory, args, name in cases:
            with self.subTest(layer=layer):
                saved = self.save(directory, name, mission_text(name, **{"pick-me-when": "A saved lookalike."}))
                out = self.listed(*args)
                kept = [m for m in out["missions"] if m["name"] == name]
                self.assertEqual([m["layer"] for m in kept], ["built-in"])
                self.assertNotEqual(kept[0]["pick-me-when"], "A saved lookalike.")
                self.assertEqual(len(out["missions"]), len(BUILTIN))
                refused = [w for w in out["warnings"] if w["code"] == BUILTIN_NAME_WARNING]
                self.assertEqual([(w["layer"], w["file"]) for w in refused], [(layer, f"{name}.md")])
                saved.unlink()

    def test_a_broken_saved_mission_named_like_a_built_in_is_an_error(self):
        self.save(self.user_dir, "build", mission_text("build", checker=None))
        out = self.listed(code=ERRORS)
        self.assertNotIn("missions", out)
        self.assertEqual(
            [(e["layer"], e["file"], e["code"]) for e in out["errors"]], [("user-global", "build.md", "no-checker")]
        )


class FileRuleTests(LayerCase):
    def test_a_saved_file_with_bad_frontmatter_fails_the_resolution_with_its_layer(self):
        self.save(self.repo_dir, "release", "no frontmatter here\n")
        out = self.listed("--repo-dir", self.repo, code=ERRORS)
        self.assertNotIn("missions", out)
        self.assertEqual([(e["layer"], e["file"]) for e in out["errors"]], [("repo", "release.md")])

    def test_errors_sort_by_layer_order_first(self):
        self.save(self.repo_dir, "aaa", "no frontmatter here\n")
        self.save(self.user_dir, "zzz", "no frontmatter here\n")
        out = self.listed("--repo-dir", self.repo, code=ERRORS)
        self.assertEqual([e["layer"] for e in out["errors"]], ["user-global", "repo"])

    def test_warnings_sort_by_layer_order_first(self):
        self.save(self.repo_dir, "build")
        self.save(self.user_dir, "review")
        out = self.listed("--repo-dir", self.repo)
        self.assertEqual([w["layer"] for w in out["warnings"]], ["user-global", "repo"])

    def test_a_symlink_to_a_file_outside_the_layer_is_an_outside_layer_error(self):
        outside = self.save(self.tmp / "elsewhere", "deploy")
        self.user_dir.mkdir(parents=True)
        (self.user_dir / "deploy.md").symlink_to(outside)
        out = self.listed(code=ERRORS)
        self.assertEqual(
            [(e["layer"], e["file"], e["code"]) for e in out["errors"]], [("user-global", "deploy.md", "outside-layer")]
        )

    def test_a_symlink_to_a_regular_file_inside_the_layer_is_listed(self):
        self.save(self.user_dir / "sub", "ship")
        (self.user_dir / "ship.md").symlink_to("sub/ship.md")
        out = self.listed()
        self.assertEqual(self.by_name(out)["ship"]["layer"], "user-global")

    def test_a_symlinked_layer_directory_is_read(self):
        self.save(self.tmp / "real-missions", "deploy")
        self.user_dir.parent.mkdir(parents=True)
        self.user_dir.symlink_to(self.tmp / "real-missions")
        missions = self.by_name(self.listed())
        self.assertEqual(missions["deploy"]["layer"], "user-global")
        self.assertEqual(missions["deploy"]["path"], os.path.join(str(self.user_dir), "deploy.md"))

    def test_names_that_are_not_lowercase_md_files_are_ignored(self):
        self.save(self.user_dir, "deploy")
        for name in ("notes.txt", "SHOUT.MD", ".hidden.md"):
            (self.user_dir / name).write_text("not a mission\n", encoding="utf-8")
        (self.user_dir / "nested.md").mkdir()
        self.save(self.user_dir / "sub", "inner")
        out = self.listed()
        self.assertEqual(set(self.by_name(out)), BUILTIN | {"deploy"})
        self.assertEqual(out["warnings"], [])

    def test_a_missing_saved_layer_directory_is_an_empty_layer(self):
        out = self.listed("--repo-dir", self.tmp / "no-such-repo")
        self.assertEqual(set(self.by_name(out)), BUILTIN)

    def test_a_saved_layer_directory_that_cannot_be_listed_is_one_unreadable_error(self):
        self.save(self.user_dir, "deploy")
        self.user_dir.chmod(0)
        self.addCleanup(self.user_dir.chmod, 0o755)
        if os.access(self.user_dir, os.R_OK):
            self.skipTest("permissions are not enforced for this user")
        out = self.listed(code=ERRORS)
        self.assertEqual(
            [(e["layer"], e["file"], e["code"]) for e in out["errors"]], [("user-global", None, "unreadable")]
        )


class DirTests(LayerCase):
    def test_dir_lists_only_that_directory_with_todays_keys(self):
        only = self.tmp / "only"
        self.save(only, "deploy")
        self.save(self.user_dir, "personal")
        out = self.listed("--dir", only)
        self.assertEqual(set(out), {"missions", "warnings"})
        self.assertEqual(len(out["missions"]), 1)
        self.assertEqual(set(out["missions"][0]), TODAY_KEYS)
        self.assertEqual(out["missions"][0]["name"], "deploy")


if __name__ == "__main__":
    unittest.main()
