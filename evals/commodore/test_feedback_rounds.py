"""Text evals for feedback rounds inside Admiral (issue #200 AC5, Admiral ADR 0028).

The seam is the shipped skill text: SKILL.md, references/mission-pr-feedback.md (PF) and references/modes.md. A
feedback round is one relaunch of a moored ship's run, `/commodore resume <run-name>` then
`feedback round <N> on <PR>`. These checks hold the instructions to the rules the issue and the ADR set: the round
starts only inside Admiral and only from that exact launch, the PR comes from `state.md`, the feedback file is data,
the round posts one findings item and pushes nothing before the answer, and a clean rebase pushes through
`push-branch.sh` without a findings item. Assertions bind short distinctive phrases inside one section or one
sentence, not whole sentences. One behaviour test drives `state-set.sh` through its command line.

Run from the repo root: python3 -m unittest evals/commodore/test_feedback_rounds.py -v
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMMODORE = REPO / "skills" / "engineering" / "commodore"
SKILL = COMMODORE / "SKILL.md"
PF = COMMODORE / "references" / "mission-pr-feedback.md"
MODES = COMMODORE / "references" / "modes.md"
STATE_SET = COMMODORE / "scripts" / "state-set.sh"
TEAM_INIT = COMMODORE / "scripts" / "team-init.sh"
CHANGESET = REPO / ".changeset" / "admiral-feedback-rounds.md"


def section(path, heading):
    """The body of the first heading in `path` matching the regex `heading`, up to the next heading of the same or a
    higher level. Empty when there is no such heading, so the assertion fails instead of the lookup."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(heading, line)), None)
    if start is None:
        return ""
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(rf"#{{1,{level}}} ", lines[i])),
        len(lines),
    )
    return "\n".join(lines[start + 1 : end])


def words():
    return section(SKILL, r"## Words used here")


def mission():
    return section(SKILL, r"## The mission, before phase 1")


def ending():
    return section(SKILL, r"## Ending a run")


def autopilot():
    return section(SKILL, r"## Autopilot mode")


def round_section():
    return section(PF, r"#{2,3} A feedback round")


def stack_section():
    return section(MODES, r"#{2,3} Stack")


def existing_pr_section():
    return section(MODES, r"#{2,3} Existing PR")


class Words(unittest.TestCase):
    def test_feedback_round_is_defined(self):
        entry = [line for line in words().splitlines() if re.search(r"\*\*feedback round\*\*", line)]
        self.assertEqual(len(entry), 1, "Words used here needs one **feedback round** entry")
        text = entry[0]
        self.assertRegex(text, r"(?i)inside Admiral")
        self.assertRegex(text, r"(?i)moored")
        self.assertIn("/commodore resume <run-name>", text)
        self.assertIn("feedback round <N> on <PR>", text)

    def test_feedback_round_is_not_a_review_round(self):
        entry = [line for line in words().splitlines() if re.search(r"\*\*feedback round\*\*", line)]
        self.assertEqual(len(entry), 1)
        self.assertRegex(entry[0], r"(?i)not a review round")


