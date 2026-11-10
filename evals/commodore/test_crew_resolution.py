"""Tests for the crew member resolver (issue #199, unit u1): `crew.py resolve` over layered Markdown member files.

Seams are `crew.py resolve` as a subprocess (explicit `--layer` mode and `--run` mode), its stdout JSON and exit
code, and the fixture directory layout in fixtures/crew-resolution/. Expected values come from the unit spec (the
issue's Agent Brief, docs/adr/0007 and the coordinator's rules), never from the resolver: the fixtures' expected.json
files were generated from spec-derived expectations by a throwaway script, never from a resolver.

Every fixture case runs twice: through explicit `--layer` mode (the ignored layer's directory is left out, because that
mode rejects it with exit 5) and through `--run` mode (every layer directory is placed where `--run` looks for it, and
the ignored layer's directory is placed too, which proves it is ignored). Inputs that can't be committed safely
(non-UTF-8 bytes, a BOM, CRLF, upper-case extensions) are generated here.

Run from the repo root: python3 -m unittest discover -s evals/commodore -p 'test_crew_resolution.py' -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

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
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
MAX_BUILTIN_BODY = 1000


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
    """Base class: every test needs the resolver script, so a missing script is the red failure."""

    def setUp(self):
        self.assertTrue(CREW_PY.is_file(), f"{CREW_PY.relative_to(REPO)} does not exist yet")
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

    def explicit(self, layers, admiral=False, extra_env=None):
        """Run explicit mode over {label: dir}; returns (proc, parsed stdout or None)."""
        args = ["resolve"] + (["--admiral"] if admiral else [])
        for label, path in layers.items():
            args += ["--layer", f"{label}={path}"]
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


# ---------------------------------------------------------------------------------------------------- run-mode world
class World:
    """A temp world for `--run`: a copy of crew.py beside its own `crew/` built-in directory, a run dir, a repo and a
    home."""

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


# ---------------------------------------------------------------------------------------------------- fixture cases
def case_names():
    return sorted(p.name for p in CASES.iterdir() if p.is_dir()) if CASES.is_dir() else []


def load_case(name):
    case = CASES / name
    meta = json.loads((case / "case.json").read_text())
    expected = json.loads((case / "expected.json").read_text())
    return case, meta, expected


class FixtureCases(ResolverCase):
    def check(self, proc, expected):
        want_exit = expected["exit"]
        self.assertEqual(proc.returncode, want_exit, proc.stderr)
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
        proc, _ = self.explicit(layers, admiral=meta["admiral"])
        self.check(proc, expected)

    def run_via_run_mode(self, name):
        _, meta, expected = load_case(name)
        copy = self.copy_case(name)
        world = World(self)
        layers = copy / "layers"

        def link(target, link_path):
            link_path.parent.mkdir(parents=True, exist_ok=True)
            link_path.symlink_to(target)

        if (layers / "built-in").is_dir():
            shutil.rmtree(world.builtin)
            link(layers / "built-in", world.builtin)
        if (layers / "user-global").is_dir():
            link(layers / "user-global", world.user_global)
        if (layers / "repo").is_dir():
            link(layers / "repo", world.repo_crew)
        world.team_env(f"REPO={world.repo}\n")
        env = {}
        if meta["admiral"]:
            env["ADMIRAL_SHIP"] = "ship-1"
            if (layers / "fleet").is_dir():
                env["ADMIRAL_CREW_DIR"] = str(layers / "fleet")
            if (layers / "run").is_dir():
                env["ADMIRAL_RUN_CREW"] = str(layers / "run")
        else:
            if (layers / "fleet").is_dir():
                env["ADMIRAL_CREW_DIR"] = str(layers / "fleet")  # set, but outside Admiral it is ignored
            if (layers / "run").is_dir():
                link(layers / "run", world.run_crew)
        proc, _ = world.resolve(**env)
        self.check(proc, expected)


def make_case_tests(name):
    def explicit(self):
        self.run_explicit(name)

    def via_run(self):
        self.run_via_run_mode(name)

    return explicit, via_run


for _name in case_names():
    _explicit, _via_run = make_case_tests(_name)
    setattr(FixtureCases, "test_explicit_" + _name.replace("-", "_"), _explicit)
    setattr(FixtureCases, "test_run_mode_" + _name.replace("-", "_"), _via_run)


class FixtureCoverage(unittest.TestCase):
    """The fixture set itself: shape, and that it covers what the unit spec says it must. These tests guard the
    fixtures, not the resolver, so they pass before crew.py exists: the one deliberate exception to "every test red"."""

    ERROR_CODES = frozenset(
        {
            "too-large",
            "outside-layer",
            "bad-frontmatter",
            "missing-field",
            "bad-name",
            "name-mismatch",
            "bad-field",
            "bad-harness",
        }
    )
    WARNING_CODES = frozenset(
        {
            "unknown-field",
            "bad-skill",
            "fix-checker-skills",
            "fix-checker-instructions",
            "bad-based-on",
            "misplaced-ad-hoc",
            "role-change",
        }
    )

    def test_cases_have_the_documented_shape_and_cover_every_code(self):
        self.assertTrue(CASES.is_dir(), "fixtures/crew-resolution/cases is missing")
        errors, warnings = set(), set()
        for name in case_names():
            case, meta, expected = load_case(name)
            self.assertEqual(set(meta), {"description", "admiral"}, name)
            self.assertIsInstance(meta["admiral"], bool, name)
            self.assertTrue((case / "layers").is_dir(), name)
            self.assertIn(expected["exit"], (OK, ERRORS), name)
            expected_keys = (
                {"members", "warnings", "exit"} if expected["exit"] == OK else {"errors", "warnings", "exit"}
            )
            self.assertEqual(set(expected), expected_keys, name)
            for item in expected["warnings"] + expected.get("errors", []):
                self.assertEqual(set(item), {"layer", "file", "code", "field"}, name)
            errors |= {e["code"] for e in expected.get("errors", [])}
            warnings |= {w["code"] for w in expected["warnings"]}
        self.assertEqual(errors, set(self.ERROR_CODES))
        self.assertEqual(warnings, set(self.WARNING_CODES))

    def test_readme_and_nested_lint_config_are_in_place(self):
        readme = (FIXTURES / "README.md").read_text()
        for needle in ("ADMIRAL_CREW_DIR", "ADMIRAL_RUN_CREW", "message", "symlink", "crew-members.md", "non-UTF-8"):
            self.assertIn(needle, readme)
        lint_config = json.loads((CASES / ".markdownlint-cli2.jsonc").read_text())
        self.assertEqual(lint_config, {"config": {"default": False}})


# ---------------------------------------------------------------------------------------------------- explicit mode
class ExplicitMode(ResolverCase):
    def test_missing_layer_directory_is_an_empty_layer(self):
        proc, parsed = self.explicit({"repo": self.tmp / "does-not-exist"})
        self.assertEqual((proc.returncode, parsed), (OK, {"members": [], "warnings": []}), proc.stderr)

    def test_admiral_with_no_layers_is_an_empty_resolution(self):
        proc, parsed = self.explicit({}, admiral=True)
        self.assertEqual((proc.returncode, parsed), (OK, {"members": [], "warnings": []}), proc.stderr)

    def test_stdout_is_one_sorted_indented_json_object(self):
        d = self.layer("repo", {"b.md": member_text("b", "scribe", body="café ✓"), "a.md": member_text("a", "scribe")})
        proc, parsed = self.explicit({"repo": d})
        self.assertEqual(proc.returncode, OK, proc.stderr)
        text = proc.stdout.rstrip("\n")
        ascii_form = json.dumps(parsed, sort_keys=True, indent=2)
        utf8_form = json.dumps(parsed, sort_keys=True, indent=2, ensure_ascii=False)
        self.assertIn(text, (ascii_form, utf8_form))
        self.assertEqual(parsed["members"][1]["instructions"], "café ✓")
        self.assertEqual([m["name"] for m in parsed["members"]], ["a", "b"])

    def test_error_output_has_no_members_key(self):
        d = self.layer("repo", {"broken.md": "nope\n", "fine.md": member_text("fine", "scribe")})
        proc, parsed = self.explicit({"repo": d})
        self.assertEqual(proc.returncode, ERRORS)
        self.assertNotIn("members", parsed)
        self.assertEqual([(e["file"], e["code"]) for e in parsed["errors"]], [("broken.md", "bad-frontmatter")])

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

    def test_unreadable_member_file_is_an_error_not_a_traceback(self):
        if os.geteuid() == 0:
            self.skipTest("root reads files whatever their mode")
        d = self.layer("repo", {"locked.md": member_text("locked", "scribe"), "fine.md": member_text("fine", "scribe")})
        (d / "locked.md").chmod(0o000)
        self.addCleanup((d / "locked.md").chmod, 0o644)
        proc, parsed = self.explicit({"repo": d})
        self.assertEqual(proc.returncode, ERRORS, proc.stderr)
        self.assertEqual(
            strip_messages(parsed),
            {"errors": [{"layer": "repo", "file": "locked.md", "code": "unreadable", "field": None}], "warnings": []},
        )

    def test_unlistable_layer_directory_is_an_error_with_a_null_file_sorted_first(self):
        if os.geteuid() == 0:
            self.skipTest("root lists directories whatever their mode")
        locked = self.layer("repo", {"x.md": member_text("x", "scribe")})
        locked.chmod(0o000)
        self.addCleanup(locked.chmod, 0o755)
        broken = self.layer("user-global", {"bad.md": "nope\n"})
        proc, parsed = self.explicit({"user-global": broken, "repo": locked})
        self.assertEqual(proc.returncode, ERRORS, proc.stderr)
        self.assertEqual(
            strip_messages(parsed)["errors"],
            [
                {"layer": "user-global", "file": "bad.md", "code": "bad-frontmatter", "field": None},
                {"layer": "repo", "file": None, "code": "unreadable", "field": None},
            ],
        )

    def test_file_name_that_is_not_utf8_is_skipped(self):
        d = self.layer("repo", {"keep.md": member_text("keep", "scribe")})
        try:
            (d.parent.joinpath("repo").joinpath(os.fsdecode(b"bad-\xff.md"))).write_text("x")
        except OSError:
            self.skipTest("this file system rejects non-UTF-8 names")
        proc, parsed = self.explicit({"repo": d})
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual([m["name"] for m in parsed["members"]], ["keep"])


class UsageErrors(ResolverCase):
    def test_bad_calls_exit_5_with_a_usage_message_and_no_stdout(self):
        run_dir = self.tmp / "run"
        run_dir.mkdir()
        (run_dir / "team.env").write_text("REPO=/nowhere\n")
        calls = {
            "no subcommand": [],
            "unknown subcommand": ["frobnicate"],
            "unknown flag": ["resolve", "--bogus"],
            "unknown label": ["resolve", "--layer", f"bogus={self.tmp}"],
            "label twice": ["resolve", "--layer", f"repo={self.tmp}", "--layer", f"repo={self.tmp}"],
            "no equals sign": ["resolve", "--layer", "repo"],
            "user-global with --admiral": ["resolve", "--admiral", "--layer", f"user-global={self.tmp}"],
            "fleet without --admiral": ["resolve", "--layer", f"fleet={self.tmp}"],
            "--run with --layer": ["resolve", "--run", run_dir, "--layer", f"repo={self.tmp}"],
            "--run with --admiral": ["resolve", "--run", run_dir, "--admiral"],
            "--run twice": ["resolve", "--run", run_dir, "--run", run_dir],
            "--run empty": ["resolve", "--run", ""],
            "--run without a value": ["resolve", "--run"],
        }
        for label, args in calls.items():
            with self.subTest(label):
                proc = self.crew(args, base_env(self.tmp))
                self.assertEqual(proc.returncode, USAGE, proc.stderr)
                self.assertEqual(proc.stdout, "")
                self.assertTrue(proc.stderr.strip(), "no usage message on stderr")

    def test_fleet_with_admiral_and_user_global_without_are_accepted(self):
        d = self.layer("x", {})
        self.assertEqual(self.explicit({"fleet": d}, admiral=True)[0].returncode, OK)
        self.assertEqual(self.explicit({"user-global": d})[0].returncode, OK)


# ---------------------------------------------------------------------------------------------------- run mode
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

    def test_empty_xdg_config_home_counts_as_unset(self):
        self.fill()
        proc, parsed = self.w.resolve(XDG_CONFIG_HOME="")
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(self.w.layers_of(parsed)["reviewer"], "user-global")

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

    def test_admiral_ship_in_the_environment_beats_an_empty_one_in_team_env(self):
        self.fill()
        self.w.team_env(f"REPO={self.w.repo}\nADMIRAL_SHIP=\n")
        proc, parsed = self.w.resolve(ADMIRAL_SHIP="ship-3", ADMIRAL_CREW_DIR=str(self.w.fleet))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        layers = self.w.layers_of(parsed)
        self.assertIn("scribe", layers)
        self.assertNotIn("reviewer", layers)

    def test_an_empty_admiral_ship_in_the_environment_beats_one_in_team_env(self):
        self.fill()
        self.w.team_env(f"REPO={self.w.repo}\nADMIRAL_SHIP=ship-x\n")
        proc, parsed = self.w.resolve(ADMIRAL_SHIP="", ADMIRAL_CREW_DIR=str(self.w.fleet))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        layers = self.w.layers_of(parsed)
        self.assertIn("reviewer", layers)
        self.assertNotIn("scribe", layers)

    def test_an_empty_admiral_ship_everywhere_means_outside_admiral(self):
        self.fill()
        self.w.team_env(f"REPO={self.w.repo}\nADMIRAL_SHIP=\n")
        proc, parsed = self.w.resolve(ADMIRAL_CREW_DIR=str(self.w.fleet))
        self.assertEqual(proc.returncode, OK, proc.stderr)
        layers = self.w.layers_of(parsed)
        self.assertIn("reviewer", layers)
        self.assertNotIn("scribe", layers)

    def test_inside_admiral_team_env_names_the_fleet_and_run_dirs(self):
        self.fill()
        self.w.team_env(
            f"REPO={self.w.repo}\nADMIRAL_SHIP=ship-4\n"
            f"ADMIRAL_CREW_DIR={self.w.fleet}\nADMIRAL_RUN_CREW='{self.w.admiral_run_crew}'\n"
        )
        proc, parsed = self.w.resolve()
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(
            self.w.layers_of(parsed),
            {"implementer": "built-in", "scribe": "fleet", "triager": "repo", "test-writer": "run"},
        )

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

    def test_unset_or_empty_admiral_dirs_are_empty_layers(self):
        self.fill()
        for env in (
            {"ADMIRAL_SHIP": "ship-1"},
            {"ADMIRAL_SHIP": "ship-1", "ADMIRAL_CREW_DIR": "", "ADMIRAL_RUN_CREW": ""},
        ):
            with self.subTest(env):
                proc, parsed = self.w.resolve(**env)
                self.assertEqual(proc.returncode, OK, proc.stderr)
                self.assertEqual(self.w.layers_of(parsed), {"implementer": "built-in", "triager": "repo"})

    def test_team_env_values_are_parsed_as_text(self):
        w = self.w
        w.put(w.builtin, "implementer", "implementer")
        variants = {
            "double quotes": ('REPO="{p}"', "with space"),
            "single quotes": ("REPO='{p}'", "single"),
            "unquoted with a trailing comment": ("REPO={p} # the repo", "commented"),
            "hash without a space stays": ("REPO={p}", "ha#sh"),
            "quoted value keeps ' #'": ('REPO="{p}"', "quoted #hash"),
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

    def test_worktree_stands_in_when_repo_is_missing_or_empty(self):
        w = self.w
        w.put(w.repo_crew, "triager", "triager")
        for label, text in {
            "REPO missing": f"WORKTREE={w.repo}\n",
            "REPO empty": f"REPO=\nWORKTREE={w.repo}\n",
            "REPO empty quoted": f'REPO=""\nWORKTREE={w.repo}\n',
        }.items():
            with self.subTest(label):
                w.team_env(text)
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

    def test_no_repo_and_no_layers_resolve_to_nothing(self):
        self.w.team_env("# nothing here\n")
        proc, parsed = self.w.resolve()
        self.assertEqual((proc.returncode, parsed), (OK, {"members": [], "warnings": []}), proc.stderr)

    def test_run_layer_member_overrides_repo_member_of_the_same_name(self):
        self.fill()
        self.w.put(self.w.repo_crew, "pinned", "scribe")
        self.w.put(self.w.run_crew, "pinned", "scribe")
        proc, parsed = self.w.resolve()
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(self.w.layers_of(parsed)["pinned"], "run")


# ---------------------------------------------------------------------------------------------------- built-in set
class BuiltInDirectory(unittest.TestCase):
    def test_built_in_directory_holds_exactly_one_member_per_role_named_after_it(self):
        self.assertTrue(BUILTIN_DIR.is_dir(), f"{BUILTIN_DIR.relative_to(REPO)} does not exist yet")
        self.assertEqual(sorted(p.name for p in BUILTIN_DIR.iterdir()), sorted(f"{r}.md" for r in ROLES))
        for role in ROLES:
            self.assertTrue((BUILTIN_DIR / f"{role}.md").is_file(), role)


class ShippedBuiltIns(ResolverCase):
    def test_built_in_set_resolves_cleanly_to_plain_defaults(self):
        proc, parsed = self.explicit({"built-in": BUILTIN_DIR})
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(parsed["warnings"], [])
        self.assertEqual([m["name"] for m in parsed["members"]], sorted(ROLES))
        for member in parsed["members"]:
            with self.subTest(member["name"]):
                self.assertEqual(member["role"], member["name"])
                self.assertEqual(member["layer"], "built-in")
                self.assertEqual(member["file"], f"{member['name']}.md")
                self.assertEqual(member["skills"], [])
                self.assertIsNone(member["model"])
                self.assertIsNone(member["harness"])
                self.assertIsNone(member["based-on"])
                self.assertFalse(member["ad-hoc"])
                self.assertTrue(member["pick-me-when"].strip())
                if member["role"] == "fix-checker":
                    self.assertEqual(member["instructions"], "")
                    self.assertIn("only", member["pick-me-when"].lower())
                else:
                    self.assertTrue(member["instructions"].strip())
                    self.assertLessEqual(len(member["instructions"]), MAX_BUILTIN_BODY)
                    self.assertIn("default", member["pick-me-when"].lower())

    def test_run_mode_finds_the_built_in_directory_next_to_the_script(self):
        w = World(self)
        shutil.rmtree(w.builtin)
        shutil.copytree(BUILTIN_DIR, w.builtin)
        w.team_env("REPO=\n")
        proc, parsed = w.resolve()
        self.assertEqual(proc.returncode, OK, proc.stderr)
        self.assertEqual(w.layers_of(parsed), {role: "built-in" for role in ROLES})
        self.assertEqual(parsed["warnings"], [])

    def test_resolver_is_an_executable_python3_stdlib_script(self):
        self.assertTrue(os.access(CREW_PY, os.X_OK), "crew.py is not executable")
        source = CREW_PY.read_text()
        self.assertTrue(source.startswith("#!"), "crew.py has no shebang")
        self.assertIn("python3", source.splitlines()[0])
        for third_party in ("import yaml", "from yaml", "ruamel"):
            self.assertNotIn(third_party, source)


if __name__ == "__main__":
    unittest.main()
