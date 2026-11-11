"""Tests for `crew.py resolve` over layered Markdown member files, in explicit `--layer` and `--run` mode."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from crew_world import BASE_PATH

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMMODORE = REPO / "skills" / "engineering" / "commodore"
CREW_PY = COMMODORE / "scripts" / "crew.py"
BUILTIN_DIR = COMMODORE / "crew"
FIXTURES = REPO / "fixtures" / "crew-resolution"
CASES = FIXTURES / "cases"

OK, ERRORS, USAGE = 0, 1, 5
ROLES = [
    "implementer",
    "test-writer",
    "reviewer",
    "security-reviewer",
    "brief-checker",
    "triager",
    "target-steward",
    "scribe",
    "fix-checker",
]


def strip_messages(obj):
    """Drop every `message` from errors and warnings, as the fixtures README says to compare."""
    out = dict(obj)
    for key in ("errors", "warnings"):
        if key in out:
            out[key] = [{k: v for k, v in item.items() if k != "message"} for item in out[key]]
    return out


def base_env(home, **extra):
    env = {"PATH": BASE_PATH, "HOME": str(home), "LANG": "en_US.UTF-8"}
    env.update({k: v for k, v in extra.items() if v is not None})
    return env


def member_text(name, role, pick=None, body=None, extra=""):
    pick = pick if pick is not None else f"Pick {name}."
    body = body if body is not None else f"Body of {name}."
    return f"---\nname: {name}\nrole: {role}\npick-me-when: {pick}\n{extra}---\n\n{body}\n"


class ResolverCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="crew-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.tmp = Path(tmp).resolve()

    def crew(self, args, env, script=None):
        return subprocess.run(
            [str(script or CREW_PY), *[str(a) for a in args]],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            cwd=self.tmp,
        )

    def explicit(self, layers, admiral=False, extra_env=None, run_id=None):
        """Run explicit mode over {label: dir}; returns (proc, parsed stdout or None)."""
        args = ["resolve"] + (["--admiral"] if admiral else [])
        for label, path in layers.items():
            args += ["--layer", f"{label}={path}"]
        if run_id is not None:
            args += ["--run-id", run_id]
        proc = self.crew(args, base_env(self.tmp / "home", **(extra_env or {})))
        return proc, (json.loads(proc.stdout) if proc.stdout.strip() else None)

    def layer(self, label, files):
        """Write {name: str|bytes} into tmp/layers/<label> and return the directory."""
        d = self.tmp / "layers" / label
        d.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            path = d / name
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8", newline="")
        return d


class World:
    """A temp world for `--run`: crew.py with its built-in `crew/`, a run dir, a repo and a home."""

    def __init__(self, test):
        self.test = test
        root = test.tmp
        self.script = root / "skill" / "scripts" / "crew.py"
        self.script.parent.mkdir(parents=True)
        shutil.copy2(CREW_PY, self.script)
        self.builtin = root / "skill" / "crew"
        self.builtin.mkdir()
        self.home = root / "home"
        self.home.mkdir()
        self.run_dir = root / "run"
        self.run_dir.mkdir()
        self.repo = root / "repo"
        self.repo.mkdir()
        self.user_global = self.home / ".config" / "commodore" / "crew"
        self.repo_crew = self.repo / ".commodore" / "crew"
        self.run_crew = self.run_dir / "crew"
        self.fleet = root / "fleet"
        self.admiral_run_crew = root / "admiral-run-crew"

    def put(self, directory, name, role):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.md").write_text(member_text(name, role), encoding="utf-8")

    def team_env(self, text):
        (self.run_dir / "team.env").write_text(text, encoding="utf-8")

    def resolve(self, **env):
        proc = self.test.crew(["resolve", "--run", self.run_dir], base_env(self.home, **env), script=self.script)
        return proc, (json.loads(proc.stdout) if proc.stdout.strip() else None)

    @staticmethod
    def layers_of(parsed):
        return {m["name"]: m["layer"] for m in parsed["members"]}


def case_names():
    return sorted(p.name for p in CASES.iterdir() if p.is_dir()) if CASES.is_dir() else []


def load_case(name):
    case = CASES / name
    meta = json.loads((case / "case.json").read_text())
    expected = json.loads((case / "expected.json").read_text())
    return case, meta, expected


class FixtureCases(ResolverCase):
    def check(self, proc, expected):
        self.assertEqual(proc.returncode, expected["exit"], proc.stderr)
        want = {k: v for k, v in expected.items() if k != "exit"}
        self.assertEqual(strip_messages(json.loads(proc.stdout)), want)

    def copy_case(self, name):
        dest = self.tmp / "case"
        shutil.copytree(CASES / name, dest, symlinks=True)
        return dest

    def run_explicit(self, name):
        _, meta, expected = load_case(name)
        copy = self.copy_case(name)
        ignored = "user-global" if meta["admiral"] else "fleet"
        layers = {d.name: d for d in sorted((copy / "layers").iterdir()) if d.is_dir() and d.name != ignored}
        proc, _ = self.explicit(layers, admiral=meta["admiral"], run_id=meta.get("run"))
        self.check(proc, expected)


def make_case_test(name):
    def test(self):
        self.run_explicit(name)

    return test


for _name in case_names():
    setattr(FixtureCases, "test_" + _name.replace("-", "_"), make_case_test(_name))


class ExplicitMode(ResolverCase):
    def test_missing_layer_directory_is_an_empty_layer(self):
        proc, parsed = self.explicit({"repo": self.tmp / "does-not-exist"})
        self.assertEqual((proc.returncode, parsed), (OK, {"members": [], "warnings": []}), proc.stderr)

    def test_members_are_sorted_by_name_and_keep_utf8_text(self):
        d = self.layer("repo", {"b.md": member_text("b", "scribe", body="café ✓"), "a.md": member_text("a", "scribe")})
        proc, parsed = self.explicit({"repo": d})
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(parsed["members"][1]["instructions"], "café ✓")
        self.assertEqual([m["name"] for m in parsed["members"]], ["a", "b"])

    def test_non_utf8_file_is_a_bad_frontmatter_error(self):
        good = member_text("good", "scribe")
        files = {
            "good.md": good,
            "latin1-body.md": b"---\nname: latin1-body\nrole: scribe\npick-me-when: P\n---\n\nbody \xff\xfe\n",
            "latin1-front.md": b"---\nname: latin1-front\nrole: scribe\npick-me-when: caf\xe9\n---\n",
        }
        proc, parsed = self.explicit({"repo": self.layer("repo", files)})
        self.assertEqual(proc.returncode, ERRORS, proc.stderr)
        got = [(e["file"], e["code"]) for e in parsed["errors"]]
        self.assertEqual(got, [("latin1-body.md", "bad-frontmatter"), ("latin1-front.md", "bad-frontmatter")])

    def test_byte_order_mark_is_a_bad_frontmatter_error(self):
        files = {"bom.md": b"\xef\xbb\xbf" + member_text("bom", "scribe").encode()}
        proc, parsed = self.explicit({"repo": self.layer("repo", files)})
        self.assertEqual(proc.returncode, ERRORS, proc.stderr)
        self.assertEqual([(e["file"], e["code"]) for e in parsed["errors"]], [("bom.md", "bad-frontmatter")])

    def test_crlf_file_resolves_like_its_lf_twin(self):
        text = member_text("twin", "scribe", pick="Same.", body="line one\n\nline two", extra="skills: [a, b]\n")
        crlf = self.layer("crlf", {"twin.md": text.replace("\n", "\r\n").encode()})
        lf = self.layer("lf", {"twin.md": text})
        got_crlf = self.explicit({"repo": crlf})[1]
        got_lf = self.explicit({"repo": lf})[1]
        self.assertEqual(got_crlf, got_lf)
        self.assertEqual(got_lf["members"][0]["instructions"], "line one\n\nline two")

    def test_only_lowercase_md_files_are_members(self):
        files = {"UPPER.MD": "garbage\n", "Mixed.Md": "garbage\n", "keep.md": member_text("keep", "scribe")}
        proc, parsed = self.explicit({"repo": self.layer("repo", files)})
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual([m["name"] for m in parsed["members"]], ["keep"])

    def test_symlinked_layer_directory_is_allowed(self):
        real = self.layer("real", {"x.md": member_text("x", "scribe")})
        (real / "store").mkdir()
        (real / "store" / "y.md").write_text(member_text("y", "scribe"), encoding="utf-8")
        (real / "y.md").symlink_to("store/y.md")
        link = self.tmp / "layers" / "link"
        link.symlink_to(real)
        proc, parsed = self.explicit({"repo": link})
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual([m["name"] for m in parsed["members"]], ["x", "y"])
        self.assertEqual(parsed["warnings"], [])

    def test_member_file_is_never_executed(self):
        marker = self.tmp / "executed-marker"
        evil = f"$(touch {marker})"
        tick = f"`touch {marker}`"
        body = f"#!/usr/bin/env python3\nopen({str(marker)!r}, 'w')\n{evil}\n{tick}"
        text = member_text("evil", "scribe", pick=f"Pick {evil}", body=body, extra=f"model: {tick}\n")
        d = self.layer("repo", {"evil.md": text})
        d.joinpath("evil.md").chmod(0o755)
        proc, parsed = self.explicit({"repo": d})
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertFalse(marker.exists(), "a member file was executed")
        member = parsed["members"][0]
        self.assertEqual(member["instructions"], body)
        self.assertEqual(member["pick-me-when"], f"Pick {evil}")
        self.assertEqual(member["model"], tick)

    def test_unreadable_file_and_unlistable_layer_are_errors_not_tracebacks(self):
        if os.geteuid() == 0:
            self.skipTest("root reads files whatever their mode")
        d = self.layer("repo", {"locked.md": member_text("locked", "scribe"), "fine.md": member_text("fine", "scribe")})
        (d / "locked.md").chmod(0o000)
        self.addCleanup((d / "locked.md").chmod, 0o644)
        hidden = self.layer("user-global", {"x.md": member_text("x", "scribe")})
        hidden.chmod(0o000)
        self.addCleanup(hidden.chmod, 0o755)
        proc, parsed = self.explicit({"user-global": hidden, "repo": d})
        self.assertEqual(proc.returncode, ERRORS, proc.stderr)
        self.assertEqual(
            strip_messages(parsed),
            {
                "errors": [
                    {"layer": "user-global", "file": None, "code": "unreadable", "field": None},
                    {"layer": "repo", "file": "locked.md", "code": "unreadable", "field": None},
                ],
                "warnings": [],
            },
        )


class UsageErrors(ResolverCase):
    def test_bad_calls_exit_5_with_a_usage_message_and_no_stdout(self):
        run_dir = self.tmp / "run"
        run_dir.mkdir()
        (run_dir / "team.env").write_text("REPO=/nowhere\n")
        calls = {
            "unknown subcommand": ["frobnicate"],
            "fleet without --admiral": ["resolve", "--layer", f"fleet={self.tmp}"],
            "--run with --layer": ["resolve", "--run", run_dir, "--layer", f"repo={self.tmp}"],
            "ad-hoc without --run-id": ["resolve", "--layer", f"ad-hoc={self.tmp}"],
        }
        for label, args in calls.items():
            with self.subTest(label):
                proc = self.crew(args, base_env(self.tmp))
                self.assertEqual(proc.returncode, USAGE, proc.stderr)
                self.assertEqual(proc.stdout, "")
                self.assertTrue(proc.stderr.strip(), "no usage message on stderr")


class RunMode(ResolverCase):
    def setUp(self):
        super().setUp()
        self.w = World(self)

    def fill(self):
        w = self.w
        w.put(w.builtin, "implementer", "implementer")
        w.put(w.user_global, "reviewer", "reviewer")
        w.put(w.fleet, "scribe", "scribe")
        w.put(w.repo_crew, "triager", "triager")
        w.put(w.run_crew, "brief-checker", "brief-checker")
        w.put(w.admiral_run_crew, "test-writer", "test-writer")
        w.team_env(f"REPO={w.repo}\n")

    def test_outside_admiral_reads_user_global_repo_and_run_slash_crew(self):
        self.fill()
        proc, parsed = self.w.resolve(ADMIRAL_CREW_DIR=str(self.w.fleet), ADMIRAL_RUN_CREW=str(self.w.admiral_run_crew))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(
            self.w.layers_of(parsed),
            {"implementer": "built-in", "reviewer": "user-global", "triager": "repo", "brief-checker": "run"},
        )

    def test_xdg_config_home_moves_the_user_global_layer(self):
        self.fill()
        xdg = self.tmp / "xdg"
        self.w.put(xdg / "commodore" / "crew", "target-steward", "target-steward")
        proc, parsed = self.w.resolve(XDG_CONFIG_HOME=str(xdg))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        layers = self.w.layers_of(parsed)
        self.assertEqual(layers["target-steward"], "user-global")
        self.assertNotIn("reviewer", layers)

    def test_inside_admiral_reads_fleet_and_admiral_run_crew_and_ignores_user_global(self):
        self.fill()
        self.w.put(self.w.fleet / "ad-hoc", "ghost", "scribe")
        proc, parsed = self.w.resolve(
            ADMIRAL_SHIP="ship-1", ADMIRAL_CREW_DIR=str(self.w.fleet), ADMIRAL_RUN_CREW=str(self.w.admiral_run_crew)
        )
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(
            self.w.layers_of(parsed),
            {"implementer": "built-in", "scribe": "fleet", "triager": "repo", "test-writer": "run"},
        )

    def test_admiral_ship_in_team_env_counts_when_the_environment_does_not_set_it(self):
        self.fill()
        self.w.team_env(f"REPO={self.w.repo}\nADMIRAL_SHIP=ship-2\n")
        proc, parsed = self.w.resolve(ADMIRAL_CREW_DIR=str(self.w.fleet), ADMIRAL_RUN_CREW=str(self.w.admiral_run_crew))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        layers = self.w.layers_of(parsed)
        self.assertEqual((layers["scribe"], layers["test-writer"]), ("fleet", "run"))
        self.assertNotIn("reviewer", layers)

    def test_an_empty_admiral_ship_in_the_environment_beats_one_in_team_env(self):
        self.fill()
        self.w.team_env(f"REPO={self.w.repo}\nADMIRAL_SHIP=ship-x\n")
        proc, parsed = self.w.resolve(ADMIRAL_SHIP="", ADMIRAL_CREW_DIR=str(self.w.fleet))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        layers = self.w.layers_of(parsed)
        self.assertIn("reviewer", layers)
        self.assertNotIn("scribe", layers)

    def test_inside_admiral_the_environment_beats_team_env_for_the_fleet_and_run_dirs(self):
        self.fill()
        other_fleet, other_run = self.tmp / "other-fleet", self.tmp / "other-run"
        self.w.put(other_fleet, "target-steward", "target-steward")
        self.w.put(other_run, "fix-checker", "fix-checker")
        self.w.team_env(
            f"REPO={self.w.repo}\nADMIRAL_CREW_DIR={self.w.fleet}\nADMIRAL_RUN_CREW={self.w.admiral_run_crew}\n"
        )
        proc, parsed = self.w.resolve(
            ADMIRAL_SHIP="ship-5", ADMIRAL_CREW_DIR=str(other_fleet), ADMIRAL_RUN_CREW=str(other_run)
        )
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(
            self.w.layers_of(parsed),
            {"implementer": "built-in", "target-steward": "fleet", "triager": "repo", "fix-checker": "run"},
        )

    def test_an_empty_admiral_dir_in_the_environment_beats_team_env_and_never_falls_back_to_run_crew(self):
        self.fill()
        self.w.team_env(f"REPO={self.w.repo}\nADMIRAL_CREW_DIR={self.w.fleet}\nADMIRAL_RUN_CREW={self.w.run_crew}\n")
        proc, parsed = self.w.resolve(ADMIRAL_SHIP="ship-6", ADMIRAL_CREW_DIR="", ADMIRAL_RUN_CREW="")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(self.w.layers_of(parsed), {"implementer": "built-in", "triager": "repo"})

    def test_team_env_values_are_parsed_as_text(self):
        w = self.w
        w.put(w.builtin, "implementer", "implementer")
        variants = {
            "double quotes": ('REPO="{p}"', "with space"),
            "unquoted with a trailing comment": ("REPO={p} # the repo", "commented"),
            "last assignment wins": ("REPO=/wrong/place\nREPO={p}", "last"),
        }
        for label, (line, dirname) in variants.items():
            with self.subTest(label):
                repo = self.tmp / "repos" / dirname
                shutil.rmtree(self.tmp / "repos", ignore_errors=True)
                w.put(repo / ".commodore" / "crew", "triager", "triager")
                w.team_env("# a comment\n\n" + line.format(p=repo) + "\n")
                proc, parsed = w.resolve()
                self.assertEqual(proc.returncode, OK, proc.stderr)
                self.assertEqual(self.w.layers_of(parsed).get("triager"), "repo")

    def test_team_env_is_never_sourced(self):
        w = self.w
        marker = self.tmp / "sourced-marker"
        w.put(w.builtin, "implementer", "implementer")
        w.put(w.repo_crew, "triager", "triager")
        w.team_env(f"X=$(touch {marker})\nY=`touch {marker}`\ntouch {marker}\nREPO={w.repo}\n")
        proc, parsed = w.resolve()
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertFalse(marker.exists(), "team.env was sourced or evaluated")
        self.assertEqual(self.w.layers_of(parsed).get("triager"), "repo")

    def test_worktree_stands_in_when_repo_is_missing(self):
        w = self.w
        w.put(w.repo_crew, "triager", "triager")
        w.team_env(f"WORKTREE={w.repo}\n")
        proc, parsed = w.resolve()
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(self.w.layers_of(parsed).get("triager"), "repo")

    def test_repo_wins_over_worktree_when_both_are_set(self):
        w = self.w
        other = self.tmp / "other-worktree"
        w.put(w.repo_crew, "triager", "triager")
        w.put(other / ".commodore" / "crew", "scribe", "scribe")
        w.team_env(f"REPO={w.repo}\nWORKTREE={other}\n")
        proc, parsed = w.resolve()
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(self.w.layers_of(parsed), {"triager": "repo"})


class ShippedBuiltIns(ResolverCase):
    def test_built_in_set_resolves_to_one_member_per_role(self):
        proc, parsed = self.explicit({"built-in": BUILTIN_DIR})
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual([m["name"] for m in parsed["members"]], sorted(ROLES))
        for member in parsed["members"]:
            self.assertEqual(member["role"], member["name"])


if __name__ == "__main__":
    unittest.main()
