"""Tests for ad hoc crew members: `crew.py adhoc` writes one, and `resolve` and `cast` see it only in its own run."""

import json
import os
import unittest
from pathlib import Path

from crew_world import WorldCase, parse_table

MAX_BYTES = 65536
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
        self.default_body = self.body_file()

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
        """Every path under the world but the skills and bytecode caches, with its kind and content."""
        out = {}
        for top, dirs, files in os.walk(self.w.root):
            if Path(top) == self.w.root:
                dirs[:] = [d for d in dirs if d != "skills"]
            if Path(top) == self.w.home:
                dirs[:] = [d for d in dirs if d != "Library"]
            dirs[:] = [d for d in dirs if d != "__pycache__"]
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

    def assert_world_is(self, before, label="the call"):
        """Compare with an earlier snapshot, naming only the paths that differ (a whole-dict diff is megabytes)."""
        after = self.snapshot()
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        self.assertEqual(changed, [], f"{label}: the world changed")

    def resolve(self, run=None, env=None):
        done = self.w.sh([self.w.crew_py, "resolve", "--run", run or self.w.run], env=env)
        return done, (json.loads(done.stdout) if done.stdout.strip() else None)

    def listed(self, run=None, env=None):
        done, parsed = self.resolve(run, env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return {m["name"]: m for m in parsed["members"]}, parsed["warnings"]

    def dotdot_after_a_symlink(self, tail):
        """A path that climbs out of a symlink into the repo: <root>/outside/link/../<tail>, link -> <repo>/sub."""
        (self.w.repo / "sub").mkdir(exist_ok=True)
        (self.w.root / "outside").mkdir(exist_ok=True)
        link = self.w.root / "outside" / "link"
        if not link.is_symlink():
            link.symlink_to(self.w.repo / "sub")
        return f"{link}/../{tail}"

    def adhoc_args(self, **kw):
        """The arguments of a valid call; a keyword replaces a value, None drops the flag, a list repeats it."""
        opts = {
            "run": self.w.run,
            "name": "notes-writer",
            "role": "scribe",
            "pick-me-when": "Use for the release notes.",
            "body-file": self.default_body,  # made in setUp: building the args must not change the world
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
        """The call exits `code` with one ERROR line, no stdout, and the world unchanged."""
        before = self.snapshot()
        done = self.adhoc(env=env, **kw)
        self.assertEqual(done.returncode, code, f"{label}: {done.stderr}")
        self.assertEqual(done.stdout, "", label)
        if code == 1:
            self.assertEqual(len(self.errors(done)), 1, f"{label}: {done.stderr}")
        else:
            self.assertTrue(done.stderr.strip(), f"{label}: no usage message")
        self.assert_world_is(before, label)
        return done


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
        run_b = self.other_run()
        done, parsed = self.resolve(run_b)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("helper", [m["name"] for m in parsed["members"]])
        self.assertEqual(parsed["warnings"], [])
        self.assertEqual(done.stderr, "")

    def test_inside_admiral_run_a_lists_only_its_fleet_member_and_run_b_does_not(self):
        self.put_ad_hoc("in-user")
        self.put_ad_hoc("helper", directory=self.fleet_ad_hoc)
        env = self.w.admiral_env()
        members, warnings = self.listed(env=env)
        self.assertEqual([n for n in members if n not in self.builtin_names()], ["helper"])
        self.assertEqual((members["helper"]["layer"], warnings), ("ad-hoc", []))
        done, parsed = self.resolve(self.other_run(), env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("helper", [m["name"] for m in parsed["members"]])
        self.assertEqual((parsed["warnings"], done.stderr), ([], ""))

    def test_a_symlink_to_the_run_directory_gives_the_same_id(self):
        self.put_ad_hoc("helper")
        link = self.w.root / "run-link"
        link.symlink_to(self.w.run)
        members, _ = self.listed(run=link)
        self.assertIn("helper", members)

    def test_the_id_never_comes_from_team_env_or_the_environment(self):
        self.put_ad_hoc("helper", run="run-b")
        self.w.team_env(lines=["RUN_ID=run-b", "ADMIRAL_RUN_ID=run-b", "RUN=run-b", "TEAM=run-b"])
        done, parsed = self.resolve(env=self.w.env(RUN_ID="run-b", ADMIRAL_RUN_ID="run-b", RUN="run-b"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("helper", [m["name"] for m in parsed["members"]])
        self.assertEqual(parsed["warnings"], [])

    def test_only_the_runs_own_ad_hoc_directory_is_read(self):
        self.put_ad_hoc("in-fleet", directory=self.fleet_ad_hoc)  # outside Admiral the fleet is ignored
        self.put_ad_hoc("in-repo", directory=self.w.layer_dirs["repo"] / "ad-hoc")
        self.put_ad_hoc("in-run", directory=self.w.layer_dirs["run"] / "ad-hoc")
        self.put_ad_hoc("in-user-crew-root", directory=self.user_crew)  # directly in a layer: misplaced, not ad hoc
        self.put_ad_hoc("in-own-dir")
        members, _ = self.listed(env=self.w.env(ADMIRAL_CREW_DIR=str(self.fleet)))
        self.assertEqual([n for n in members if n not in self.builtin_names()], ["in-own-dir"])

    def test_a_run_id_with_a_quote_is_an_error(self):
        run = self.other_run('quo"te')
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
        members, warnings = self.listed()
        self.assertEqual([n for n in members if n not in self.builtin_names()], [])
        self.assertEqual(warnings, [])


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

    def test_a_directory_whose_real_path_is_inside_the_repo(self):
        xdg = self.w.repo / "cfg"
        self.put_ad_hoc("helper", directory=xdg / "commodore" / "crew" / "ad-hoc")
        self.assert_dir_refused(env=self.w.env(XDG_CONFIG_HOME=str(xdg)))


class CastAdHoc(AdHocCase):
    def test_without_a_pick_the_role_keeps_its_non_ad_hoc_default(self):
        self.put_ad_hoc("helper")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual((rows["scribe"][1], rows["scribe"][7]), ("scribe", "built-in"))
        self.assertNotIn("helper", done.stdout)
        self.assertEqual([w for w in self.warns(done) if "helper" in w or "candidates" in w], [])

    def test_a_pick_casts_it_with_source_ad_hoc(self):
        self.put_ad_hoc("helper", body="Be the helper.")
        done = self.w.cast("--pick", "scribe=helper")
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, _ = parse_table(done.stdout)
        self.assertEqual(
            (rows["scribe"][1], rows["scribe"][4], rows["scribe"][7]), ("helper", "Be the helper.", "ad-hoc")
        )
        self.assertNotIn("(pinned)", rows["scribe"][7])

    def test_a_custom_role_ad_hoc_member_is_cast_under_its_role_only_when_picked(self):
        self.put_ad_hoc("notes", role="changelog", extra="based-on: scribe\n")
        done = self.w.cast()
        self.assertEqual(done.returncode, 0, done.stderr)
        _, _, rows, order = parse_table(done.stdout)
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
        run_b = self.other_run()
        done = self.w.cast("--pick", "scribe=helper", run=run_b)
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertIn("helper", done.stderr)

    def test_cast_json_carries_ad_hoc_and_ad_hoc_run(self):
        self.put_ad_hoc("helper")
        done = self.w.cast("--pick", "scribe=helper", "--save")
        self.assertEqual(done.returncode, 0, done.stderr)
        entries = {e["role"]: e for e in self.w.read_json()["cast"]}
        self.assertEqual((entries["scribe"]["ad-hoc"], entries["scribe"]["ad-hoc-run"]), (True, self.run_id))
        self.assertEqual(entries["scribe"]["layer"], "ad-hoc")


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

    def test_the_file_is_private_and_the_directory_is_created_with_mode_0700(self):
        self.assertFalse(self.w.xdg.exists())
        self.assertEqual(self.adhoc().returncode, 0)
        self.assertEqual(stat_mode(self.user_ad_hoc / "notes-writer.md"), 0o600)
        self.assertEqual(stat_mode(self.user_ad_hoc), 0o700)
        self.assertEqual(stat_mode(self.user_crew), 0o700)

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

    def test_awkward_characters_round_trip_through_resolve_exactly(self):
        body = self.body_file(raw=TRICKY_BODY.encode())
        done = self.adhoc(pick_me_when=TRICKY, body_file=body, skill=["a:b", "c.d_e-f"])
        self.assertEqual(done.returncode, 0, done.stderr)
        members, warnings = self.listed()
        self.assertEqual(warnings, [])
        got = members["notes-writer"]
        self.assertEqual((got["pick-me-when"], got["instructions"]), (TRICKY, TRICKY_BODY))
        self.assertEqual(got["skills"], ["a:b", "c.d_e-f"])

    def test_the_body_file_is_read_never_run(self):
        marker = self.w.root / "ran"
        body = self.body_file(raw=f"#!/bin/sh\ntouch {marker}\n$(touch {marker})\n".encode())
        body.chmod(0o755)
        self.assertEqual(self.adhoc(body_file=body).returncode, 0)
        self.assertFalse(marker.exists())


def stat_mode(path):
    return Path(path).stat().st_mode & 0o777


class AdhocRefusals(AdHocCase):
    def test_each_check_refuses_with_one_error_and_writes_nothing(self):
        self.w.write_member("repo", "repo-member", "scribe")
        cases = {
            "name not a slug": {"name": "Bad_Name"},
            "role not a slug": {"role": "UPPER"},
            "role fix-checker": {"role": "fix-checker"},
            "custom role without based-on": {"role": "changelog"},
            "custom role, unknown based-on": {"role": "changelog", "based_on": "nonsense"},
            "built-in role with based-on": {"role": "scribe", "based_on": "implementer"},
            "bad harness": {"harness": "gemini"},
            "bad skill": {"skill": ["ok", "bad skill"]},
            "bad model": {"model": "has space"},
            "blank pick-me-when": {"pick_me_when": " \t "},
            "pick-me-when with a newline": {"pick_me_when": "a\nb"},
            "name of a built-in member": {"name": "scribe"},
            "name of a repo member": {"name": "repo-member"},
            "body file missing": {"body_file": self.w.run / "prompts" / "absent.md"},
            "body not UTF-8": {"body_file": self.body_file(raw=b"bad \xff\xfe", name="latin1.md")},
            "body and frontmatter over the cap": {
                "body_file": self.body_file(raw=b"x" * (MAX_BYTES - 20), name="edge.md")
            },
        }
        for label, kw in cases.items():
            with self.subTest(label):
                self.assert_refused(label, **kw)

    def test_a_name_that_exists_as_a_file_in_the_ad_hoc_directory_is_refused_and_kept(self):
        path = self.put_ad_hoc("notes-writer", run="run-b")
        before = path.read_bytes()
        self.assert_refused("another run's file")
        self.assertEqual(path.read_bytes(), before)

    def test_a_symlink_named_like_the_member_is_refused_and_its_target_never_written(self):
        self.user_ad_hoc.mkdir(parents=True)
        target = self.w.root / "victim.md"
        (self.user_ad_hoc / "notes-writer.md").symlink_to(target)
        self.assert_refused("dangling")
        self.assertFalse(target.exists())
        target.write_text("keep me\n")
        self.assert_refused("live symlink")
        self.assertEqual(target.read_text(), "keep me\n")

    def test_a_symlinked_ad_hoc_directory_is_refused(self):
        elsewhere = self.w.root / "elsewhere"
        elsewhere.mkdir()
        self.user_crew.mkdir(parents=True)
        self.user_ad_hoc.symlink_to(elsewhere)
        self.assert_refused("ad-hoc symlink")
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_a_symlinked_xdg_config_home_is_allowed(self):
        real = self.w.root / "real-xdg"
        real.mkdir()
        link = self.w.root / "xdg-link"
        link.symlink_to(real)
        done = self.adhoc(env=self.w.env(XDG_CONFIG_HOME=str(link)))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((real / "commodore" / "crew" / "ad-hoc" / "notes-writer.md").is_file())

    def test_the_ad_hoc_directory_may_never_be_in_the_repo_or_a_commodore_directory(self):
        places = {
            "xdg inside the repo, nothing there yet": self.w.repo / "cfg",
            "xdg inside a .commodore directory": self.w.root / "other" / ".commodore" / "xdg",
        }
        for label, xdg in places.items():
            with self.subTest(label):
                self.assert_refused(label, env=self.w.env(XDG_CONFIG_HOME=str(xdg)))
        self.assertEqual(list(self.w.repo.rglob("ad-hoc")), [])

    def test_a_dot_dot_after_a_symlink_into_the_repo_is_refused_outside_and_inside_admiral(self):
        xdg = self.dotdot_after_a_symlink("cfg")
        self.assert_refused("xdg", env=self.w.env(XDG_CONFIG_HOME=xdg))
        fleet = self.dotdot_after_a_symlink("fleet")
        (self.w.repo / "fleet").mkdir()
        self.assert_refused("fleet", env=self.w.admiral_env() | {"ADMIRAL_CREW_DIR": fleet})
        self.assertEqual(list(self.w.repo.rglob("ad-hoc")), [])
        self.assertEqual(list(self.w.repo.rglob("cfg")), [])

    def test_inside_admiral_an_empty_unset_or_missing_fleet_directory_is_refused(self):
        envs = {
            "empty": self.w.admiral_env() | {"ADMIRAL_CREW_DIR": ""},
            "unset": self.w.env(ADMIRAL_SHIP="ship-1"),
            "missing": self.w.admiral_env(),
        }
        for label, env in envs.items():
            with self.subTest(label):
                self.assert_refused(label, env=env)

    def test_the_body_file_must_be_a_regular_file_inside_the_runs_prompts_directory(self):
        outside = self.w.root / "outside.md"
        outside.write_text("outside\n")
        prompts = self.w.run / "prompts"
        (prompts / "link-out.md").symlink_to(outside)
        (prompts / "subdir").mkdir()
        (self.w.run / "in-run-dir.md").write_text("x\n")
        cases = {
            "in the run dir, not prompts": self.w.run / "in-run-dir.md",
            "symlink out of prompts": prompts / "link-out.md",
            "a directory": prompts / "subdir",
        }
        for label, path in cases.items():
            with self.subTest(label):
                self.assert_refused(label, body_file=path)

    def test_resolve_errors_stop_the_write_and_are_printed_as_error_lines(self):
        self.w.layer_dirs["repo"].mkdir(parents=True)
        (self.w.layer_dirs["repo"] / "broken.md").write_text("no frontmatter\n")
        done = self.assert_refused("resolve errors")
        self.assertIn("broken.md", done.stderr)
        self.assertIn("bad-frontmatter", done.stderr)

    def test_usage_errors_exit_5_and_write_nothing(self):
        self.assert_refused("missing --name", code=5, name=None)
        before = self.snapshot()
        done = self.w.sh([self.w.crew_py, "adhoc", *self.adhoc_args(), "--bogus", "x"])
        self.assertEqual((done.returncode, done.stdout), (5, ""), done.stderr)
        self.assert_world_is(before)


if __name__ == "__main__":
    unittest.main()