class RoundStart(unittest.TestCase):
    def test_exact_launch_starts_a_round_inside_admiral(self):
        text = mission()
        self.assertRegex(text, r"(?i)feedback round <N> on <PR>")
        self.assertRegex(text, r"(?i)inside Admiral[^\n]*feedback round|feedback round[^\n]*inside Admiral")
        self.assertIn("ADMIRAL_SHIP", text)
        self.assertRegex(text, r"(?i)nothing (else )?after `?<PR>`?")

    def test_a_round_starts_even_when_the_run_is_finished_or_partial(self):
        text = mission()
        self.assertRegex(
            text, r"(?i)feedback round[^\n]*(finished|`result:`)[^\n]*|(finished|`result:`)[^\n]*feedback round"
        )
        self.assertRegex(text, r"(?i)feedback round[^\n]*partial|partial[^\n]*feedback round")

    def test_other_resumes_of_a_finished_run_still_stop(self):
        text = mission() + "\n" + ending()
        self.assertRegex(text, r"(?i)(every )?other (resume|launch)[^\n]*finished[^\n]*(stop|says it's finished)")
        self.assertRegex(ending(), r"(?i)finished and stops")

    def test_outside_admiral_nothing_changes(self):
        self.assertRegex(mission(), r"(?i)outside Admiral[^\n]*starts nothing[^\n]*finished")

    def test_hand_wake_with_free_text_is_a_follow_up(self):
        text = mission() + "\n" + ending()
        self.assertRegex(text, r"(?i)(free text|hand wake)[^\n]*follow-up|follow-up[^\n]*(free text|hand wake)")

    def test_round_number_is_checked(self):
        self.assertIn("^[1-9][0-9]*$", mission())

    def test_pr_must_match_a_units_row_and_its_recorded_url_is_used(self):
        text = mission()
        self.assertRegex(text, r"(?i)units table")
        self.assertRegex(text, r"`state\.md`[^\n]*(units|\bPR\b)|(units|\bPR\b)[^\n]*`state\.md`")
        self.assertRegex(text, r"(?i)(feedback|launch)[^\n]*\bPR\b[^\n]*units table|units table[^\n]*\bPR\b")
        self.assertRegex(text, r"(?i)recorded (PR )?URL")
        self.assertRegex(text, r"(?i)never the launch text")
        self.assertIn("^[0-9]+$", text)

    def test_failed_check_is_a_high_stakes_stop_with_one_question_item(self):
        text = mission()
        self.assertRegex(
            text, r"(?i)(failed|fails|failing) check[^\n]*high-stakes|high-stakes[^\n]*(failed|fails|failing) check"
        )
        self.assertRegex(text, r"(?i)one question item")

    def test_round_is_recorded_in_state(self):
        text = mission()
        self.assertIn("feedback round=<N>", text)
        self.assertIn("feedback pr=<url>", text)
        self.assertIn("feedback status=open", text)
        self.assertIn("state-set.sh", text)

    def test_open_feedback_status_means_the_run_is_unfinished(self):
        text = mission()
        self.assertRegex(
            text,
            r"(?i)feedback status[^\n]*open[^\n]*(unfinished|isn't finished|not finished)"
            r"|(unfinished|isn't finished|not finished)[^\n]*feedback status[^\n]*open",
        )
        self.assertRegex(text, r"(?i)whatever its `result:` line says|regardless of[^\n]*`result:`")

    def test_same_round_number_never_starts_twice(self):
        text = mission()
        self.assertRegex(text, r"(?i)same `?<N>`?")
        self.assertRegex(text, r"(?i)never starts it twice|not start it twice|never start[^\n]*twice")

    def test_round_end_closes_status_and_sets_result_in_one_call(self):
        text = mission() + "\n" + ending()
        self.assertIn("feedback status=closed", text)
        self.assertRegex(
            text, r"(?i)feedback status=closed[^\n]*(result|one call)|(result|one call)[^\n]*feedback status=closed"
        )

    def test_open_round_follows_pf_whatever_the_mission_line_says(self):
        text = mission()
        self.assertRegex(
            text,
            r"(?i)feedback status[^\n]*(mission-pr-feedback|\bPF\b)|(mission-pr-feedback|\bPF\b)[^\n]*feedback status",
        )
        self.assertRegex(text, r"(?i)whatever its `mission:` line says|regardless of[^\n]*`mission:`")
        self.assertRegex(text, r"(?i)`mission:` line stays")

    def test_autopilot_resume_goes_back_into_the_round(self):
        text = autopilot()
        resume = text[text.find("**Resume.**") :] if "**Resume.**" in text else ""
        self.assertRegex(resume, r"(?i)feedback round")


