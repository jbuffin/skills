"""Tests for ad hoc crew members (issue #199, unit u4): `crew.py adhoc` writes one, `resolve` and `cast` see it only in
the run that wrote it.

Seams: `crew.py resolve --run`, `crew.py cast --run` and `crew.py adhoc` as subprocesses in temp worlds
(evals/commodore/crew_world.py): stdout JSON, the cast table, stderr lines, exit codes, and which files exist with what
content. Expected values come from the unit spec (issue #199, docs/adr/0007, the u4 spec sections 1 to 4 and the rulings
of section 9), never from running the code. `XDG_CONFIG_HOME` and `ADMIRAL_CREW_DIR` always point into the temp world.

The run id is the real path of the run directory (ruling 1). A refusal means exit 1, one `ERROR` line and a world
that is byte for byte what it was before (`snapshot`), so "nothing written" covers the temp file, the directory and
the body file too.

Run from the repo root: python3 -m unittest discover -s evals/commodore -p 'test_crew_adhoc.py' -v
"""

import json
import os
import re
import subprocess
import unittest
from pathlib import Path

from crew_world import HEADER, REPO, WorldCase, is_root, parse_table

COMMODORE = REPO / "skills" / "engineering" / "commodore"
MAX_BYTES = 65536
BAD_MODELS = ["-bad", "has space", "a$b", 'a"b', "a`b", "a" * 129, "'quoted'"]
FULL_KEYS = ["name", "role", "based-on", "pick-me-when", "skills", "model", "harness", "ad-hoc", "ad-hoc-run"]
MINIMAL_KEYS = ["name", "role", "pick-me-when", "skills", "ad-hoc", "ad-hoc-run"]
TRICKY = 'He said "hi" \\ then: a # b'
TRICKY_BODY = 'Line one: "quoted" \\ back\n---\n# heading: still body\n\ncafé ✓ $(not run)'


