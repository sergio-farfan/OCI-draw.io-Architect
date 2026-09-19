"""Settings tests for the one persisted view choice (A4) and the command's Step 1 question."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = TESTS_DIR.parent
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import detect_settings as ds  # noqa: E402
import oci_view as ov  # noqa: E402

COMMAND = (PLUGIN_ROOT / "commands" / "drawio-architect.md").read_text(encoding="utf-8")


class SettingsTests(unittest.TestCase):
    def test_purpose_has_a_stable_place_in_the_frontmatter(self):
        self.assertIn("purpose", ds.FIELD_ORDER)
        text = ds.to_yaml_frontmatter({"region": "us-ashburn-1", "purpose": "security",
                                       "terraform_dir": "infra"})
        lines = text.splitlines()
        self.assertLess(lines.index('purpose: "security"'), lines.index('terraform_dir: "infra"'))
        self.assertGreater(lines.index('purpose: "security"'), lines.index('region: "us-ashburn-1"'))

    def test_purpose_is_answered_never_detected(self):
        """A4 / Step 0: a view choice is never detected, only answered and remembered."""
        self.assertEqual(ds.ANSWERED_KEYS, ("purpose",))
        for key in ds.ANSWERED_KEYS:
            self.assertNotIn(key, ds.USEFUL_KEYS)
        detected = ds.detect(str(TESTS_DIR / "fixtures" / "detect"), query_cli=False)
        self.assertNotIn("purpose", detected)

    def test_a_purpose_alone_is_not_a_useful_settings_file(self):
        self.assertFalse(ds.has_useful_settings({"purpose": "network"}))

    def test_no_other_view_key_is_persisted(self):
        for key in ("detail", "label_mode", "layers", "filter", "mode", "global_services"):
            self.assertNotIn(key, ds.FIELD_ORDER, key)


class CommandTests(unittest.TestCase):
    def test_step_1_asks_the_purpose_with_the_six_verbatim_names(self):
        for title in ov.PURPOSE_TITLES.values():
            self.assertIn(title, COMMAND, title)
        self.assertIn("AskUserQuestion", COMMAND)

    def test_step_0_documents_the_persisted_purpose_key(self):
        self.assertIn("purpose:", COMMAND)
        self.assertRegex(COMMAND, r"purpose[^\n]*remember")

    def test_step_2_states_the_per_front_end_mode_default(self):
        self.assertRegex(COMMAND, r"--mode[^\n]*participating")
        self.assertIn("query_tenancy.py", COMMAND)

    def test_step_2_says_a_live_tenancy_is_cut_down_before_the_model_is_written(self):
        self.assertRegex(COMMAND, r"before the model is written")

    def test_step_5_checks_the_captions_and_the_layers_panel(self):
        self.assertRegex(COMMAND, r"no OCID")
        self.assertRegex(COMMAND, r"layers panel")

    def test_step_6_reports_the_view_and_how_to_toggle_a_layer(self):
        self.assertRegex(COMMAND, r"Cmd\+Shift\+L|Ctrl\+Shift\+L")

    def test_every_new_layout_flag_is_named_in_the_command(self):
        for flag in ("--purpose", "--detail", "--label-mode", "--label-fields", "--layers",
                     "--hidden-layers", "--filter", "--mode", "--discovery",
                     "--global-services"):
            self.assertIn(flag, COMMAND, flag)

    def test_the_command_names_no_forbidden_identity(self):
        self.assertNotRegex(COMMAND, re.compile(r"co-authored|generated with", re.I))