class FeedbackRoundSection(unittest.TestCase):
    def test_the_section_exists(self):
        self.assertTrue(round_section().strip(), "PF needs a section headed 'A feedback round'")

    def test_per_round_paths(self):
        text = round_section()
        self.assertIn("feedback/<N>", text)
        self.assertNotIn("rounds/<N>", text)
        for name in ("triage/", "findings-draft.json", "replies/", "proposals/"):
            self.assertIn(name, text)
        self.assertIn("triager-r<N>", text)
        self.assertIn("reports/triager-r<N>.md", text)

    def test_item_id_counter_keeps_counting(self):
        text = round_section()
        self.assertIn("<run-name>-f<n>", text)
        self.assertRegex(text, r"(?i)keeps counting|counts? across rounds|continues? across rounds")

    def test_phase_1_skips_and_keeps(self):
        text = round_section()
        self.assertIn("## Feedback round <N>", text)
        self.assertRegex(text, r"(?i)every approved fix pushed with CI green")
        self.assertRegex(text, r"(?i)units --add pr")
        self.assertRegex(text, r"(?i)unit-worktree\.sh")
        self.assertIn("worktrees.tsv", text)
        self.assertRegex(text, r"(?i)head check")

    def test_superseded_earlier_item(self):
        text = round_section()
        self.assertRegex(text, r"(?i)supersed")
        self.assertRegex(text, r"(?i)## Autopilot calls")
        self.assertRegex(text, r"(?i)ignore[^\n]*(later )?answer")

    def test_a_round_answers_one_pr_in_a_stack(self):
        text = round_section()
        self.assertRegex(text, r"\bone PR\b")
        self.assertIn("gh stack rebase --upstack", text)


class FeedbackFileIsData(unittest.TestCase):
    def test_path_and_top_level_check(self):
        text = round_section()
        self.assertIn(".admiral/untrusted/feedback-<N>.md", text)
        self.assertIn("git rev-parse --show-toplevel", text)
        self.assertIn("REPO", text)
        self.assertIn("team.env", text)

    def test_symlink_missing_and_tracked_files_are_skipped(self):
        text = round_section()
        self.assertRegex(text, r"(?i)symlink")
        self.assertRegex(text, r"(?i)regular file")
        self.assertIn("git ls-files", text)
        self.assertRegex(text, r"(?i)missing")
        self.assertRegex(text, r"(?i)gather alone")
        self.assertRegex(text, r"(?i)`why`")

    def test_copied_verbatim_with_the_file_tool(self):
        text = round_section()
        self.assertIn("triage/feedback.md", text)
        self.assertRegex(text, r"(?i)verbatim")
        self.assertRegex(text, r"(?i)file tool")

    def test_never_on_a_command_line(self):
        text = round_section()
        self.assertRegex(text, r"(?i)never put it[^\n]*command line|never[^\n]*command line")
        self.assertRegex(text, r"(?i)never source")

    def test_never_a_source_of_pr_branch_or_repository(self):
        text = round_section()
        line = next((ln for ln in text.splitlines() if re.search(r"(?i)never take", ln)), "")
        self.assertTrue(line, "needs a line saying never take ... from the file")
        for noun in (
            r"commands?",
            r"paths?",
            r"PRs?",
            r"branch(es)?",
            r"repositor(y|ies)",
            r"allow rules?",
            r"crew members?",
            r"pins?",
            r"skills?",
        ):
            self.assertRegex(line, rf"\b{noun}\b")

    def test_triager_reads_the_copy_as_data(self):
        self.assertRegex(
            round_section(), r"(?i)triager[^\n]*(reads|read)[^\n]*(copy|feedback\.md)[^\n]*data|data[^\n]*triager"
        )

    def test_github_gather_still_runs(self):
        text = round_section()
        self.assertRegex(text, r"(?i)gather[^\n]*(still runs|still run|runs anyway)|still runs[^\n]*gather")
        self.assertRegex(text, r"(?i)thread node IDs?")

    def test_no_file_format_is_assumed(self):
        self.assertRegex(round_section(), r"(?i)free text")