class AdHocCase(WorldCase):
    def setUp(self):
        super().setUp()
        self.run_id = str(self.w.run)  # the world's root is a real path, so this is the run's real path
        self.user_crew = self.w.xdg / "commodore" / "crew"
        self.user_ad_hoc = self.user_crew / "ad-hoc"
        self.fleet = self.w.layer_dirs["fleet"]
        self.fleet_ad_hoc = self.fleet / "ad-hoc"

    def builtin_names(self):
        """The nine members under skills/engineering/commodore/crew/ (the built-in layer)."""
        return {
            "brief-checker",
            "fix-checker",
            "implementer",
            "reviewer",
            "scribe",
            "security-reviewer",
            "target-steward",
            "test-writer",
            "triager",
        }

    # ------------------------------------------------------------------------------------------ files
    def ad_hoc_text(self, name, role, **opts):
        """Member text; opts: run (default this run), extra (frontmatter lines), body, flag (write `ad-hoc: true`)."""
        run = opts.get("run") or self.run_id
        body = opts.get("body", "Ad hoc body.")
        head = f"---\nname: {name}\nrole: {role}\npick-me-when: Pick {name}.\n{opts.get('extra', '')}"
        head += ("ad-hoc: true\n" if opts.get("flag", True) else "") + f'ad-hoc-run: "{run}"\n---\n'
        return head + (f"\n{body}\n" if body else "")

    def put_ad_hoc(self, name, role="scribe", directory=None, **kw):
        directory = directory or self.user_ad_hoc
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.md"
        path.write_text(self.ad_hoc_text(name, role, **kw), encoding="utf-8")
        return path

    def other_run(self, name="run-b", parent=None):
        """A second run directory, with its own team.env, that shares the user-global and fleet directories."""
        run = (parent or self.w.root) / name
        run.mkdir(parents=True)
        (run / "team.env").write_text(f"HARNESS=claude\nREPO={self.w.repo}\n")
        return run

    def body_file(self, text="Write the release notes.", name="body.md", raw=None):
        prompts = self.w.run / "prompts"
        prompts.mkdir(exist_ok=True)
        path = prompts / name
        path.write_bytes(raw if raw is not None else text.encode("utf-8"))
        return path

    def snapshot(self):
        """Every path under the world (but the copied skills) with its kind and content: what a refusal must keep."""
        out = {}
        for top, dirs, files in os.walk(self.w.root):
            if Path(top) == self.w.root:
                dirs[:] = [d for d in dirs if d != "skills"]
            for name in dirs + files:
                path = Path(top, name)
                rel = str(path.relative_to(self.w.root))
                if path.is_symlink():
                    out[rel] = ("link", os.readlink(path))
                elif path.is_dir():
                    out[rel] = ("dir", path.stat().st_mode & 0o777)
                else:
                    out[rel] = ("file", path.read_bytes(), path.stat().st_mode & 0o777)
        return out

    # ------------------------------------------------------------------------------------------ running
    def resolve(self, run=None, env=None):
        done = self.w.sh([self.w.crew_py, "resolve", "--run", run or self.w.run], env=env)
        return done, (json.loads(done.stdout) if done.stdout.strip() else None)

    def listed(self, run=None, env=None):
        done, parsed = self.resolve(run, env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return {m["name"]: m for m in parsed["members"]}, parsed["warnings"]

    def adhoc_args(self, **kw):
        """The arguments of a valid call; a keyword replaces a value, None drops the flag, a list repeats it."""
        opts = {
            "run": self.w.run,
            "name": "notes-writer",
            "role": "scribe",
            "pick-me-when": "Use for the release notes.",
            "body-file": self.body_file(),
        }
        opts.update({k.replace("_", "-"): v for k, v in kw.items()})
        args = []
        for key, value in opts.items():
            for item in value if isinstance(value, list) else [value]:
                if item is not None:
                    args += [f"--{key}", str(item)]
        return args

    def adhoc(self, env=None, **kw):
        return self.w.sh([self.w.crew_py, "adhoc", *self.adhoc_args(**kw)], env=env)

    def errors(self, done):
        return [ln for ln in done.stderr.splitlines() if ln.startswith("ERROR")]

    def assert_refused(self, label, env=None, code=1, **kw):
        """The call exits `code`, says one ERROR line (a usage error says its usage), prints nothing to stdout and
        leaves the world exactly as it was."""
        before = self.snapshot()
        done = self.adhoc(env=env, **kw)
        self.assertEqual(done.returncode, code, f"{label}: {done.stderr}")
        self.assertEqual(done.stdout, "", label)
        if code == 1:
            self.assertEqual(len(self.errors(done)), 1, f"{label}: {done.stderr}")
        else:
            self.assertTrue(done.stderr.strip(), f"{label}: no usage message")
        self.assertEqual(self.snapshot(), before, f"{label}: the world changed")
        return done

    def read_member_file(self, path):
        """(frontmatter keys in file order, {key: raw value text}, body text after the closing --- line)."""
        lines = Path(path).read_text(encoding="utf-8").split("\n")
        self.assertEqual(lines[0], "---")
        end = lines.index("---", 1)
        pairs = [ln.split(": ", 1) if ": " in ln else [ln.rstrip(":"), ""] for ln in lines[1:end]]
        return [k for k, _ in pairs], {k: v for k, v in pairs}, "\n".join(lines[end + 1 :])


# ---------------------------------------------------------------------------------------------------- resolve
class ResolveOnlyForTheRunThatMadeIt(AdHocCase):
    def test_run_a_lists_its_ad_hoc_member_outside_admiral(self):
        self.put_ad_hoc("helper")
        members, warnings = self.listed()
        self.assertEqual(warnings, [])
        got = members["helper"]
        self.assertEqual((got["layer"], got["ad-hoc"], got["ad-hoc-run"]), ("ad-hoc", True, self.run_id))
        self.assertEqual((got["file"], got["instructions"]), ("helper.md", "Ad hoc body."))

    def test_run_b_on_the_same_user_global_directory_does_not_list_it_and_hears_nothing(self):
        self.put_ad_hoc("helper")
        self.assertIn("helper", self.listed()[0])  # control: run A sees it
        run_b = self.other_run()
        done, parsed = self.resolve(run_b)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("helper", [m["name"] for m in parsed["members"]])
        self.assertEqual(parsed["warnings"], [])
        self.assertEqual(done.stderr, "")

    def test_inside_admiral_run_a_lists_it_and_run_b_does_not(self):
        self.put_ad_hoc("helper", directory=self.fleet_ad_hoc)
        env = self.w.admiral_env()
        members, warnings = self.listed(env=env)
        self.assertEqual((members["helper"]["layer"], warnings), ("ad-hoc", []))
        done, parsed = self.resolve(self.other_run(), env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("helper", [m["name"] for m in parsed["members"]])
        self.assertEqual((parsed["warnings"], done.stderr), ([], ""))

    def test_a_trailing_slash_on_the_run_directory_gives_the_same_id(self):
        self.put_ad_hoc("helper")
        members, _ = self.listed(run=f"{self.w.run}/")
        self.assertIn("helper", members)

    def test_a_symlink_to_the_run_directory_gives_the_same_id(self):
        self.put_ad_hoc("helper")
        link = self.w.root / "run-link"
        link.symlink_to(self.w.run)
        members, _ = self.listed(run=link)
        self.assertIn("helper", members)

    def test_the_id_is_the_whole_real_path_not_the_basename(self):
        self.put_ad_hoc("helper")
        self.assertIn("helper", self.listed()[0])  # control: the run itself sees it
        same_basename = self.other_run("run", parent=self.w.root / "elsewhere" / "x")
        done, parsed = self.resolve(same_basename)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("helper", [m["name"] for m in parsed["members"]])
        self.assertEqual(parsed["warnings"], [])

    def test_the_id_never_comes_from_team_env_or_the_environment(self):
        self.put_ad_hoc("helper", run="run-b")
        self.put_ad_hoc("own")
        self.w.team_env(lines=["RUN_ID=run-b", "ADMIRAL_RUN_ID=run-b", "RUN=run-b", "TEAM=run-b"])
        done, parsed = self.resolve(env=self.w.env(RUN_ID="run-b", ADMIRAL_RUN_ID="run-b", RUN="run-b"))
        self.assertEqual(done.returncode, 0, done.stderr)
        names = [m["name"] for m in parsed["members"]]
        self.assertNotIn("helper", names)
        self.assertIn("own", names)  # control: the run's real-path id still matches
        self.assertEqual(parsed["warnings"], [])

    def test_only_the_runs_own_ad_hoc_directory_is_read(self):
        self.put_ad_hoc("in-fleet", directory=self.fleet_ad_hoc)  # outside Admiral the fleet is ignored
        self.put_ad_hoc("in-repo", directory=self.w.layer_dirs["repo"] / "ad-hoc")
        self.put_ad_hoc("in-run", directory=self.w.layer_dirs["run"] / "ad-hoc")
        self.put_ad_hoc("in-user-crew-root", directory=self.user_crew)  # directly in a layer: misplaced, not ad hoc
        self.put_ad_hoc("in-own-dir")
        members, _ = self.listed(env=self.w.env(ADMIRAL_CREW_DIR=str(self.fleet)))
        self.assertEqual([n for n in members if n not in self.builtin_names()], ["in-own-dir"])

    def test_inside_admiral_the_user_global_ad_hoc_directory_is_ignored(self):
        self.put_ad_hoc("in-user")
        self.put_ad_hoc("in-fleet", directory=self.fleet_ad_hoc)
        members, warnings = self.listed(env=self.w.admiral_env())
        self.assertEqual([n for n in members if n not in self.builtin_names()], ["in-fleet"])
        self.assertEqual(warnings, [])

    def test_a_run_id_with_a_quote_backslash_or_control_character_is_an_error(self):
        for label, name in {
            "quote": 'quo"te',
            "backslash": "back\\slash",
            "newline": "new\nline",
            "tab": "ta\tb",
        }.items():
            with self.subTest(label):
                run = self.other_run(name)
                done = self.w.sh([self.w.crew_py, "resolve", "--run", run])
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertTrue(any(ln.startswith("ERROR bad run id") for ln in done.stderr.splitlines()), done.stderr)
                self.assertEqual(done.stdout, "")


class ResolveFilter(AdHocCase):
    def test_noise_that_does_not_name_this_run_is_silent(self):
        d = self.user_ad_hoc
        d.mkdir(parents=True)
        (d / "garbage.md").write_text("not a member\n")
        (d / "latin1.md").write_bytes(b"---\nname: latin1\n---\nbody \xff\xfe\n")
        (d / "huge.md").write_text("x" * (MAX_BYTES + 10))
        (d / "outside.md").symlink_to(self.w.root / "nowhere.md")
        (d / "sub").mkdir()
        self.put_ad_hoc("in-subdir", directory=d / "sub")
        self.put_ad_hoc("other", run="somebody-else")
        self.put_ad_hoc("exact", run=self.run_id + " ")  # exact string compare: a trailing space is another run
        self.put_ad_hoc("flagless-other", run="somebody-else", flag=False)
        self.put_ad_hoc("mine")  # control: the one valid member of this run
        members, warnings = self.listed()
        self.assertEqual([n for n in members if n not in self.builtin_names()], ["mine"])
        self.assertEqual(warnings, [])

    def test_an_own_member_that_fails_the_filter_warns_once_with_ad_hoc_unreadable(self):
        d = self.user_ad_hoc
        self.put_ad_hoc("no-flag", flag=False)
        self.put_ad_hoc("liar", role="scribe").write_text(self.ad_hoc_text("different", "scribe"))
        (d / "bad-yaml.md").write_text(f'---\nname: bad-yaml\nad-hoc-run: "{self.run_id}"\n  - nope\n')
        members, warnings = self.listed()
        self.assertEqual([n for n in members if n not in self.builtin_names()], [])
        got = sorted((w["layer"], w["file"], w["code"], w["field"]) for w in warnings)
        self.assertEqual(
            got,
            [
                ("ad-hoc", "bad-yaml.md", "ad-hoc-unreadable", None),
                ("ad-hoc", "liar.md", "ad-hoc-unreadable", None),
                ("ad-hoc", "no-flag.md", "ad-hoc-unreadable", None),
            ],
        )

    def test_the_unquoted_run_line_counts_for_the_own_broken_warning(self):
        self.user_ad_hoc.mkdir(parents=True)
        (self.user_ad_hoc / "plain.md").write_text(f"---\nname: other\nad-hoc-run: {self.run_id}\n---\n")
        _, warnings = self.listed()
        self.assertEqual([(w["file"], w["code"]) for w in warnings], [("plain.md", "ad-hoc-unreadable")])

    def test_ad_hoc_never_replaces_a_standing_member_whatever_the_layer(self):
        self.w.write_member("repo", "taken", "scribe", body="Standing.")
        self.put_ad_hoc("taken")
        self.put_ad_hoc("scribe")  # a built-in member's name
        members, warnings = self.listed()
        self.assertEqual((members["taken"]["layer"], members["scribe"]["layer"]), ("repo", "built-in"))
        self.assertEqual(
            [(w["layer"], w["file"], w["code"], w["field"]) for w in warnings],
            [("ad-hoc", "scribe.md", "ad-hoc-name-taken", "name"), ("ad-hoc", "taken.md", "ad-hoc-name-taken", "name")],
        )
        by_file = {w["file"]: w["message"] for w in warnings}
        self.assertIn("repo", by_file["taken.md"])
        self.assertIn("built-in", by_file["scribe.md"])

    def test_no_ad_hoc_fix_checker(self):
        self.put_ad_hoc("second-checker", role="fix-checker", body="")
        members, warnings = self.listed()
        self.assertNotIn("second-checker", members)
        self.assertEqual(
            [(w["file"], w["code"], w["field"]) for w in warnings],
            [("second-checker.md", "ad-hoc-fix-checker", "role")],
        )

    def test_a_member_this_run_made_gets_the_usual_field_warnings_with_layer_ad_hoc(self):
        self.put_ad_hoc("odd", extra="zeta: 1\nskills: [writing, bad skill!]\n")
        members, warnings = self.listed()
        self.assertEqual(members["odd"]["skills"], ["writing"])
        self.assertEqual(
            [(w["layer"], w["file"], w["code"], w["field"]) for w in warnings],
            [("ad-hoc", "odd.md", "unknown-field", "zeta"), ("ad-hoc", "odd.md", "bad-skill", "skills")],
        )

    def test_a_missing_ad_hoc_directory_is_silent(self):
        members, warnings = self.listed()
        self.assertEqual((sorted(members), warnings), (sorted(self.builtin_names()), []))
        self.assertFalse(self.user_ad_hoc.exists())
        self.put_ad_hoc("helper")  # control: once the directory exists, the run's member is listed
        self.assertIn("helper", self.listed()[0])

    def test_an_ad_hoc_directory_that_cannot_be_listed_is_one_warning_not_an_error(self):
        if is_root():
            self.skipTest("root lists directories whatever their mode")
        self.put_ad_hoc("helper")
        self.user_ad_hoc.chmod(0o000)
        self.addCleanup(self.user_ad_hoc.chmod, 0o755)
        members, warnings = self.listed()
        self.assertNotIn("helper", members)
        self.assertEqual(
            [(w["layer"], w["file"], w["code"], w["field"]) for w in warnings],
            [("ad-hoc", None, "ad-hoc-unreadable", None)],
        )


class ResolveRefusesAnUnsafeAdHocDirectory(AdHocCase):
    def assert_dir_refused(self, env=None):
        members, warnings = self.listed(env=env)
        self.assertNotIn("helper", members)
        self.assertEqual(
            [(w["layer"], w["file"], w["code"], w["field"]) for w in warnings],
            [("ad-hoc", None, "ad-hoc-dir-refused", None)],
        )

    def test_the_ad_hoc_directory_as_a_symlink(self):
        real = self.w.root / "real-ad-hoc"
        self.put_ad_hoc("helper", directory=real)
        self.user_crew.mkdir(parents=True)
        self.user_ad_hoc.symlink_to(real)
        self.assert_dir_refused()

    def test_a_symlinked_crew_or_commodore_directory(self):
        for label in ("commodore", "crew"):
            with self.subTest(label):
                shutil_target = self.w.root / f"real-{label}"
                shutil_target.mkdir()
                if label == "commodore":
                    self.put_ad_hoc("helper", directory=shutil_target / "crew" / "ad-hoc")
                    link = self.w.xdg / "commodore"
                else:
                    self.put_ad_hoc("helper", directory=shutil_target / "ad-hoc")
                    link = self.user_crew
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(shutil_target)
                self.assert_dir_refused()
                link.unlink()

    def test_a_directory_whose_real_path_is_inside_the_repo_or_a_commodore_directory(self):
        places = {
            "inside the repo": self.w.repo / "cfg",
            "the repo itself": self.w.repo,
            "inside a .commodore directory": self.w.root / "other" / ".commodore" / "xdg",
        }
        for label, xdg in places.items():
            with self.subTest(label):
                self.put_ad_hoc("helper", directory=xdg / "commodore" / "crew" / "ad-hoc")
                self.assert_dir_refused(env=self.w.env(XDG_CONFIG_HOME=str(xdg)))

    def test_inside_admiral_the_ad_hoc_directory_as_a_symlink_or_the_fleet_inside_the_repo(self):
        real = self.w.root / "real-ad-hoc"
        self.put_ad_hoc("helper", directory=real)
        self.fleet.mkdir()
        self.fleet_ad_hoc.symlink_to(real)
        self.assert_dir_refused(env=self.w.admiral_env())
        self.fleet_ad_hoc.unlink()
        in_repo = self.w.repo / "fleet"
        self.put_ad_hoc("helper", directory=in_repo / "ad-hoc")
        self.assert_dir_refused(env=self.w.admiral_env(ADMIRAL_CREW_DIR=None) | {"ADMIRAL_CREW_DIR": str(in_repo)})

    def test_inside_admiral_a_symlinked_fleet_directory_is_allowed(self):
        real = self.w.root / "real-fleet"
        self.put_ad_hoc("helper", directory=real / "ad-hoc")
        self.fleet.symlink_to(real)
        members, warnings = self.listed(env=self.w.admiral_env())
        self.assertEqual((members["helper"]["layer"], warnings), ("ad-hoc", []))

    def test_a_symlinked_xdg_config_home_is_allowed(self):
        real = self.w.root / "real-xdg"
        self.put_ad_hoc("helper", directory=real / "commodore" / "crew" / "ad-hoc")
        link = self.w.root / "xdg-link"
        link.symlink_to(real)
        members, warnings = self.listed(env=self.w.env(XDG_CONFIG_HOME=str(link)))
        self.assertEqual((members["helper"]["layer"], warnings), ("ad-hoc", []))


# ---------------------------------------------------------------------------------------------------- cast
class CastAdHoc(AdHocCase):
    def test_without_a_pick_the_role_keeps_its_non_ad_hoc_default(self):
        self.put_ad_hoc("helper")
        done = self.assert_cast_works()
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["scribe"][1], rows["scribe"][7]), ("scribe", "built-in"))
        self.assertNotIn("helper", done.stdout)
        self.assertEqual(self.warns(done), [])

    def test_the_several_candidates_warning_counts_only_non_ad_hoc_members(self):
        self.w.write_member("repo", "scribe-repo", "scribe")
        self.put_ad_hoc("helper")
        self.assertEqual(self.w.cast("--pick", "scribe=helper").returncode, 0)  # control: it is a candidate
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        warns = [w for w in self.warns(done) if "scribe" in w and "candidates" in w]
        self.assertEqual(len(warns), 1, done.stderr)
        self.assertIn("2 candidates", warns[0])
        self.assertNotIn("3 candidates", done.stderr)

    def test_a_pick_casts_it_with_source_ad_hoc(self):
        self.put_ad_hoc("helper", body="Be the helper.")
        done = self.w.cast("--pick", "scribe=helper")
        self.assertEqual(done.returncode, 0, done.stderr)
        header, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(header, HEADER)
        self.assertEqual(
            (rows["scribe"][1], rows["scribe"][4], rows["scribe"][7]), ("helper", "Be the helper.", "ad-hoc")
        )
        self.assertNotIn("(pinned)", rows["scribe"][7])

    def test_inside_admiral_a_pick_casts_it_with_source_ad_hoc(self):
        self.put_ad_hoc("helper", directory=self.fleet_ad_hoc)
        done = self.w.cast("--pick", "scribe=helper", env=self.w.admiral_env())
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["scribe"][1], rows["scribe"][7]), ("helper", "ad-hoc"))

    def test_a_custom_role_ad_hoc_member_is_cast_under_its_role_only_when_picked(self):
        self.put_ad_hoc("notes", role="changelog", extra="based-on: scribe\n")
        _, _, rows, order = parse_table(self.assert_cast_works().stdout)
        self.assertNotIn("changelog", order)  # a role whose only candidates are ad hoc has no default, no crash
        done = self.w.cast("--pick", "changelog=notes")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, order = parse_table(done.stdout)
        self.assertEqual(order[-1], "changelog")
        self.assertEqual(
            (rows["changelog"][1], rows["changelog"][2], rows["changelog"][7]), ("notes", "scribe", "ad-hoc")
        )

    def test_another_runs_ad_hoc_member_is_not_a_candidate_to_pick(self):
        self.put_ad_hoc("helper")
        self.assert_cast_works("--pick", "scribe=helper")  # control: run A can pick it
        run_b = self.other_run()
        done = self.w.cast("--pick", "scribe=helper", run=run_b)
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertIn("helper", done.stderr)

    def test_cast_json_carries_ad_hoc_and_ad_hoc_run_in_every_entry(self):
        self.put_ad_hoc("helper")
        done = self.w.cast("--pick", "scribe=helper", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        entries = {e["role"]: e for e in self.w.read_json()["cast"]}
        self.assertEqual((entries["scribe"]["ad-hoc"], entries["scribe"]["ad-hoc-run"]), (True, self.run_id))
        self.assertEqual(entries["scribe"]["layer"], "ad-hoc")
        for role, entry in entries.items():
            if role != "scribe":
                with self.subTest(role):
                    self.assertEqual((entry["ad-hoc"], entry["ad-hoc-run"]), (False, None))

    def test_a_saved_pick_of_an_ad_hoc_member_applies_on_the_next_cast(self):
        self.put_ad_hoc("helper")
        self.assertEqual(self.w.cast("--pick", "scribe=helper", "--save").returncode, 0)
        _, _, rows, _ = parse_table(self.w.cast().stdout)
        self.assertEqual((rows["scribe"][1], rows["scribe"][7]), ("helper", "ad-hoc"))


# ---------------------------------------------------------------------------------------------------- adhoc: writes
class AdhocWrites(AdHocCase):
    def test_writes_the_member_outside_admiral_and_prints_its_path(self):
        done = self.adhoc(
            based_on=None,
            skill=["/writing", "$simplify", "plain"],
            model="opus",
            harness="codex",
            name="notes-writer",
            role="scribe",
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        path = self.user_ad_hoc / "notes-writer.md"
        self.assertEqual(done.stdout.splitlines(), [f"wrote {path}"])
        self.assertTrue(path.is_file())
        self.assertEqual(sorted(p.name for p in self.user_ad_hoc.iterdir()), ["notes-writer.md"])
        members, warnings = self.listed()
        self.assertEqual(warnings, [])
        got = members["notes-writer"]
        self.assertEqual(
            (got["layer"], got["ad-hoc"], got["ad-hoc-run"], got["skills"], got["model"], got["harness"]),
            ("ad-hoc", True, self.run_id, ["writing", "simplify", "plain"], "opus", "codex"),
        )
        self.assertEqual(
            (got["pick-me-when"], got["instructions"]), ("Use for the release notes.", "Write the release notes.")
        )

    def test_frontmatter_keys_come_in_the_documented_order_with_quoted_strings(self):
        self.adhoc(role="release-notes", based_on="scribe", skill="writing", model="opus", harness="claude")
        keys, values, body = self.read_member_file(self.user_ad_hoc / "notes-writer.md")
        self.assertEqual(keys, FULL_KEYS)
        self.assertEqual(values["name"], '"notes-writer"')
        self.assertEqual(values["role"], '"release-notes"')
        self.assertEqual(values["based-on"], '"scribe"')
        self.assertEqual(values["pick-me-when"], '"Use for the release notes."')
        self.assertEqual(values["model"], '"opus"')
        self.assertEqual(values["harness"], '"claude"')
        self.assertTrue(values["skills"].startswith("[") and values["skills"].endswith("]"), values["skills"])
        self.assertEqual((values["ad-hoc"], values["ad-hoc-run"]), ("true", f'"{self.run_id}"'))
        self.assertEqual(body, "Write the release notes.")

    def test_the_minimal_call_writes_an_empty_flow_list_and_leaves_out_the_optional_keys(self):
        self.assertEqual(self.adhoc().returncode, 0)
        keys, values, _ = self.read_member_file(self.user_ad_hoc / "notes-writer.md")
        self.assertEqual(keys, MINIMAL_KEYS)
        self.assertEqual(values["skills"], "[]")

    def test_the_file_is_private_and_the_directory_is_created_with_mode_0700(self):
        self.assertFalse(self.w.xdg.exists())
        self.assertEqual(self.adhoc().returncode, 0)
        self.assertEqual(stat_mode(self.user_ad_hoc / "notes-writer.md"), 0o600)
        self.assertEqual(stat_mode(self.user_ad_hoc), 0o700)
        self.assertEqual(stat_mode(self.user_crew), 0o700)

    def test_an_existing_ad_hoc_directory_keeps_its_mode_and_other_files(self):
        self.put_ad_hoc("earlier", run="run-earlier")
        self.user_ad_hoc.chmod(0o750)
        before = (self.user_ad_hoc / "earlier.md").read_text()
        self.assertEqual(self.adhoc().returncode, 0)
        self.assertEqual(stat_mode(self.user_ad_hoc), 0o750)
        self.assertEqual((self.user_ad_hoc / "earlier.md").read_text(), before)

    def test_inside_admiral_the_file_lands_in_the_fleet_ad_hoc_directory(self):
        self.fleet.mkdir()
        done = self.adhoc(env=self.w.admiral_env())
        self.assertEqual(done.returncode, 0, done.stderr)
        path = self.fleet_ad_hoc / "notes-writer.md"
        self.assertEqual(done.stdout.splitlines(), [f"wrote {path}"])
        self.assertEqual((stat_mode(path), stat_mode(self.fleet_ad_hoc)), (0o600, 0o700))
        self.assertFalse(self.w.xdg.exists())
        members, _ = self.listed(env=self.w.admiral_env())
        self.assertEqual(
            (members["notes-writer"]["layer"], members["notes-writer"]["ad-hoc-run"]), ("ad-hoc", self.run_id)
        )

    def test_inside_admiral_the_fleet_dir_can_come_from_team_env_like_resolve_reads_it(self):
        self.fleet.mkdir()
        self.w.team_env(lines=["ADMIRAL_SHIP=ship-9", f"ADMIRAL_CREW_DIR={self.fleet}"])
        done = self.adhoc(env=self.w.env())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.fleet_ad_hoc / "notes-writer.md").is_file())

    def test_a_trailing_slash_on_run_writes_the_same_run_id(self):
        self.assertEqual(self.adhoc(run=f"{self.w.run}/").returncode, 0)
        _, values, _ = self.read_member_file(self.user_ad_hoc / "notes-writer.md")
        self.assertEqual(values["ad-hoc-run"], f'"{self.run_id}"')

    def test_awkward_characters_round_trip_through_resolve_exactly(self):
        body = self.body_file(raw=TRICKY_BODY.encode())
        done = self.adhoc(pick_me_when=TRICKY, body_file=body, skill=["a:b", "c.d_e-f"])
        self.assertEqual(done.returncode, 0, done.stderr)
        members, warnings = self.listed()
        self.assertEqual(warnings, [])
        got = members["notes-writer"]
        self.assertEqual((got["pick-me-when"], got["instructions"]), (TRICKY, TRICKY_BODY))
        self.assertEqual(got["skills"], ["a:b", "c.d_e-f"])

    def test_the_body_is_written_as_is_after_the_closing_line(self):
        body = "  indented first\n\ntrailing blank lines\n\n"
        self.adhoc(body_file=self.body_file(raw=body.encode()))
        text = (self.user_ad_hoc / "notes-writer.md").read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n---\n" + body), repr(text))

    def test_the_body_file_is_read_never_run(self):
        marker = self.w.root / "ran"
        body = self.body_file(raw=f"#!/bin/sh\ntouch {marker}\n$(touch {marker})\n".encode())
        body.chmod(0o755)
        self.assertEqual(self.adhoc(body_file=body).returncode, 0)
        self.assertFalse(marker.exists())

    def test_a_body_that_fits_at_the_size_cap_is_written(self):
        head = len((self.ad_hoc_text("notes-writer", "scribe", body="")).encode()) + 400  # generous frontmatter room
        body = self.body_file(raw=b"x" * (MAX_BYTES - head))
        self.assertEqual(self.adhoc(body_file=body).returncode, 0)

    def test_the_new_member_is_a_candidate_cast_only_by_pick(self):
        self.assertEqual(self.adhoc().returncode, 0)
        _, _, rows, _ = parse_table(self.assert_cast_works().stdout)
        self.assertEqual(rows["scribe"][1], "scribe")  # not the role's default
        done = self.w.cast("--pick", "scribe=notes-writer")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["scribe"][1], rows["scribe"][7]), ("notes-writer", "ad-hoc"))

    def test_a_custom_role_member_is_cast_under_its_role_when_picked(self):
        self.assertEqual(self.adhoc(role="release-notes", based_on="scribe").returncode, 0)
        done = self.w.cast("--pick", "release-notes=notes-writer")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(
            (rows["release-notes"][1], rows["release-notes"][2], rows["release-notes"][7]),
            ("notes-writer", "scribe", "ad-hoc"),
        )

    def test_the_second_run_does_not_see_the_member_the_first_wrote(self):
        self.assertEqual(self.adhoc().returncode, 0)
        done, parsed = self.resolve(self.other_run())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("notes-writer", [m["name"] for m in parsed["members"]])
        self.assertEqual((parsed["warnings"], done.stderr), ([], ""))


