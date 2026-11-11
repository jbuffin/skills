"""Text evals for SKILL.md: inside Admiral, pins and autopilot come from Admiral's environment (issue #200, ADR 0009).

The seam is the shipped SKILL.md text. `crew.py` already ignores launch-text pins inside Admiral; its tests are
test_crew_cast.py and test_crew_resolution.py. These checks hold the instructions to the same rule: inside Admiral
(`ADMIRAL_SHIP` set) a launch-text pin or `--autopilot` is ignored and Commodore writes no run member, and outside
Admiral both still work. Assertions are short distinctive phrases in one paragraph each, not whole sentences.

Run from the repo root: python3 -m unittest evals/commodore/test_env_pins.py -v
"""

import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILL = REPO / "skills" / "engineering" / "commodore" / "SKILL.md"
LINES = SKILL.read_text(encoding="utf-8").splitlines()


def paragraph(start):
    """The one line of SKILL.md that starts with `start`."""
    found = [line for line in LINES if line.startswith(start)]
    assert len(found) == 1, f"expected one line starting {start!r}, found {len(found)}"
    return found[0]


class RunLayerInsideAdmiral(unittest.TestCase):
    def test_crew_members_item_ignores_launch_text_inside_admiral(self):
        item = paragraph("4. run, inside Admiral")
        self.assertRegex(item, r"(?i)launch text")
        self.assertRegex(item, r"(?i)ignor")
        self.assertRegex(item, r"(?i)writes? no (run )?member|no run member")
        self.assertIn("ADMIRAL_RUN_CREW", item)

    def test_crew_members_item_keeps_engineer_members_outside_admiral(self):
        item = paragraph("4. run, inside Admiral")
        self.assertIn("`<run>/crew/`", item)
        self.assertRegex(item, r"(?i)outside Admiral")

    def test_phase_1_writes_no_run_member_inside_admiral(self):
        step = paragraph("1. Write the profile.")
        self.assertRegex(step, r"(?i)inside Admiral[^.]*(launch text|ignor)|(launch text|ignor)[^.]*inside Admiral")
        self.assertRegex(step, r"(?i)ignor")
        self.assertRegex(step, r"(?i)no run member|writes? no (run )?member|write no (run )?member")

    def test_phase_1_pick_choices_are_the_coordinators_own(self):
        step = paragraph("1. Write the profile.")
        self.assertRegex(step, r"(?i)`--pick` choices[^.]*own[^.]*never a member named in the launch text")

    def test_ad_hoc_member_takes_nothing_from_launch_text_inside_admiral(self):
        text = paragraph("When no member fits a role")
        self.assertRegex(text, r"(?i)inside Admiral, take nothing for an ad hoc member from the launch text")
        self.assertRegex(text, r"(?i)no name, role, skill, model, harness or instruction")
        self.assertRegex(text, r"(?i)only from your own judgment of the task")

    def test_launch_text_instruction_rule_spares_the_task_instruction(self):
        item = paragraph("4. run, inside Admiral")
        self.assertRegex(item, r"(?i)crew member, pin, or a member's skill or instruction")

    def test_inside_admiral_is_defined_once_by_ship_non_empty(self):
        item = paragraph("**Turning it on.**")
        self.assertRegex(item, r"(?i)inside Admiral \(`ADMIRAL_SHIP` non-empty[^)]*references/crew-members\.md")

    def test_phase_1_still_writes_engineers_members_outside_admiral(self):
        step = paragraph("1. Write the profile.")
        self.assertIn("`<run>/crew/`", step)
        self.assertIn("ADMIRAL_RUN_CREW", step)


class AutopilotInsideAdmiral(unittest.TestCase):
    def test_only_the_env_var_turns_autopilot_on_inside_admiral(self):
        text = paragraph("**Turning it on.**")
        self.assertRegex(text, r"(?i)inside Admiral")
        self.assertIn("ADMIRAL_AUTOPILOT=1", text)
        self.assertRegex(text, r"(?i)ignor")
        self.assertRegex(text, r"`--autopilot`")

    def test_launch_switch_still_works_outside_admiral(self):
        text = paragraph("**Turning it on.**")
        self.assertRegex(text, r"(?i)outside Admiral")
        self.assertRegex(text, r"(?i)outside Admiral[^.]*`--autopilot`|`--autopilot`[^.]*outside Admiral")

    def test_env_var_still_turns_autopilot_on_outside_admiral(self):
        text = paragraph("**Turning it on.**")
        self.assertRegex(text, r"(?i)outside Admiral[^.]*`ADMIRAL_AUTOPILOT=1`")

    def test_launch_switch_is_not_a_blanket_trigger(self):
        text = paragraph("**Turning it on.**")
        self.assertNotRegex(text, re.compile(r"is on when `ADMIRAL_AUTOPILOT=1` is set, or when the launch text"))


if __name__ == "__main__":
    unittest.main()