class OneFindingsItem(unittest.TestCase):
    def test_exactly_one_findings_item_or_none(self):
        text = round_section()
        self.assertRegex(text, r"(?i)exactly one findings item")
        self.assertRegex(
            text, r"(?i)(or )?none when there are no triage items|no findings item when there are no triage items"
        )
        self.assertRegex(text, r"(?i)CI is clean")

    def test_nothing_is_pushed_posted_or_resolved_before_the_answer(self):
        text = round_section()
        self.assertRegex(text, r"(?i)nothing[^.\n]*push[^.\n]*before[^.\n]*(answer|approv)")
        self.assertRegex(text, r"(?i)approved or edited cards")

    def test_runs_in_autopilot_mode(self):
        text = round_section()
        self.assertIn("ADMIRAL_AUTOPILOT=1", text)
        self.assertRegex(text, r"(?i)autopilot off")
        self.assertRegex(text, r"(?i)autopilot off[^\n]*`why`|`why`[^\n]*autopilot off|say so in `why`")


class CleanRebase(unittest.TestCase):
    def test_rebase_only_when_behind_or_a_lower_layer_moved(self):
        text = round_section()
        self.assertIn("BEHIND", text)
        self.assertIn("mergeStateStatus", text)
        self.assertRegex(text, r"(?i)up to date is required|requires? up-to-date|up-to-date")
        self.assertRegex(text, r"(?i)lower layer mov")

    def test_catch_up_to_head_ref_oid_before_rebasing(self):
        text = round_section()
        self.assertIn("headRefOid", text)
        self.assertRegex(text, r"(?i)fast-forward")
        self.assertRegex(text, r"(?i)origin/<branch>")
        self.assertRegex(text, r"(?i)(isn't|not) a fast-forward[^\n]*(stop|question item)")
        self.assertRegex(text, r"(?i)push nothing")

    def test_pushes_through_push_branch_never_gh_stack_push(self):
        text = round_section()
        self.assertIn("push-branch.sh", text)
        self.assertRegex(text, r"(?i)never `?gh stack push`?")
        self.assertRegex(text, r"(?i)bare force push")
        self.assertIn("watch-ci.sh", text)

    def test_rebase_commands(self):
        text = round_section()
        self.assertIn("gh stack rebase", text)
        self.assertIn("git rebase origin/<base>", text)

    def test_clean_rebase_needs_no_findings_item_and_is_recorded(self):
        text = round_section()
        self.assertRegex(text, r"(?i)no findings item")
        self.assertIn("## Decisions and assumptions", text)
        self.assertRegex(text, r"(?i)report[^\n]*`why`|`why`[^\n]*report")

    def test_conflict_is_aborted_and_becomes_a_triage_item(self):
        text = round_section()
        self.assertIn("git rebase --abort", text)
        self.assertIn("gh stack rebase --abort", text)
        self.assertIn("DIRTY", text)
        self.assertRegex(text, r"(?i)triage item")
        self.assertRegex(text, r"(?i)conflict[^\n]*CI fixes[^\n]*findings item|findings item[^\n]*conflict")

    def test_modes_stack_and_existing_pr_point_at_the_section(self):
        for body in (stack_section(), existing_pr_section()):
            self.assertRegex(body, r"(?i)feedback round")
            self.assertRegex(body, r"mission-pr-feedback\.md#a-feedback-round")


class Report(unittest.TestCase):
    def test_every_round_ends_with_a_fresh_report(self):
        text = round_section()
        self.assertRegex(text, r"(?i)ending a run")
        self.assertRegex(text, r"(?i)`prs`[^\n]*`closes`|`closes`[^\n]*`prs`")
        self.assertIn("`resume`", text)
        self.assertRegex(text, r"(?i)feedback round <N> on <PR>")
        self.assertRegex(text, r"(?i)feedback file[^\n]*skip|skip[^\n]*feedback file")
        self.assertRegex(text, r"(?i)`inbox`")


