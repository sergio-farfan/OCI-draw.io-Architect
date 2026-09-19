"""Tests for the v1.5.0 three-valued service scope and the 'name' subnet-label mode."""
from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import oci_topology as ot  # noqa: E402


def stderr_of(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


class ServiceScopeTests(unittest.TestCase):
    def test_the_seven_global_keys_are_the_guidelines_section_4_list(self):
        self.assertEqual(sorted(ot.GLOBAL_ICON_KEYS),
                         ["audit", "auditing", "dns", "iam", "identity", "policies", "policy"])
        self.assertEqual(ot.SERVICE_SCOPES, ("vcn", "regional", "global"))

    def test_every_global_key_is_also_still_in_the_regional_table(self):
        """6.7: with global_services 'osn' nothing moves, so is_regional must keep saying yes."""
        for key in ot.GLOBAL_ICON_KEYS:
            self.assertIn(key, ot.REGIONAL_ICON_KEYS, key)
            self.assertTrue(ot.is_regional({"icon": key}), key)

    def test_a_global_icon_classifies_as_global(self):
        for key in ("iam", "identity", "policies", "auditing", "dns"):
            self.assertEqual(ot.service_scope({"icon": key}), "global", key)
            self.assertTrue(ot.is_global({"icon": key}), key)

    def test_a_regional_icon_is_regional_and_not_global(self):
        for key in ("logging", "vault", "buckets", "apm"):
            self.assertEqual(ot.service_scope({"icon": key}), "regional", key)
            self.assertFalse(ot.is_global({"icon": key}), key)

    def test_an_unknown_icon_stays_vcn_resident(self):
        self.assertEqual(ot.service_scope({"icon": "mount_target"}), "vcn")
        self.assertFalse(ot.is_regional({"icon": "mount_target"}))

    def test_an_explicit_scope_wins_over_both_tables(self):
        self.assertEqual(ot.service_scope({"icon": "iam", "scope": "regional"}), "regional")
        self.assertEqual(ot.service_scope({"icon": "logging", "scope": "global"}), "global")
        self.assertEqual(ot.service_scope({"icon": "iam", "scope": "vcn"}), "vcn")
        self.assertFalse(ot.is_regional({"icon": "iam", "scope": "vcn"}))

    def test_an_unknown_scope_raises(self):
        with self.assertRaises(ValueError) as ctx:
            ot.service_scope({"icon": "iam", "scope": "planetary"})
        self.assertIn("services[].scope", str(ctx.exception))

    def test_the_legacy_regional_boolean_still_wins_over_the_icon_tables(self):
        self.assertEqual(ot.service_scope({"icon": "iam", "regional": False}), "vcn")
        self.assertEqual(ot.service_scope({"icon": "mount_target", "regional": True}), "regional")
        self.assertEqual(ot.service_scope({"icon": "iam", "regional": "true"}), "regional")

    def test_a_private_dns_resolver_stays_vcn_resident(self):
        """The dns icon is global; oci_dns_resolver is not a global service."""
        self.assertEqual(ot.service_scope({"icon": "dns", "type": "oci_dns_resolver"}), "vcn")
        self.assertEqual(ot.service_scope({"icon": "dns"}), "global")

    def test_a_bad_regional_value_warns_once_and_falls_back_to_the_tables(self):
        ot._WARNED.clear()
        scope, err = stderr_of(ot.service_scope, {"icon": "iam", "regional": "maybe"})
        self.assertEqual(scope, "global")
        self.assertIn("WARNING: regional: 'maybe' is not a boolean", err)


class SubnetLabelNameModeTests(unittest.TestCase):
    def test_the_enum_widens_without_changing_the_first_two_values(self):
        """5: an enum WIDENING - every 1.4.0 value stays valid and keeps its index."""
        self.assertEqual(ot.SUBNET_LABEL_MODES, ("twoline", "inline", "name"))
        self.assertEqual(ot.subnet_label_mode({}), "twoline")
        self.assertEqual(ot.subnet_label_mode({"subnet_label": "name"}), "name")
        with self.assertRaises(ValueError):
            ot.subnet_label_mode({"subnet_label": "titles"})

    def test_label_parts_can_drop_the_cidr_line(self):
        self.assertEqual(ot.label_parts("sn-app", "10.0.2.0/24", False),
                         ("sn-app (Private)", "10.0.2.0/24"))
        self.assertEqual(ot.label_parts("sn-app", "10.0.2.0/24", False, with_cidr=False),
                         ("sn-app (Private)", ""))
        self.assertEqual(ot.label_parts("sn-app", "10.0.2.0/24", True, with_cidr=False),
                         ("sn-app (Public)", ""))

    def test_dropping_the_cidr_keeps_the_public_private_token(self):
        """6.3: 'minimal' is the name plus the token, no CIDR - the token never goes."""
        line1, line2 = ot.label_parts("sn-lb", None, True, with_cidr=False)
        self.assertEqual((line1, line2), ("sn-lb (Public)", ""))


if __name__ == "__main__":
    unittest.main()
