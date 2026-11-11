"""Tests for `crew.py note add`: which notes it writes to a member's memory, where, and which it refuses."""

import datetime
import json
import os
import shutil
import stat
import subprocess
import unittest
from pathlib import Path

from crew_world import WorldCase

OK, ERRORS, USAGE = 0, 1, 5
CAP = 30
MAX_BYTES = 65536
FACT = "Run the tests with `make test`."
OTHER = "The CI image has no network."
OLD = ("2026-11-01 (run-a): First fact.", "2026-11-02 (run-b): Second fact.", "2026-11-03 (run-c): Third fact.")


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def lines(*notes):
    return "".join(f"- {n}\n" for n in notes)


def numbered(count, what="Fact"):
    return [f"2026-11-01 (run-a): {what} {i:02d}." for i in range(1, count + 1)]


def snapshot(*roots):
    """Every file's bytes and every symlink's target under the roots, by path."""
    found = {}
    for root in roots:
        for here, dirs, files in os.walk(root):
            for name in dirs + files:
                path = Path(here) / name
                if path.is_symlink():
                    found[str(path)] = ("link", os.readlink(path))
                elif path.is_file():
                    found[str(path)] = ("file", path.read_bytes())
    return found


class WriteCase(WorldCase):
    """A temp world whose checkout's origin is https://github.com/acme/app.git."""

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.git("remote", "add", "origin", "https://github.com/acme/app.git")
        self.count = 0
        self.today = None

    def git(self, *args):
        env = self.w.env(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
        subprocess.run(["git", "-C", str(self.w.repo), *args], env=env, check=True, capture_output=True)

    def root(self):
        return self.w.xdg / "commodore" / "crew" / "memory"

    def put(self, rel, text):
        path = self.root() / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def path(self, scope="fleet", member="implementer"):
        return self.root() / member / ("fleet.md" if scope == "fleet" else "repos/acme/app.md")

    def read(self, scope="fleet"):
        return self.path(scope).read_text(encoding="utf-8")

    def stamp(self, note, run="run"):
        """The line a write made today."""
        return f"- {self.today} ({run}): {note}\n"

    def proposal(self, data, run=None):
        self.count += 1
        path = Path(run or self.w.run) / "prompts" / f"note-{self.count}.json"
        path.parent.mkdir(exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return path

    def run_add(self, *args, env=None, umask=None):
        before = utc_today()
        done = subprocess.run(
            [str(self.w.crew_py), "note", "add", *[str(a) for a in args]],
            env=env or self.w.env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            preexec_fn=(lambda: os.umask(umask)) if umask is not None else None,
        )
        if utc_today() != before:
            self.skipTest("the UTC date changed during the call")
        self.today = before
        return done

    def add(self, scope="fleet", note=FACT, replaces=None, member="implementer", run=None, env=None, umask=None):  # noqa: PLR0913, PLR0917
        run = run or self.w.run
        data = {"scope": scope, "note": note, "replaces": replaces}
        return self.run_add(
            "--run", run, "--member", member, "--proposal", self.proposal(data, run), env=env, umask=umask
        )

    def add_raw(self, raw):
        return self.run_add("--run", self.w.run, "--member", "implementer", "--proposal", self.proposal(raw))

    def memory(self):
        return snapshot(self.w.xdg, self.w.root / "elsewhere", self.w.repo, self.w.layer_dirs["fleet"])

    def assert_wrote(self, done, scope="fleet", member="implementer"):
        self.assertEqual(done.returncode, OK, done.stderr)
        self.assertEqual(done.stdout, f"wrote {self.path(scope, member)}\n")

    def assert_refused(self, done, before, code=ERRORS):
        self.assertEqual(done.returncode, code, done.stderr)
        self.assertEqual(done.stdout, "")
        if code == ERRORS:
            self.assertEqual([ln for ln in done.stderr.splitlines() if ln.startswith("ERROR")], [done.stderr.strip()])
        self.assertEqual(self.memory(), before)


class Writes(WriteCase):
    def test_a_fleet_note_is_appended_as_a_dated_line_to_the_members_fleet_file(self):
        done = self.add("fleet", FACT)
        self.assert_wrote(done)
        self.assertEqual(self.read(), f"- {self.today} (run): {FACT}\n")
        self.assertFalse(self.path("repo").exists())

    def test_a_repo_note_goes_to_the_file_of_the_checkouts_origin(self):
        done = self.add("repo", FACT)
        self.assert_wrote(done, "repo")
        self.assertEqual(self.path("repo"), self.root() / "implementer/repos/acme/app.md")
        self.assertEqual(self.read("repo"), self.stamp(FACT))

    def test_a_report_item_with_all_seven_keys_is_a_proposal(self):
        item = {"member": "x", "role": "y", "repo": None, "ad-hoc": True}
        self.assert_wrote(self.add_raw(json.dumps({**item, "scope": "fleet", "note": FACT, "replaces": None})))
        self.assertEqual(self.read(), self.stamp(FACT))

    def test_the_run_name_in_the_line_is_the_run_directorys_name(self):
        run = self.w.root / "my-run_1.2"
        run.mkdir()
        shutil.copy2(self.w.run / "team.env", run / "team.env")
        self.assert_wrote(self.add(run=run))
        self.assertEqual(self.read(), self.stamp(FACT, run="my-run_1.2"))

    def test_an_existing_file_keeps_every_line_and_the_note_goes_last(self):
        old = "# Notes\n\nSome prose.\n- not a note\n" + lines(OLD[0])
        self.put("implementer/fleet.md", old)
        self.assert_wrote(self.add())
        self.assertEqual(self.read(), old + self.stamp(FACT))

    def test_a_file_with_no_final_newline_gets_one_before_the_note(self):
        self.put("implementer/fleet.md", f"- {OLD[0]}")
        self.assert_wrote(self.add())
        self.assertEqual(self.read(), lines(OLD[0]) + self.stamp(FACT))

    def test_new_directories_are_0700_and_the_file_0600_under_a_022_umask(self):
        self.assert_wrote(self.add("repo", umask=0o022), "repo")
        made = [self.w.xdg / "commodore", self.w.xdg / "commodore/crew", self.root()]
        made += [self.root() / "implementer", self.root() / "implementer/repos", self.root() / "implementer/repos/acme"]
        for directory in made:
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700, directory)
        self.assertEqual(stat.S_IMODE(self.path("repo").stat().st_mode), 0o600)

    def test_a_note_is_300_characters_at_most_counted_in_characters(self):
        before = self.memory()
        self.assert_refused(self.add(note="é" * 301), before)
        self.assert_wrote(self.add(note="é" * 300))
        self.assertEqual(self.read(), self.stamp("é" * 300))

    def test_a_no_break_space_is_allowed(self):
        note = "A\u00a0fact."
        self.assert_wrote(self.add(note=note))
        self.assertEqual(self.read(), self.stamp(note))

    def test_a_symlink_above_commodore_is_followed(self):
        dotfiles = self.w.root / "dotfiles"
        dotfiles.mkdir()
        self.w.xdg.symlink_to(dotfiles)
        self.assert_wrote(self.add())
        self.assertEqual((dotfiles / "commodore/crew/memory/implementer/fleet.md").read_text(), self.stamp(FACT))

    def test_the_written_notes_load_in_the_resolver_without_warnings(self):
        self.add("fleet", FACT)
        self.add("repo", OTHER)
        done = self.w.sh([self.w.crew_py, "resolve", "--run", self.w.run])
        self.assertEqual(done.returncode, OK, done.stderr)
        parsed = json.loads(done.stdout)
        member = next(m for m in parsed["members"] if m["name"] == "implementer")
        want = {"fleet": [self.stamp(FACT)[2:-1]], "repo": [self.stamp(OTHER)[2:-1]]}
        self.assertEqual(member["notes"], want)
        self.assertEqual([w for w in parsed["warnings"] if w["layer"] == "memory"], [])

    def test_a_write_replaces_the_file_through_a_new_inode_and_leaves_no_temp_file(self):
        self.put("implementer/fleet.md", lines(*OLD))
        held = self.w.root / "held.md"
        os.link(self.path(), held)
        self.assert_wrote(self.add())
        self.assertEqual(held.read_text(), lines(*OLD))
        self.assertEqual(self.read(), lines(*OLD) + self.stamp(FACT))
        self.assertEqual(sorted(p.name for p in self.path().parent.iterdir()), ["fleet.md"])


class Cap(WriteCase):
    def test_a_scope_with_30_valid_notes_refuses_a_note_without_replaces(self):
        self.put("implementer/fleet.md", lines(*numbered(CAP)))
        before = self.memory()
        done = self.add()
        self.assert_refused(done, before)
        self.assertIn("replaces", done.stderr)

    def test_the_cap_counts_each_scope_on_its_own(self):
        self.put("implementer/fleet.md", lines(*numbered(CAP)))
        self.assert_wrote(self.add("repo"), "repo")

    def test_bad_lines_do_not_count_toward_the_cap(self):
        bad = "- bad line\n" + "- 2026-02-30 (run-a): An impossible date.\n"
        self.put("implementer/fleet.md", bad + lines(*numbered(CAP - 1)))
        self.assert_wrote(self.add())

    def test_replaces_works_at_the_cap(self):
        notes = numbered(CAP)
        self.put("implementer/fleet.md", lines(*notes))
        self.assert_wrote(self.add(replaces=notes[4]))
        self.assertEqual(self.read(), lines(*notes[:4]) + self.stamp(FACT) + lines(*notes[5:]))

    def test_a_write_that_would_leave_the_file_over_65536_bytes_is_refused(self):
        self.assert_wrote(self.add())
        pad = "x" * (MAX_BYTES - len(self.read().encode()) - 1)
        self.put("implementer/fleet.md", self.read() + pad + "\n")
        before = self.memory()
        self.assert_refused(self.add(note=OTHER), before)


class Replaces(WriteCase):
    def test_replaces_swaps_the_first_matching_line_in_place(self):
        text = "# Notes\n\n" + lines(OLD[0], OLD[1]) + "\n" + lines(OLD[2], OLD[1])
        self.put("implementer/fleet.md", text)
        self.assert_wrote(self.add(replaces=OLD[1]))
        self.assertEqual(self.read(), "# Notes\n\n" + lines(OLD[0]) + self.stamp(FACT) + "\n" + lines(OLD[2], OLD[1]))

    def test_a_replaces_that_matches_no_line_is_refused(self):
        self.put("implementer/fleet.md", lines(*OLD))
        before = self.memory()
        self.assert_refused(self.add(replaces="2026-11-09 (run-z): Not there."), before)

    def test_replaces_matches_only_a_valid_note_line(self):
        impossible = "2026-02-30 (run-a): An impossible date."
        self.put("implementer/fleet.md", lines(impossible, OLD[0]))
        before = self.memory()
        self.assert_refused(self.add(replaces=impossible), before)


class Refusals(WriteCase):
    def test_the_fix_checker_gets_no_note(self):
        before = self.memory()
        self.assert_refused(self.add(member="fix-checker"), before)
        self.assert_wrote(self.add(member="reviewer"), member="reviewer")

    def test_inside_admiral_it_is_a_bad_call(self):
        before = self.memory()
        self.assert_refused(self.add(env=self.w.admiral_env()), before, USAGE)

    def test_an_unknown_member_is_refused(self):
        before = self.memory()
        self.assert_refused(self.add(member="nobody"), before)

    def test_a_crew_that_does_not_resolve_is_refused(self):
        broken = self.w.layer_dirs["repo"]
        broken.mkdir(parents=True)
        (broken / "broken.md").write_text("not a member file\n")
        before = self.memory()
        self.assert_refused(self.add(), before)

    def test_a_run_directory_name_outside_letters_digits_dot_underscore_dash_is_refused(self):
        run = self.w.root / "odd run"
        run.mkdir()
        shutil.copy2(self.w.run / "team.env", run / "team.env")
        before = self.memory()
        self.assert_refused(self.add(run=run), before)

    def test_bad_note_text_is_refused(self):
        before = self.memory()
        for label, note in {"empty": "", "trailing space": "A fact. ", "line break": "A\nfact."}.items():
            with self.subTest(label):
                self.assert_refused(self.add(note=note), before)

    def test_a_hidden_character_is_refused_and_named_by_code_point(self):
        before = self.memory()
        done = self.add(note="A\u202efact.")
        self.assert_refused(done, before)
        self.assertIn("U+202E", done.stderr)
        self.assertNotIn("\u202e", done.stderr)

    def test_a_bad_proposal_file_is_refused(self):
        before = self.memory()
        good = '"scope":"fleet","note":"A fact."'
        cases = {
            "not json": "{",
            "not an object": "[]",
            "unknown key": "{" + good + ',"extra":1}',
            "duplicate key": "{" + good + ',"note":"B."}',
            "wrong type": '{"scope":"fleet","note":5}',
            "unknown scope": '{"scope":"global","note":"A fact."}',
            "no note": '{"scope":"fleet"}',
            "not utf-8": b'{"scope":"fleet","note":"caf\xe9"}',
        }
        for label, raw in cases.items():
            with self.subTest(label):
                self.assert_refused(self.add_raw(raw), before)

    def test_a_proposal_file_outside_the_runs_prompts_is_refused(self):
        outside = self.w.root / "proposal.json"
        outside.write_text(json.dumps({"scope": "fleet", "note": FACT}))
        before = self.memory()
        self.assert_refused(self.run_add("--run", self.w.run, "--member", "implementer", "--proposal", outside), before)

    def test_a_repo_note_needs_a_github_origin_but_a_fleet_note_does_not(self):
        self.git("remote", "set-url", "origin", "https://gitlab.com/acme/app.git")
        before = self.memory()
        self.assert_refused(self.add("repo"), before)
        self.assert_wrote(self.add("fleet"))

    def test_a_repo_note_in_a_run_with_no_repo_is_refused(self):
        self.w.team_env(repo=False)
        before = self.memory()
        self.assert_refused(self.add("repo"), before)

    def test_a_memory_root_inside_the_repo_is_refused(self):
        landing = self.w.repo / "dotfiles"
        landing.mkdir()
        self.w.xdg.symlink_to(landing)
        before = self.memory()
        self.assert_refused(self.add(), before)

    def test_bad_calls_exit_5(self):
        proposal = self.proposal({"scope": "fleet", "note": FACT})
        good = ["--run", self.w.run, "--member", "implementer", "--proposal", proposal]
        before = self.memory()
        calls = {
            "no --proposal": good[:4],
            "--member twice": [*good, "--member", "reviewer"],
            "unknown flag": [*good, "--bogus", "x"],
        }
        for label, args in calls.items():
            with self.subTest(label):
                self.assert_refused(self.run_add(*args), before, USAGE)
        with self.subTest("unknown subcommand"):
            done = self.w.sh([self.w.crew_py, "note", "remove", *good])
            self.assertEqual(done.returncode, USAGE, done.stderr)
            self.assertEqual(self.memory(), before)


class Symlinks(WriteCase):
    def move_aside(self, rel):
        """Move xdg/<rel> to elsewhere/<rel> and leave a symlink to it."""
        real = self.w.xdg / rel
        moved = self.w.root / "elsewhere" / rel
        moved.parent.mkdir(parents=True)
        shutil.move(real, moved)
        real.symlink_to(moved)

    def test_a_symlink_from_commodore_down_is_refused_and_never_followed(self):
        levels = {
            "crew": "commodore/crew",
            "the member directory": "commodore/crew/memory/implementer",
            "the note file": "commodore/crew/memory/implementer/fleet.md",
        }
        for label, rel in levels.items():
            with self.subTest(label):
                shutil.rmtree(self.w.xdg, ignore_errors=True)
                shutil.rmtree(self.w.root / "elsewhere", ignore_errors=True)
                self.put("implementer/fleet.md", lines(OLD[0]))
                self.move_aside(rel)
                before = self.memory()
                self.assert_refused(self.add(), before)
                self.assert_refused(self.add(replaces=OLD[0]), before)


if __name__ == "__main__":
    unittest.main()