class RoundLifecycle(unittest.TestCase):
    """Review round 1: what happens to a round across a stop, a resume and the next round."""

    def test_a_stop_waiting_on_an_answer_leaves_the_round_open(self):
        text = ending()
        self.assertRegex(
            text,
            r"(?i)feedback round[^\n]*(findings item|question item|high-stakes stop)"
            r"[^\n]*leaves `feedback status` `open`",
        )
        self.assertRegex(text, r"(?i)only when nothing is waiting on an answer")
        self.assertIn("feedback status=closed", text)

    def test_the_high_stakes_stop_keeps_the_round_open(self):
        text = autopilot()
        step4 = text[text.find("4. Write `result: partial`") :].split("\n", 1)[0]
        self.assertRegex(step4, r"(?i)feedback round[^\n]*`feedback status` `open`")

    def test_resume_reads_the_answer_and_never_restarts_the_round(self):
        text = autopilot()
        resume = text[text.find("**Resume.**") :]
        self.assertRegex(resume, r"(?i)steps 1\D5")
        self.assertRegex(resume, r"(?i)after a findings item[^\n]*Resuming after a findings item")
        self.assertRegex(resume, r"(?i)never run the round's phase 1 gather again")
        self.assertIn("feedback/<N>/", resume)

    def test_one_open_round_at_a_time(self):
        text = mission()
        self.assertRegex(text, r"(?i)one open round at a time")
        self.assertRegex(text, r"(?i)another PR[^\n]*(don't|do not) start round `?<N>`?")
        self.assertRegex(text, r"(?i)next relaunch")
        self.assertRegex(round_section(), r"(?i)supersede[^\n]*only[^\n]*same PR|same PR[^\n]*supersede")

    def test_a_round_never_ends_the_run_better_than_it_found_it(self):
        text = mission() + "\n" + ending()
        self.assertRegex(text, r"(?i)never ends the run better than it found it")
        self.assertRegex(text, r"(?i)open items[^\n]*`## Autopilot calls`[^\n]*`## Inbox questions`")
        self.assertRegex(text, r"(?i)result=partial[^\n]*`?inbox`?")

    def test_launch_text_forms(self):
        text = mission()
        self.assertIn("$commodore resume <run-name>", text)
        self.assertRegex(text, r"(?i)outside Admiral[^\n]*starts nothing")
        self.assertRegex(text, r"(?i)`feedback status` is already `open`[^\n]*(still )?resumes")

    def test_failed_check_options_and_used_round_numbers(self):
        text = mission()
        self.assertRegex(text, r"(?i)`Stop` \(recommended\)")
        self.assertRegex(text, r"(?i)keeps? (a finished run's|its) old `result:` line")
        self.assertRegex(text, r"(?i)counts as used when `<run>/feedback/<N>/` exists")

    def test_an_ambiguous_bare_number_fails_the_check(self):
        self.assertRegex(mission(), r"(?i)more than one[^\n]*(row|URL)[^\n]*(check )?fails")


class RoundIsolation(unittest.TestCase):
    def test_unit_names_and_item_ids_are_per_round(self):
        text = round_section()
        self.assertIn("r<N>-u<k>", text)
        self.assertIn("review-round.sh", text)
        self.assertIn("r<N>-t1", text)
        self.assertIn("r<N>-ci1", text)

    def test_briefs_never_overwrite_the_runs_common_brief(self):
        text = round_section()
        self.assertIn("feedback/<N>/brief-common.md", text)
        self.assertIn("prompts/triager-r<N>.md", text)
        self.assertRegex(text, r"(?i)never over `?<run>/brief-common\.md`?")

    def test_launch_is_in_the_prs_own_unit(self):
        self.assertRegex(round_section(), r"(?i)launch[^\n]*(triager|fix units)[^\n]*PR's own unit[^\n]*never `u1`")

    def test_a_round_triages_only_what_is_new(self):
        text = round_section()
        self.assertRegex(text, r"(?i)newest comment is a reply this run recorded")
        self.assertRegex(text, r"(?i)gather time[^\n]*per round|per round[^\n]*gather time")
        self.assertRegex(text, r"(?i)name the dropped ones in the final report")

    def test_order_inside_a_round(self):
        self.assertRegex(
            round_section(),
            r"(?i)fast-forward the reused worktree[^\n]*head check[^\n]*clean rebase[^\n]*CI wait[^\n]*gather",
        )

    def test_triager_brief_and_cards(self):
        text = round_section()
        self.assertRegex(text, r"(?i)triager's brief points at[^\n]*triage/feedback\.md[^\n]*context")
        self.assertRegex(text, r"(?i)cards cover only `items\.md` ids")

    def test_with_autopilot_off_the_batch_is_one_question_item(self):
        self.assertRegex(round_section(), r"(?i)with autopilot off[^\n]*step 11[^\n]*one question item")

    def test_feedback_directories_must_be_real(self):
        text = round_section()
        self.assertRegex(text, r"(?i)neither `<top>/\.admiral` nor `<top>/\.admiral/untrusted` is a symlink")
        self.assertRegex(text, r"(?i)`git ls-files`[^\n]*(error|fails)[^\n]*tracked")


