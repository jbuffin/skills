"""Tests for the startup-prompt WARNs the admiral driver's `preflight` adds for Codex and Copilot (u2 of #115,
decision 9): folder trust and hook trust are settled once per dock, and a launch waits forever at an unsettled prompt,
so preflight reads where each harness records them and WARNs. The WARNs never turn into FAILs.

Seams: drivers/admiral/preflight as a subprocess against a temp team dir. HOME is a temp dir, so
~/.admiral/config.json, ~/.codex/config.toml and ~/.copilot/config.json are the test's own; the fake `admiral` answers
`admiral ships` with the ship's fleet, and the fake `codex` and `copilot` are the only harness CLIs on PATH.
CODEX_HOME and COPILOT_HOME are unset unless a test passes them. The WARN wording is not fixed by the brief, so lines
are matched by the words that name the problem: a WARN naming trust for the folder, a WARN naming hook trust, and the
path the check read.

Run from the repo root: python3 -m unittest evals/agent-teammates/test_admiral_preflight_trust.py -v
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from admiral_world import ADMIRAL_DRIVER, SHIP, WorldCase

OK = 0

RULES = (
    'prefix_rule(pattern=["git", "add"], decision="allow")\nprefix_rule(pattern=["git", "commit"], decision="allow")\n'
)
HOOK_STATE = '[hooks.state."/dock/hooks.json:pre_tool_use:0:0"]\ntrusted_hash = "sha256:abc"\n'


def warns(out):
    return [line for line in out.splitlines() if line.startswith("WARN")]


def trust_warns(out):
    """WARNs about folder trust: they name trust and not hooks."""
    return [w for w in warns(out) if re.search(r"(?i)trust", w) and not re.search(r"(?i)hook", w)]


def hook_warns(out):
    return [w for w in warns(out) if re.search(r"(?i)hook", w) and re.search(r"(?i)trust", w)]


def config_toml(*trusted, hooks=True, level="trusted"):
    text = "".join(f'[projects."{p}"]\ntrust_level = "{level}"\n\n' for p in trusted)
    return text + (HOOK_STATE if hooks else "")


class PreflightCase(WorldCase):
    harness = None

    def setUp(self):
        super().setUp()
        self.w.write_team_env(harness=self.harness)

    def preflight(self, **kw):
        return self.w.run(ADMIRAL_DRIVER / "preflight", self.w.team, **kw)

    def assertWarnsThenSettles(self, settle, **kw):
        """Nothing settled warns once about folder trust; after `settle()` it doesn't. The first half keeps a test that
        only expects silence from passing before the check exists."""
        before = self.preflight(**kw)
        self.assertEqual(len(trust_warns(before.out)), 1, before.out)
        settle()
        after = self.preflight(**kw)
        self.assertEqual(after.code, OK, after.text)
        self.assertEqual(trust_warns(after.out), [], after.out)
        return after

    def git_checkout(self):
        """A main checkout with a linked worktree; returns (main, worktree)."""
        main, tree = self.w.root / "main-checkout", self.w.root / "linked-tree"
        main.mkdir()
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(main)]
        for cmd in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"], ["worktree", "add", "-q", str(tree)]):
            subprocess.run([*git, *cmd], check=True, capture_output=True)
        return main, tree


class TestCodexTrustWarns(PreflightCase):
    harness = "codex"

    def setUp(self):
        super().setUp()
        rules = self.w.home / ".codex" / "rules"
        rules.mkdir(parents=True)
        (rules / "default.rules").write_text(RULES)
        self.dock = self.w.root / "dock-codex"
        self.dock.mkdir()
        self.dock_config({"work": self.dock})

    def dock_config(self, homes):
        fleets = {name: {"codex": {"env": {"CODEX_HOME": str(home)}}} for name, home in homes.items()}
        path = self.w.home / ".admiral" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fleets": fleets}))

    def settled(self, *trusted, **kw):
        (self.dock / "config.toml").write_text(config_toml(*trusted, **kw))

    # the repo root
    def test_a_trusted_repo_root_and_hook_state_raise_no_warn(self):
        before = self.preflight()
        self.assertEqual(len(hook_warns(before.out)), 1, before.out)
        done = self.assertWarnsThenSettles(lambda: self.settled(self.w.checkout))
        self.assertEqual(hook_warns(done.out), [])

    def test_a_trusted_ancestor_of_the_repo_root_counts(self):
        self.assertWarnsThenSettles(lambda: self.settled(self.w.root))

    def test_an_untrusted_or_unrelated_project_warns(self):
        for trusted, level in ((self.w.work, "trusted"), (self.w.checkout, "untrusted")):
            with self.subTest(trusted=str(trusted), level=level):
                self.settled(trusted, level=level)
                done = self.preflight()
                self.assertEqual(done.code, OK, done.text)
                self.assertEqual(len(trust_warns(done.out)), 1, done.out)
                self.assertNotRegex(done.out, r"(?m)^FAIL .*trust")

    def test_a_child_of_the_repo_root_is_not_enough(self):
        self.settled(self.w.checkout / "sub")
        self.assertEqual(len(trust_warns(self.preflight().out)), 1)

    def test_a_missing_config_toml_warns_for_the_folder_and_for_hooks(self):
        done = self.preflight()
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(len(trust_warns(done.out)), 1, done.out)
        self.assertEqual(len(hook_warns(done.out)), 1, done.out)

    def test_no_hook_state_tables_warn_only_about_hooks(self):
        self.settled(self.w.checkout, hooks=False)
        done = self.preflight()
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(trust_warns(done.out), [])
        self.assertEqual(len(hook_warns(done.out)), 1, done.out)

    def test_the_warns_are_not_fails(self):
        done = self.preflight()
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(len(trust_warns(done.out)) + len(hook_warns(done.out)), 2, done.out)
        self.assertNotRegex(done.out, r"(?m)^FAIL")

    # the dock's CODEX_HOME
    def test_the_dock_home_is_read_and_named(self):
        done = self.preflight()
        self.assertIn(str(self.dock), "\n".join(trust_warns(done.out) + hook_warns(done.out)))

    def test_the_ships_fleet_picks_the_dock(self):
        other = self.w.root / "other-dock"
        other.mkdir()
        (other / "config.toml").write_text(config_toml(self.w.checkout))
        self.settled()  # the ship's own dock trusts nothing
        self.dock_config({"work": self.dock, "play": other})
        self.w.ctl_write(
            "ships.txt",
            f"{SHIP}\tadmiral-{SHIP}\twork\tcodex\tunderway\tskills\nother\tadmiral-other\tplay\tcodex\tunderway\tx\n",
        )
        done = self.preflight()
        self.assertEqual(len(trust_warns(done.out)), 1, done.out)
        self.assertIn(str(self.dock), done.out)
        self.w.ctl_write(
            "ships.txt",
            f"other\tadmiral-other\tplay\tcodex\tunderway\tx\n{SHIP}\tadmiral-{SHIP}\twork\tcodex\tunderway\tskills\n",
        )
        self.assertEqual(len(trust_warns(self.preflight().out)), 1)

    def test_the_session_name_finds_the_fleet_as_well_as_the_display_name(self):
        self.w.ctl_write("ships.txt", f"Heather Hull\t{SHIP}\twork\tcodex\tunderway\tskills\n")
        self.assertWarnsThenSettles(lambda: self.settled(self.w.checkout))

    def test_without_a_dock_entry_it_falls_back_to_the_coordinators_codex_home(self):
        self.dock_config({})
        coordinator = self.w.root / "coordinator-codex"
        (coordinator / "rules").mkdir(parents=True)
        (coordinator / "rules" / "default.rules").write_text(RULES)
        (coordinator / "config.toml").write_text(config_toml(self.w.checkout))
        (coordinator / "config.toml").write_text("")
        before = self.preflight(CODEX_HOME=str(coordinator))
        self.assertEqual(len(trust_warns(before.out)), 1, before.out)
        self.assertIn(str(coordinator), "\n".join(trust_warns(before.out)))
        (coordinator / "config.toml").write_text(config_toml(self.w.checkout))
        done = self.preflight(CODEX_HOME=str(coordinator))
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(trust_warns(done.out), [])
        self.assertEqual(hook_warns(done.out), [])
        self.assertIn(str(coordinator), done.out)

    def test_without_either_it_falls_back_to_the_dot_codex_dir_and_says_so(self):
        self.dock_config({})
        done = self.preflight()
        self.assertEqual(len(trust_warns(done.out)), 1, done.out)
        self.assertIn(str(self.w.home / ".codex"), "\n".join(trust_warns(done.out) + hook_warns(done.out)))
        (self.w.home / ".codex" / "config.toml").write_text(config_toml(self.w.checkout))
        self.assertEqual(trust_warns(self.preflight().out), [])

    def test_a_tilde_in_the_dock_home_is_expanded(self):
        settled = self.w.home / "dock-tilde"
        settled.mkdir()
        (settled / "config.toml").write_text(config_toml(self.w.checkout))
        self.dock_config({"work": "~/dock-tilde"})
        (self.w.home / ".admiral" / "config.json").write_text(
            json.dumps({"fleets": {"work": {"codex": {"env": {"CODEX_HOME": "~/dock-tilde"}}}}})
        )
        done = self.preflight()
        self.assertEqual((trust_warns(done.out), hook_warns(done.out)), ([], []), done.out)

    def test_a_missing_admiral_config_json_falls_back(self):
        (self.w.home / ".admiral" / "config.json").unlink()
        done = self.preflight()
        self.assertEqual(done.code, OK, done.text)
        self.assertEqual(len(trust_warns(done.out)), 1, done.out)

    # the repo root when REPO is unset
    def test_repo_unset_uses_the_main_checkout_of_the_current_repository(self):
        main, tree = self.git_checkout()
        self.w.write_team_env(harness="codex", repo=False)
        self.assertWarnsThenSettles(lambda: self.settled(main), cwd=tree)

    def test_repo_unset_does_not_trust_the_linked_worktree_alone(self):
        _, tree = self.git_checkout()
        self.w.write_team_env(harness="codex", repo=False)
        self.settled(tree)
        self.assertEqual(len(trust_warns(self.preflight(cwd=tree).out)), 1)

    def test_repo_unset_outside_a_repository_says_the_check_was_skipped(self):
        self.w.write_team_env(harness="codex", repo=False)
        elsewhere = self.w.root / "not-a-repo"
        elsewhere.mkdir()
        self.settled(self.w.checkout)
        done = self.preflight(cwd=elsewhere)
        self.assertEqual(done.code, OK, done.text)
        skipped = [w for w in warns(done.out) if re.search(r"(?i)skipped", w)]
        self.assertEqual(len(skipped), 1, done.out)

    def test_repo_wins_over_the_current_repository(self):
        main, tree = self.git_checkout()
        self.settled(main)  # trusts the cwd's repository, but team.env's REPO is elsewhere
        done = self.preflight(cwd=tree)
        self.assertEqual(len(trust_warns(done.out)), 1, done.out)

    # when codex is not installed
    def test_no_codex_means_no_trust_warns(self):
        before = self.preflight()
        self.assertEqual(len(trust_warns(before.out)), 1, before.out)
        (self.w.bin / "codex").unlink()
        done = self.preflight()
        self.assertEqual(trust_warns(done.out), [])
        self.assertEqual(hook_warns(done.out), [])
        self.assertRegex(done.out, r"(?m)^FAIL .*codex")


class TestCopilotTrustWarns(PreflightCase):
    harness = "copilot"
    HEADER = "// User settings belong in settings.json.\n// This file is managed automatically.\n"

    def setUp(self):
        super().setUp()
        self.config = self.w.home / ".copilot" / "config.json"
        self.config.parent.mkdir(parents=True)

    def settled(self, *folders, header=None):
        self.config.write_text(
            (self.HEADER if header is None else header) + json.dumps({"trustedFolders": list(map(str, folders))})
        )

    def test_a_trusted_repo_root_raises_no_warn(self):
        self.assertWarnsThenSettles(lambda: self.settled(self.w.checkout))

    def test_a_trusted_ancestor_counts(self):
        self.assertWarnsThenSettles(lambda: self.settled(self.w.root))

    def test_the_leading_comment_lines_are_dropped_before_parsing(self):
        self.assertWarnsThenSettles(lambda: self.settled(self.w.checkout, header="// one\n// two\n// three\n"))

    def test_no_entry_for_the_repo_warns_and_names_the_file(self):
        self.settled(self.w.work, self.w.checkout / "sub")
        done = self.preflight()
        self.assertEqual(len(trust_warns(done.out)), 1, done.out)
        self.assertIn(str(self.config), "\n".join(trust_warns(done.out)))
        self.assertNotRegex(done.out, r"(?m)^FAIL .*trust")

    def test_a_missing_file_warns(self):
        self.config.unlink() if self.config.exists() else None
        done = self.preflight()
        self.assertEqual(len(trust_warns(done.out)), 1, done.out)

    def test_an_unreadable_file_warns(self):
        self.config.write_text(self.HEADER + "{ this is not json")
        self.assertEqual(len(trust_warns(self.preflight().out)), 1)

    def test_no_trusted_folders_key_warns(self):
        self.config.write_text(self.HEADER + "{}")
        self.assertEqual(len(trust_warns(self.preflight().out)), 1)

    def test_copilot_home_replaces_the_default_dir(self):
        custom = self.w.root / "copilot-home"
        custom.mkdir()
        self.settled(self.w.checkout)  # the default dir trusts it, the custom one doesn't
        (custom / "config.json").write_text(self.HEADER + json.dumps({"trustedFolders": []}))
        before = self.preflight(COPILOT_HOME=str(custom))
        self.assertEqual(len(trust_warns(before.out)), 1, before.out)
        (custom / "config.json").write_text(self.HEADER + json.dumps({"trustedFolders": [str(self.w.checkout)]}))
        self.assertEqual(trust_warns(self.preflight(COPILOT_HOME=str(custom)).out), [])

    def test_repo_unset_uses_the_main_checkout_of_the_current_repository(self):
        main, tree = self.git_checkout()
        self.w.write_team_env(harness="copilot", repo=False)
        self.assertWarnsThenSettles(lambda: self.settled(main), cwd=tree)

    def test_repo_unset_outside_a_repository_says_the_check_was_skipped(self):
        self.w.write_team_env(harness="copilot", repo=False)
        elsewhere = self.w.root / "not-a-repo"
        elsewhere.mkdir()
        self.settled(self.w.checkout)
        done = self.preflight(cwd=elsewhere)
        self.assertEqual(len([w for w in warns(done.out) if re.search(r"(?i)skipped", w)]), 1, done.out)

    def test_an_unreadable_file_still_warns_when_the_repo_root_is_unknown(self):
        self.w.write_team_env(harness="copilot", repo=False)
        elsewhere = self.w.root / "not-a-repo"
        elsewhere.mkdir()
        self.config.write_text(self.HEADER + "{ this is not json")
        done = self.preflight(cwd=elsewhere)
        self.assertEqual(len([w for w in warns(done.out) if str(self.config) in w]), 1, done.out)
        self.assertEqual(len([w for w in warns(done.out) if re.search(r"(?i)skipped", w)]), 1, done.out)

    def test_copilot_has_no_hook_trust_warn(self):
        done = self.assertWarnsThenSettles(lambda: self.settled(self.w.checkout))
        self.assertEqual(hook_warns(done.out), [])


if __name__ == "__main__":
    unittest.main()