def stat_mode(path):
    return Path(path).stat().st_mode & 0o777


# ---------------------------------------------------------------------------------------------------- adhoc: refusals
class AdhocRefusals(AdHocCase):
    def test_each_check_refuses_with_one_error_and_writes_nothing(self):
        self.w.write_member("repo", "repo-member", "scribe")
        self.w.write_member("user", "user-member", "scribe")
        self.w.write_member("run", "run-member", "scribe")
        self.put_ad_hoc("elsewhere-run", run="run-b")
        slug_bad = ["Bad_Name", "-x", "x-", "has space", "UPPER", "x" * 65, ""]
        cases = {}
        cases.update({f"name {v!r}": {"name": v} for v in slug_bad})
        cases.update({f"role {v!r}": {"role": v} for v in slug_bad if v})
        cases.update(
            {
                "role fix-checker": {"role": "fix-checker"},
                "custom role without based-on": {"role": "changelog"},
                "custom role, based-on fix-checker": {"role": "changelog", "based_on": "fix-checker"},
                "custom role, unknown based-on": {"role": "changelog", "based_on": "nonsense"},
                "custom role, based-on is itself custom": {"role": "changelog", "based_on": "Scribe"},
                "built-in role with based-on": {"role": "scribe", "based_on": "implementer"},
                "bad harness": {"harness": "gemini"},
                "bad harness case": {"harness": "Claude"},
                "bad skill": {"skill": ["ok", "bad skill"]},
                "skill with two leading slashes": {"skill": "//x"},
                "skill with a leading dash": {"skill": "-x"},
                "skill empty after the prefix": {"skill": "/"},
                "empty pick-me-when": {"pick_me_when": ""},
                "blank pick-me-when": {"pick_me_when": " \t "},
                "pick-me-when with a newline": {"pick_me_when": "a\nb"},
                "name of a built-in member": {"name": "scribe"},
                "name of a repo member": {"name": "repo-member"},
                "name of a user-global member": {"name": "user-member"},
                "name of a run-layer member": {"name": "run-member"},
                "name of another run's ad hoc file": {"name": "elsewhere-run"},
                "body file missing": {"body_file": self.w.run / "prompts" / "absent.md"},
                "body not UTF-8": {"body_file": self.body_file(raw=b"bad \xff\xfe", name="latin1.md")},
                "body over the cap": {"body_file": self.body_file(raw=b"x" * (MAX_BYTES + 1), name="huge.md")},
                "body and frontmatter over the cap": {
                    "body_file": self.body_file(raw=b"x" * (MAX_BYTES - 20), name="edge.md")
                },
            }
        )
        cases.update({f"model {v!r}": {"model": v} for v in BAD_MODELS})
        for label, kw in cases.items():
            with self.subTest(label):
                self.assert_refused(label, **kw)
        # positive control: the world is fine, so only the bad part was the reason
        self.assertEqual(self.adhoc().returncode, 0)

    def test_a_name_that_exists_as_a_file_in_the_ad_hoc_directory_is_refused_and_kept(self):
        for label, run in {"own run": None, "another run": "run-b"}.items():
            with self.subTest(label):
                path = self.put_ad_hoc("notes-writer", run=run)
                before = path.read_bytes()
                self.assert_refused(label)
                self.assertEqual(path.read_bytes(), before)
                path.unlink()

    def test_a_dangling_symlink_named_like_the_member_is_refused_and_its_target_not_created(self):
        self.user_ad_hoc.mkdir(parents=True)
        target = self.w.root / "victim.md"
        (self.user_ad_hoc / "notes-writer.md").symlink_to(target)
        self.assert_refused("dangling")
        self.assertFalse(target.exists())

    def test_a_symlink_named_like_the_member_never_overwrites_its_target(self):
        self.user_ad_hoc.mkdir(parents=True)
        target = self.w.root / "victim.md"
        target.write_text("keep me\n")
        (self.user_ad_hoc / "notes-writer.md").symlink_to(target)
        self.assert_refused("live symlink")
        self.assertEqual(target.read_text(), "keep me\n")

    def test_symlinks_in_the_ad_hoc_path_are_refused(self):
        elsewhere = self.w.root / "elsewhere"
        elsewhere.mkdir()
        self.user_crew.mkdir(parents=True)
        self.user_ad_hoc.symlink_to(elsewhere)
        self.assert_refused("ad-hoc symlink")
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.user_ad_hoc.unlink()
        (self.w.root / "real-crew").mkdir()
        self.user_crew.rmdir()
        self.user_crew.symlink_to(self.w.root / "real-crew")
        self.assert_refused("crew symlink")
        self.assertEqual(list((self.w.root / "real-crew").iterdir()), [])
        self.user_crew.unlink()
        (self.w.root / "real-commodore").mkdir()
        (self.w.xdg / "commodore").rmdir()
        (self.w.xdg / "commodore").symlink_to(self.w.root / "real-commodore")
        self.assert_refused("commodore symlink")
        self.assertEqual(list((self.w.root / "real-commodore").iterdir()), [])

    def test_inside_admiral_the_ad_hoc_directory_as_a_symlink_is_refused_but_the_fleet_directory_may_be_one(self):
        env = self.w.admiral_env()
        elsewhere = self.w.root / "elsewhere"
        elsewhere.mkdir()
        self.fleet.mkdir()
        self.fleet_ad_hoc.symlink_to(elsewhere)
        self.assert_refused("ad-hoc symlink", env=env)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.fleet_ad_hoc.unlink()
        self.fleet.rmdir()
        real = self.w.root / "real-fleet"
        real.mkdir()
        self.fleet.symlink_to(real)
        done = self.adhoc(env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((real / "ad-hoc" / "notes-writer.md").is_file())

    def test_a_symlinked_xdg_config_home_is_allowed(self):
        real = self.w.root / "real-xdg"
        real.mkdir()
        link = self.w.root / "xdg-link"
        link.symlink_to(real)
        done = self.adhoc(env=self.w.env(XDG_CONFIG_HOME=str(link)))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((real / "commodore" / "crew" / "ad-hoc" / "notes-writer.md").is_file())

    def test_the_ad_hoc_directory_may_never_be_in_the_repo_or_a_commodore_directory(self):
        real_in_repo = self.w.repo / "cfg2"
        real_in_repo.mkdir()
        link = self.w.root / "xdg-into-repo"
        link.symlink_to(real_in_repo)
        places = {
            "xdg inside the repo, nothing there yet": self.w.repo / "cfg",
            "xdg deep inside the repo, nothing there yet": self.w.repo / "a" / "b" / "c",
            "xdg is the repo": self.w.repo,
            "xdg inside a .commodore directory": self.w.root / "other" / ".commodore" / "xdg",
            "xdg is a symlink into the repo": link,
        }
        for label, xdg in places.items():
            with self.subTest(label):
                self.assert_refused(label, env=self.w.env(XDG_CONFIG_HOME=str(xdg)))
        self.assertEqual(list(self.w.repo.rglob("ad-hoc")), [])

    def test_inside_admiral_a_fleet_directory_in_the_repo_or_a_commodore_directory_is_refused(self):
        for label, fleet in {
            "fleet inside the repo": self.w.repo / "fleet",
            "fleet inside .commodore": self.w.root / "x" / ".commodore" / "fleet",
        }.items():
            with self.subTest(label):
                fleet.mkdir(parents=True)
                env = self.w.admiral_env() | {"ADMIRAL_CREW_DIR": str(fleet)}
                self.assert_refused(label, env=env)

    def test_inside_admiral_a_missing_or_empty_fleet_directory_is_exit_1(self):
        before = self.snapshot()
        env = self.w.admiral_env() | {"ADMIRAL_CREW_DIR": ""}
        done = self.adhoc(env=env)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stderr.splitlines(), ["ERROR no ad hoc directory: ADMIRAL_CREW_DIR is empty"])
        self.assertEqual(self.snapshot(), before)
        done = self.adhoc(env=self.w.admiral_env())  # set, but the directory does not exist
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(len(self.errors(done)), 1)
        self.assertEqual(self.snapshot(), before)

    def test_an_unset_fleet_directory_inside_admiral_is_empty_too(self):
        env = self.w.env(ADMIRAL_SHIP="ship-1")
        done = self.adhoc(env=env)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stderr.splitlines(), ["ERROR no ad hoc directory: ADMIRAL_CREW_DIR is empty"])

    def test_the_body_file_must_be_a_regular_file_inside_the_runs_prompts_directory(self):
        outside = self.w.root / "outside.md"
        outside.write_text("outside\n")
        inside = self.body_file(name="real.md")
        prompts = self.w.run / "prompts"
        (prompts / "link-out.md").symlink_to(outside)
        (prompts / "link-in.md").symlink_to(inside)
        (prompts / "subdir").mkdir()
        (self.w.run / "in-run-dir.md").write_text("x\n")
        cases = {
            "in the run dir, not prompts": self.w.run / "in-run-dir.md",
            "in the temp dir": outside,
            "symlink out of prompts": prompts / "link-out.md",
            "symlink within prompts": prompts / "link-in.md",
            "a directory": prompts / "subdir",
            "dot-dot out of prompts": prompts / ".." / "in-run-dir.md",
            "dot-dot back in via another dir": self.w.root / "run" / ".." / "run" / "in-run-dir.md",
        }
        for label, path in cases.items():
            with self.subTest(label):
                self.assert_refused(label, body_file=path)
        self.assertEqual(self.adhoc(body_file=inside).returncode, 0)

    def test_a_run_id_with_a_quote_backslash_or_control_character_is_refused(self):
        for label, name in {"quote": 'quo"te', "backslash": "back\\slash", "newline": "new\nline"}.items():
            with self.subTest(label):
                run = self.other_run(name)
                (run / "prompts").mkdir()
                body = run / "prompts" / "body.md"
                body.write_text("body\n")
                before = self.snapshot()
                done = self.adhoc(run=run, body_file=body)
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertTrue(any(ln.startswith("ERROR bad run id") for ln in done.stderr.splitlines()), done.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_resolve_errors_stop_the_write_and_are_printed_as_error_lines(self):
        self.w.layer_dirs["repo"].mkdir(parents=True)
        (self.w.layer_dirs["repo"] / "broken.md").write_text("no frontmatter\n")
        done = self.assert_refused("resolve errors")
        self.assertIn("broken.md", done.stderr)
        self.assertIn("bad-frontmatter", done.stderr)

    def test_usage_errors_exit_5_and_write_nothing(self):
        body = str(self.body_file())
        full = {
            "run": str(self.w.run),
            "name": "x-member",
            "role": "scribe",
            "pick-me-when": "Pick.",
            "body-file": body,
        }
        calls = {f"missing --{k}": {k: None} for k in full}
        calls.update({f"{k} twice": {k: [v, v]} for k, v in full.items()})
        calls.update(
            {f"{k} twice": {k: [v, v]} for k, v in {"based-on": "scribe", "model": "opus", "harness": "codex"}.items()}
        )
        for label, kw in calls.items():
            with self.subTest(label):
                self.assert_refused(label, code=5, **kw)
        for label, extra in {
            "unknown flag": ["--bogus", "x"],
            "stray word": ["stray"],
            "--name without a value": [],
        }.items():
            with self.subTest(label):
                before = self.snapshot()
                args = self.adhoc_args(name=None if label == "--name without a value" else "x-member")
                args += ["--name"] if label == "--name without a value" else extra
                done = self.w.sh([self.w.crew_py, "adhoc", *args])
                self.assertEqual((done.returncode, done.stdout), (5, ""), done.stderr)
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.adhoc(name="x-member").returncode, 0)  # control: the same call without the flaw works

    def test_skill_may_repeat(self):
        self.assertEqual(self.adhoc(skill=["one", "two"]).returncode, 0)
        members, _ = self.listed()
        self.assertEqual(members["notes-writer"]["skills"], ["one", "two"])