class PushSafety(unittest.TestCase):
    def test_every_pushed_branch_is_caught_up(self):
        text = round_section()
        self.assertRegex(text, r"(?i)every branch the rebase moves")
        self.assertRegex(text, r"(?i)every layer from the round's PR up")
        self.assertRegex(text, r"(?i)caught-up remote head")

    def test_remote_head_is_rechecked_right_before_each_push(self):
        text = round_section()
        self.assertRegex(text, r"(?i)right before each[^\n]*push-branch\.sh")
        self.assertIn("git rev-parse origin/<branch>", text)
        self.assertRegex(text, r"(?i)(not|no longer) equal[^\n]*question item[^\n]*push nothing more")

    def test_upstack_conflict_after_a_fix_is_not_a_second_findings_item(self):
        text = round_section()
        self.assertRegex(text, r"(?i)upstack[^\n]*conflict[^\n]*(not|never)[^\n]*second findings item")
        self.assertRegex(text, r"(?i)pushes no more layers")
        self.assertRegex(text, r"(?i)finish(es)? the round's Phase 3")
        self.assertRegex(text, r"(?i)ends? the round `partial`[^\n]*`why`")


class Changeset(unittest.TestCase):
    def test_changeset_is_minor(self):
        self.assertTrue(CHANGESET.is_file(), ".changeset/admiral-feedback-rounds.md is missing")
        self.assertIn('"jasonbuffin-skills": minor', CHANGESET.read_text(encoding="utf-8"))

    def test_no_text_uses_the_old_rounds_directory(self):
        for path in (SKILL, PF, MODES, CHANGESET):
            self.assertNotIn("rounds/<N>", path.read_text(encoding="utf-8"), path.name)


class StateSetAcceptsFeedbackKeys(unittest.TestCase):
    """Guard: state-set.sh needs no change for the round's mode keys."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "repo").mkdir()
        env = {**os.environ, "HARNESS": "claude", "AGENT_TEAMS_DIR": str(root / "teams")}
        subprocess.run(
            [str(TEAM_INIT), "seed", str(root / "repo")], env=env, capture_output=True, text=True, check=True
        )
        self.run_dir = root / "teams" / "seed"
        self.env = env

    def set_mode(self, *pairs):
        done = subprocess.run(
            [str(STATE_SET), str(self.run_dir), "mode", "--set", *pairs],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""), pairs)
        return (self.run_dir / "state.md").read_text(encoding="utf-8")

    def test_round_keys_with_spaces_are_accepted(self):
        text = self.set_mode("feedback round=2", "feedback status=open")
        self.assertIn("feedback round", text)
        self.assertRegex(text, r"feedback round\W+2\b")
        self.assertRegex(text, r"feedback status\W+open\b")

    def test_closing_a_round_and_setting_the_result_in_one_call(self):
        self.set_mode("feedback round=2", "feedback status=open")
        text = self.set_mode("feedback status=closed", "result=done")
        self.assertRegex(text, r"feedback status\W+closed\b")
        self.assertNotRegex(text, r"feedback status\W+open\b")
        self.assertRegex(text, r"result\W+done\b")


if __name__ == "__main__":
    unittest.main()