# ---------------------------------------------------------------------------------------------------- skill text
class SkillText(unittest.TestCase):
    """Text checks on what the implementer ships: SKILL.md, the references and USAGE."""

    def read(self, rel):
        return (COMMODORE / rel).read_text(encoding="utf-8")

    def test_skill_md_names_the_adhoc_command_the_prompts_file_and_the_state_section(self):
        text = self.read("SKILL.md")
        self.assertIn("crew.py adhoc --run", text)
        self.assertIn("<run>/prompts/", text)
        self.assertIn("## Ad hoc members", text)  # ruling 14: the lead records each `wrote <path>` line in state.md
        self.assertIn("--pick", text)

    def test_the_build_missions_final_report_lists_the_ad_hoc_members(self):
        text = self.read("references/mission-build.md")
        report = next(ln for ln in text.splitlines() if ln.startswith("5. Write the final report"))
        self.assertIn("ad hoc members", report.lower())

    def test_crew_members_reference_documents_the_directory_the_filter_and_the_command(self):
        text = self.read("references/crew-members.md")
        for needle in (
            "ad-hoc-name-taken",
            "ad-hoc-fix-checker",
            "ad-hoc-unreadable",
            "ad-hoc-dir-refused",
            "--run-id",
            "--layer ad-hoc",
            "crew.py adhoc",
        ):
            self.assertIn(needle, text)
        layers = text.split("## Layers", 1)[1].split("\n## ", 1)[0]
        table = [ln for ln in layers.splitlines() if ln.startswith("|")]
        self.assertTrue(table)
        self.assertEqual([ln for ln in table if "ad-hoc" in ln], [], "the ad hoc directory isn't an override layer")
        self.assertNotIn("which isn't read here", text)

    def test_usage_lists_the_new_forms(self):
        done = subprocess.run(
            [str(COMMODORE / "scripts" / "crew.py")],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(done.returncode, 5)
        for needle in ("crew.py adhoc", "--body-file", "--pick-me-when", "--run-id", "ad-hoc="):
            self.assertIn(needle, done.stderr)

    def test_the_final_report_wording_says_drop_not_delete(self):
        for rel in ("SKILL.md", "references/mission-build.md"):
            lines = [ln for ln in self.read(rel).splitlines() if re.search(r"ad[- ]hoc", ln, re.IGNORECASE)]
            joined = "\n".join(lines).lower()
            self.assertNotIn("delete", joined, rel)
        self.assertIn("drop", self.read("references/mission-build.md").lower())


if __name__ == "__main__":
    unittest.main()
