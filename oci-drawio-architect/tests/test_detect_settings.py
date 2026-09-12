"""Unit tests for scripts/detect_settings.py.

Run with:
    python3 -m unittest discover -s oci-drawio-architect/tests

No test touches the network, the OCI CLI or the real ~/.oci/config: ``shutil.which``
and ``subprocess.run`` are monkeypatched and ``OCI_CLI_CONFIG_FILE`` points at a
non-existent path.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
FIXTURES = TESTS_DIR / "fixtures" / "detect"
SCRIPT = SCRIPTS_DIR / "detect_settings.py"

sys.path.insert(0, str(SCRIPTS_DIR))
import detect_settings as ds  # noqa: E402


NO_CONFIG = {"OCI_CLI_CONFIG_FILE": "/nonexistent/oci-config-for-tests"}


class IsolatedEnvMixin:
    """Isolate every test from the developer's OCI config and CLI."""

    def setUp(self):
        super().setUp()
        self._stack = contextlib.ExitStack()
        self._stack.enter_context(mock.patch.dict(os.environ, NO_CONFIG))
        self._stack.enter_context(mock.patch.object(ds.shutil, "which", return_value=None))
        self._stack.enter_context(
            mock.patch.object(ds.subprocess, "run",
                              side_effect=AssertionError("subprocess.run must not be called")))
        self.addCleanup(self._stack.close)


# ---------------------------------------------------------------------------
# HCL helpers
# ---------------------------------------------------------------------------

class StripCommentsTests(unittest.TestCase):
    def test_strips_hash_slash_and_block_comments(self):
        text = 'a = 1 # hash\nb = 2 // slashes\n/* block\n comment */ c = 3\n'
        out = ds.strip_hcl_comments(text)
        self.assertNotIn("hash", out)
        self.assertNotIn("slashes", out)
        self.assertNotIn("block", out)
        self.assertIn("c = 3", out)
        # newlines preserved so line structure survives
        self.assertEqual(out.count("\n"), text.count("\n"))

    def test_preserves_comment_markers_inside_strings(self):
        text = 'url = "https://example.com/#frag" # real comment\n'
        self.assertEqual(ds.strip_hcl_comments(text), 'url = "https://example.com/#frag" \n')

    def test_preserves_heredoc_content(self):
        text = 'x = <<-EOT\n  #!/bin/bash\n  echo "unbalanced\n  EOT\ny = "v" # c\n'
        out = ds.strip_hcl_comments(text)
        self.assertIn("#!/bin/bash", out)
        self.assertIn('y = "v" ', out)
        self.assertNotIn("# c", out)


class BlockParsingTests(unittest.TestCase):
    def test_one_line_block_then_block_with_default(self):
        text = 'variable "tenancy_ocid" {}\nvariable "other" { default = "ocid1.tenancy.oc1..other" }\n'
        blocks = list(ds.iter_top_level_blocks(text))
        self.assertEqual([(k, l) for k, l, _ in blocks],
                         [("variable", ["tenancy_ocid"]), ("variable", ["other"])])
        self.assertEqual(ds.top_level_attrs(blocks[0][2]), {})
        self.assertEqual(ds.top_level_attrs(blocks[1][2]), {"default": '"ocid1.tenancy.oc1..other"'})

    def test_indented_closing_brace_and_nested_block(self):
        text = ('variable "region" {\n'
                '  default = "eu-frankfurt-1"\n'
                '  validation {\n'
                '    condition = true\n'
                '    error_message = "x"\n'
                '  }\n'
                '  }\n'
                'variable "next" { default = "later" }\n')
        blocks = list(ds.iter_top_level_blocks(text))
        self.assertEqual(len(blocks), 2)
        attrs = ds.top_level_attrs(blocks[0][2])
        self.assertEqual(attrs, {"default": '"eu-frankfurt-1"'})
        self.assertNotIn("condition", attrs)

    def test_loose_vcn_entries(self):
        raw = ('{\n'
               '  hub = {\n    display_name = "hub-vcn"\n    cidr = "10.0.0.0/16"\n  }\n'
               '  spoke = { display_name = "spoke-vcn", cidr_blocks = ["10.1.0.0/16"] }\n'
               '}')
        self.assertEqual(ds.loose_vcn_entries(raw), [
            {"name": "hub-vcn", "cidr": "10.0.0.0/16"},
            {"name": "spoke-vcn", "cidr": "10.1.0.0/16"},
        ])


# ---------------------------------------------------------------------------
# Terraform parsing via fixtures
# ---------------------------------------------------------------------------

class TerraformFixtureTests(IsolatedEnvMixin, unittest.TestCase):
    def detect(self, name):
        return ds.detect(str(FIXTURES / name), project_dir=FIXTURES, query_cli=False)

    def test_region_from_variable_default_with_comments_and_aliases(self):
        s = self.detect("var_default")
        self.assertEqual(s["region"], "eu-frankfurt-1")           # not the aliased us-ashburn-1
        self.assertEqual(s["region_label"], "Frankfurt")
        self.assertEqual(s["oci_profile"], "FRANKFURT")           # var.profile resolved
        self.assertEqual(s["oci_auth"], "security_token")
        self.assertEqual(s["compartment_ocid"], "ocid1.compartment.oc1..aaaacomp")
        self.assertEqual(s["terraform_dir"], "var_default")

    def test_tenancy_without_default_is_not_taken_from_neighbouring_variable(self):
        s = self.detect("var_default")
        self.assertNotIn("tenancy_ocid", s)
        for v in s.values():
            self.assertNotIn("aaaaother", str(v))
            self.assertNotIn("commentedout", str(v))

    def test_vcns_and_compartments_from_resources_locals_and_defaults(self):
        s = self.detect("var_default")
        self.assertEqual(s["vcns"], [
            {"name": "hub-vcn", "cidr": "10.10.0.0/16"},
            {"name": "mgmt-vcn", "cidr": "10.20.0.0/16"},
            {"name": "spoke1-vcn", "cidr": "10.1.0.0/16"},
        ])
        self.assertEqual(s["compartments"], ["network"])
        self.assertEqual(s["compartment"], "network")

    def test_tfvars_precedence_later_auto_tfvars_wins(self):
        s = self.detect("tfvars_precedence")
        self.assertEqual(s["region"], "uk-london-1")               # b.auto > a.auto > terraform.tfvars > default
        self.assertEqual(s["region_label"], "London")
        self.assertEqual(s["tenancy_ocid"], "ocid1.tenancy.oc1..aaaatf")
        self.assertEqual(s["compartment_ocid"], "ocid1.compartment.oc1..aaaajson")  # *.auto.tfvars.json
        self.assertEqual(s["vcns"], [
            {"name": "hub-vcn", "cidr": "10.0.0.0/16"},
            {"name": "spoke-vcn", "cidr": "10.1.0.0/16"},
        ])

    def test_terraform_tfvars_overrides_variable_default(self):
        s = self.detect("tfvars_only")
        self.assertEqual(s["region"], "eu-frankfurt-1")

    def test_commented_out_region_is_ignored(self):
        s = self.detect("commented_region")
        self.assertNotIn("region", s)
        self.assertNotIn("region_label", s)
        self.assertEqual(s["oci_profile"], "DEFAULT")

    def test_backend_block_region_is_ignored(self):
        s = self.detect("backend_only")
        self.assertNotIn("region", s)
        self.assertFalse(ds.has_useful_settings(s))

    def test_invalid_tenancy_ocid_rejected_and_one_line_provider(self):
        s = self.detect("wrong_ocid")
        self.assertEqual(s["region"], "ap-osaka-1")
        self.assertNotIn("tenancy_ocid", s)


# ---------------------------------------------------------------------------
# Terraform directory discovery
# ---------------------------------------------------------------------------

def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


PROVIDER = 'provider "oci" {\n  region = "eu-frankfurt-1"\n}\n'


class FindTerraformDirTests(IsolatedEnvMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_prunes_ignored_dirs_and_reports_same_depth_alternatives(self):
        _write(self.tmp / ".terraform" / "modules" / "net" / "provider.tf", PROVIDER)
        _write(self.tmp / "node_modules" / "pkg" / "provider.tf", PROVIDER)
        _write(self.tmp / ".git" / "provider.tf", PROVIDER)
        _write(self.tmp / "envs" / "prod" / "main.tf", PROVIDER)
        _write(self.tmp / "envs" / "dev" / "providers.tf", PROVIDER)
        _write(self.tmp / "envs" / "prod" / "deeper" / "provider.tf", PROVIDER)
        _write(self.tmp / "modules" / "vcn" / "main.tf", 'resource "oci_core_vcn" "v" {}\n')
        _write(self.tmp / "modules" / "vcn" / "dev.tfvars", 'x = 1\n')

        dirs = ds.find_terraform_dirs(self.tmp)
        self.assertEqual([d.relative_to(self.tmp).as_posix() for d in dirs], ["envs/dev", "envs/prod"])
        self.assertEqual(ds.find_terraform_dir(self.tmp), self.tmp / "envs" / "dev")

        s = ds.detect(None, project_dir=self.tmp, query_cli=False)
        self.assertEqual(s["terraform_dir"], "envs/dev")
        self.assertEqual(s["terraform_dirs"], ["envs/dev", "envs/prod"])

    def test_commented_provider_does_not_count(self):
        _write(self.tmp / "a" / "provider.tf", '# provider "oci" {\n#  region = "x"\n# }\n')
        _write(self.tmp / "b" / "c" / "provider.tf", PROVIDER)
        self.assertEqual(ds.find_terraform_dir(self.tmp), self.tmp / "b" / "c")

    def test_falls_back_to_tfvars_dir(self):
        _write(self.tmp / "x" / "y" / "terraform.tfvars", 'region = "eu-frankfurt-1"\n')
        _write(self.tmp / "x" / "z" / "vars.auto.tfvars.json", '{}')
        self.assertEqual(
            [d.relative_to(self.tmp).as_posix() for d in ds.find_terraform_dirs(self.tmp)], ["x/y", "x/z"])

    def test_nothing_found(self):
        _write(self.tmp / "README.md", "hi")
        self.assertEqual(ds.find_terraform_dirs(self.tmp), [])
        self.assertIsNone(ds.find_terraform_dir(self.tmp))


# ---------------------------------------------------------------------------
# Region labels
# ---------------------------------------------------------------------------

REQUIRED_REGIONS = [
    "af-johannesburg-1", "ap-chuncheon-1", "ap-hyderabad-1", "ap-melbourne-1", "ap-mumbai-1",
    "ap-osaka-1", "ap-seoul-1", "ap-singapore-1", "ap-singapore-2", "ap-sydney-1", "ap-tokyo-1",
    "ca-montreal-1", "ca-toronto-1", "eu-amsterdam-1", "eu-frankfurt-1", "eu-frankfurt-2",
    "eu-jovanovac-1", "eu-madrid-1", "eu-madrid-2", "eu-marseille-1", "eu-milan-1", "eu-paris-1",
    "eu-stockholm-1", "eu-zurich-1", "il-jerusalem-1", "me-abudhabi-1", "me-dubai-1", "me-jeddah-1",
    "me-riyadh-1", "mx-monterrey-1", "mx-queretaro-1", "sa-bogota-1", "sa-santiago-1", "sa-saopaulo-1",
    "sa-valparaiso-1", "sa-vinhedo-1", "uk-cardiff-1", "uk-london-1", "us-ashburn-1", "us-chicago-1",
    "us-phoenix-1", "us-sanjose-1", "us-saltlake-2",
]


class RegionLabelTests(unittest.TestCase):
    def test_table_contains_current_regions_and_not_bogus_ones(self):
        for r in REQUIRED_REGIONS:
            self.assertIn(r, ds.REGION_LABELS, r)
        self.assertNotIn("eu-london-1", ds.REGION_LABELS)
        for r, label in ds.REGION_LABELS.items():
            self.assertRegex(r, ds.REGION_ID_RE.pattern)
            self.assertNotEqual(label, r)

    def test_known_labels(self):
        self.assertEqual(ds.region_display_label("uk-london-1"), "London")
        self.assertEqual(ds.region_display_label("me-abudhabi-1"), "Abu Dhabi")
        self.assertEqual(ds.region_display_label("eu-madrid-2"), "Madrid 2")
        self.assertEqual(ds.region_display_label("EU-FRANKFURT-1"), "Frankfurt")

    def test_derivation_without_table(self):
        self.assertEqual(ds._derive_region_label("me-abudhabi-1"), "Abu Dhabi")
        self.assertEqual(ds._derive_region_label("us-sanjose-1"), "San Jose")
        self.assertEqual(ds._derive_region_label("sa-saopaulo-1"), "Sao Paulo")
        self.assertEqual(ds._derive_region_label("us-saltlake-2"), "Salt Lake 2")
        self.assertEqual(ds._derive_region_label("eu-madrid-2"), "Madrid 2")
        self.assertEqual(ds._derive_region_label("uk-london-1"), "London")

    def test_unknown_region_never_gets_raw_identifier(self):
        self.assertEqual(ds.region_display_label("xx-foo-3"), "Foo 3")
        self.assertEqual(ds.region_display_label("zz-bar-1"), "Bar")
        for r in ("xx-foo-3", "zz-bar-1", "weird_thing", "ap-new-city-2"):
            self.assertNotEqual(ds.region_display_label(r), r)
        self.assertEqual(ds.region_display_label("ap-new-city-2"), "New City 2")
        self.assertEqual(ds.region_display_label(""), "")


# ---------------------------------------------------------------------------
# Logos
# ---------------------------------------------------------------------------

class FindLogosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.project = self.tmp / "project"
        self.plugin_logos = self.tmp / "plugin" / "logos"

    def test_dark_is_for_light_backgrounds_and_paths_are_relative(self):
        _write(self.project / "logos" / "company_logo_dark.png")
        _write(self.project / "logos" / "company_logo_light.png")
        _write(self.project / "images" / "screenshot_dark.png")      # images/ is not scanned
        _write(self.project / "assets" / "images" / "diagram.png")    # no "logo" in name
        logos = ds.find_logos(self.project, plugin_logos_dir=self.plugin_logos)
        self.assertEqual(logos, {
            "logo_light": "logos/company_logo_dark.png",
            "logo_dark": "logos/company_logo_light.png",
        })

    def test_black_white_keywords_and_svg(self):
        _write(self.project / "assets" / "logos" / "acme-black.svg")
        _write(self.project / "assets" / "logos" / "acme-white.svg")
        logos = ds.find_logos(self.project, plugin_logos_dir=self.plugin_logos)
        self.assertEqual(logos["logo_light"], "assets/logos/acme-black.svg")
        self.assertEqual(logos["logo_dark"], "assets/logos/acme-white.svg")

    def test_generic_logo_requires_logo_word_and_keyword_files_win(self):
        _write(self.project / "assets" / "images" / "brand_logo.svg")
        _write(self.project / "assets" / "images" / "brand_logo_dark.jpg")
        _write(self.project / "assets" / "images" / "hero.png")
        logos = ds.find_logos(self.project, plugin_logos_dir=self.plugin_logos)
        self.assertEqual(logos, {"logo_light": "assets/images/brand_logo_dark.jpg"})

        (self.project / "assets" / "images" / "brand_logo_dark.jpg").unlink()
        logos = ds.find_logos(self.project, plugin_logos_dir=self.plugin_logos)
        self.assertEqual(logos, {"logo_light": "assets/images/brand_logo.svg"})

    def test_plugin_local_fallback_is_absolute_and_loses_to_project(self):
        _write(self.plugin_logos / "default_logo_dark.png")
        _write(self.plugin_logos / "default_logo_white.png")
        self.project.mkdir(parents=True, exist_ok=True)
        logos = ds.find_logos(self.project, plugin_logos_dir=self.plugin_logos)
        self.assertTrue(os.path.isabs(logos["logo_light"]))
        self.assertTrue(logos["logo_light"].endswith("default_logo_dark.png"))
        self.assertTrue(logos["logo_dark"].endswith("default_logo_white.png"))

        _write(self.project / "docs" / "logos" / "corp_logo_black.png")
        logos = ds.find_logos(self.project, plugin_logos_dir=self.plugin_logos)
        self.assertEqual(logos["logo_light"], "docs/logos/corp_logo_black.png")
        self.assertTrue(logos["logo_dark"].endswith("default_logo_white.png"))


# ---------------------------------------------------------------------------
# OCI config
# ---------------------------------------------------------------------------

OCI_CONFIG = """\
[DEFAULT]
user=ocid1.user.oc1..aaaauser
Tenancy = ocid1.tenancy.oc1..aaaadefault ; auth tenancy
region=eu-frankfurt-1
fingerprint=aa:bb:cc

[TOKEN]
security_token_file = /Users/me/.oci/sessions/TOKEN/token
REGION = uk-london-1 # override

[BADTENANCY]
tenancy = ocid1.compartment.oc1..nottenancy
"""


class ParseOciConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.cfg = self.tmp / "config"
        self.cfg.write_text(OCI_CONFIG)

    def test_default_profile(self):
        self.assertEqual(ds.parse_oci_config("DEFAULT", config_path=str(self.cfg)),
                         {"tenancy_ocid": "ocid1.tenancy.oc1..aaaadefault", "region": "eu-frankfurt-1"})

    def test_named_profile_inherits_default_and_detects_security_token(self):
        got = ds.parse_oci_config("TOKEN", config_path=str(self.cfg))
        self.assertEqual(got, {
            "tenancy_ocid": "ocid1.tenancy.oc1..aaaadefault",
            "region": "uk-london-1",
            "oci_auth": "security_token",
        })
        self.assertEqual(ds.parse_oci_config("token", config_path=str(self.cfg)), got)

    def test_missing_profile_and_missing_file_and_invalid_tenancy(self):
        self.assertEqual(ds.parse_oci_config("NOPE", config_path=str(self.cfg)), {})
        self.assertEqual(ds.parse_oci_config("DEFAULT", config_path=str(self.tmp / "missing")), {})
        self.assertNotIn("tenancy_ocid", ds.parse_oci_config("BADTENANCY", config_path=str(self.cfg)))

    def test_env_var_override(self):
        with mock.patch.dict(os.environ, {"OCI_CLI_CONFIG_FILE": str(self.cfg)}):
            self.assertEqual(ds.parse_oci_config("TOKEN")["region"], "uk-london-1")


# ---------------------------------------------------------------------------
# OCI CLI
# ---------------------------------------------------------------------------

def _completed(args, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


TENANCY_JSON = json.dumps({"data": {"name": "acme", "id": "ocid1.tenancy.oc1..aaaatf"}})
SUBS_JSON = json.dumps({"data": [
    {"region-name": "eu-frankfurt-1", "is-home-region": True},
    {"region-name": "uk-london-1", "is-home-region": False},
]})


class QueryOciCliTests(unittest.TestCase):
    def test_skipped_when_oci_not_on_path(self):
        with mock.patch.object(ds.shutil, "which", return_value=None), \
             mock.patch.object(ds.subprocess, "run", side_effect=AssertionError("must not run")):
            got = ds.query_oci_cli("ocid1.tenancy.oc1..x", "DEFAULT")
        self.assertNotIn("tenancy_name", got)
        self.assertIn("not found on PATH", got["cli_warning"])

    def test_success_with_security_token_and_timeouts(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            if args[1:4] == ["iam", "tenancy", "get"]:
                return _completed(args, stdout=TENANCY_JSON)
            return _completed(args, stdout=SUBS_JSON)

        err = io.StringIO()
        with mock.patch.object(ds.shutil, "which", return_value="/usr/local/bin/oci"), \
             mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             contextlib.redirect_stderr(err):
            got = ds.query_oci_cli("ocid1.tenancy.oc1..aaaatf", "TOKEN", auth="security_token")

        self.assertEqual(got, {
            "tenancy_name": "acme",
            "subscribed_regions": ["eu-frankfurt-1", "uk-london-1"],
            "home_region": "eu-frankfurt-1",
        })
        self.assertIn("Querying OCI CLI (profile TOKEN)...", err.getvalue())
        self.assertEqual(len(calls), 2)
        for args, kwargs in calls:
            self.assertEqual(kwargs["timeout"], ds.CLI_TIMEOUT)
            self.assertIn("--auth", args)
            self.assertEqual(args[args.index("--auth") + 1], "security_token")
            self.assertEqual(args[args.index("--profile") + 1], "TOKEN")
            self.assertEqual(args[args.index("--tenancy-id") + 1], "ocid1.tenancy.oc1..aaaatf")

    def test_failure_reports_first_stderr_line_and_stops(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return _completed(args, stderr="ServiceError:\n{\n  \"code\": \"NotAuthenticated\"\n}\n", returncode=1)

        with mock.patch.object(ds.shutil, "which", return_value="/usr/local/bin/oci"), \
             mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             contextlib.redirect_stderr(io.StringIO()):
            got = ds.query_oci_cli("ocid1.tenancy.oc1..x", "DEFAULT")
        self.assertEqual(got, {"cli_warning": "ServiceError:"})
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--auth", calls[0])

    def test_timeout_is_reported(self):
        def fake_run(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        with mock.patch.object(ds.shutil, "which", return_value="/usr/local/bin/oci"), \
             mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             contextlib.redirect_stderr(io.StringIO()):
            got = ds.query_oci_cli("ocid1.tenancy.oc1..x", "DEFAULT")
        self.assertIn("timed out", got["cli_warning"])


class DetectTenancyMergeTests(unittest.TestCase):
    """Terraform tenancy is preferred; the OCI config tenancy is the auth identity."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        cfg = self.tmp / "config"
        cfg.write_text("[DEFAULT]\ntenancy = ocid1.tenancy.oc1..aaaaauth\nregion = ap-tokyo-1\n")
        self._env = mock.patch.dict(os.environ, {"OCI_CLI_CONFIG_FILE": str(cfg)})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_config_tenancy_does_not_replace_terraform_tenancy_without_cli(self):
        with mock.patch.object(ds.shutil, "which", return_value=None):
            s = ds.detect(str(FIXTURES / "tfvars_precedence"), project_dir=FIXTURES)
        self.assertEqual(s["tenancy_ocid"], "ocid1.tenancy.oc1..aaaatf")
        self.assertEqual(s["auth_tenancy_ocid"], "ocid1.tenancy.oc1..aaaaauth")
        self.assertEqual(s["region"], "uk-london-1")   # Terraform region beats config region
        self.assertIn("cli_warning", s)

    def test_cli_failure_on_both_keeps_terraform_tenancy(self):
        def fake_run(args, **kwargs):
            return _completed(args, stderr="ServiceError: NotAuthorizedOrNotFound", returncode=1)

        with mock.patch.object(ds.shutil, "which", return_value="/usr/local/bin/oci"), \
             mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             contextlib.redirect_stderr(io.StringIO()):
            s = ds.detect(str(FIXTURES / "tfvars_precedence"), project_dir=FIXTURES)
        self.assertEqual(s["tenancy_ocid"], "ocid1.tenancy.oc1..aaaatf")
        self.assertEqual(s["auth_tenancy_ocid"], "ocid1.tenancy.oc1..aaaaauth")
        self.assertNotIn("tenancy_name", s)
        self.assertEqual(s["cli_warning"], "ServiceError: NotAuthorizedOrNotFound")

    def test_cli_success_with_auth_tenancy_only_promotes_it(self):
        def fake_run(args, **kwargs):
            tenancy = args[args.index("--tenancy-id") + 1]
            if tenancy != "ocid1.tenancy.oc1..aaaaauth":
                return _completed(args, stderr="ServiceError: NotAuthorizedOrNotFound", returncode=1)
            if args[1:4] == ["iam", "tenancy", "get"]:
                return _completed(args, stdout=json.dumps({"data": {"name": "authco"}}))
            return _completed(args, stdout=SUBS_JSON)

        with mock.patch.object(ds.shutil, "which", return_value="/usr/local/bin/oci"), \
             mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             contextlib.redirect_stderr(io.StringIO()):
            s = ds.detect(str(FIXTURES / "tfvars_precedence"), project_dir=FIXTURES)
        self.assertEqual(s["tenancy_name"], "authco")
        self.assertEqual(s["tenancy_ocid"], "ocid1.tenancy.oc1..aaaaauth")
        self.assertEqual(s["terraform_tenancy_ocid"], "ocid1.tenancy.oc1..aaaatf")
        self.assertNotIn("auth_tenancy_ocid", s)
        self.assertEqual(s["home_region"], "eu-frankfurt-1")
        self.assertEqual(s["subscribed_regions"], ["eu-frankfurt-1", "uk-london-1"])
        self.assertNotIn("cli_warning", s)

    def test_cli_success_with_terraform_tenancy_keeps_it(self):
        def fake_run(args, **kwargs):
            if args[1:4] == ["iam", "tenancy", "get"]:
                return _completed(args, stdout=TENANCY_JSON)
            return _completed(args, stdout=SUBS_JSON)

        with mock.patch.object(ds.shutil, "which", return_value="/usr/local/bin/oci"), \
             mock.patch.object(ds.subprocess, "run", side_effect=fake_run), \
             contextlib.redirect_stderr(io.StringIO()):
            s = ds.detect(str(FIXTURES / "tfvars_precedence"), project_dir=FIXTURES)
        self.assertEqual(s["tenancy_name"], "acme")
        self.assertEqual(s["tenancy_ocid"], "ocid1.tenancy.oc1..aaaatf")
        self.assertEqual(s["auth_tenancy_ocid"], "ocid1.tenancy.oc1..aaaaauth")
        self.assertNotIn("terraform_tenancy_ocid", s)


# ---------------------------------------------------------------------------
# YAML output
# ---------------------------------------------------------------------------

class YamlFrontmatterTests(unittest.TestCase):
    def test_escaping_lists_and_order(self):
        out = ds.to_yaml_frontmatter({
            "logo_light": "C:\\Users\\me\\logo.png",
            "tenancy_name": 'Acme "Corp"',
            "vcns": [{"name": "hub", "cidr": "10.0.0.0/16"}],
            "subscribed_regions": ["eu-frankfurt-1", "uk-london-1"],
            "home_region": "eu-frankfurt-1",
            "compartments": ["network"],
            "cli_warning": "should not be emitted",
            "custom_flag": True,
        })
        lines = out.split("\n")
        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[-1], "---")
        self.assertEqual(lines[1], 'tenancy_name: "Acme \\"Corp\\""')
        self.assertIn('logo_light: "C:\\\\Users\\\\me\\\\logo.png"', lines)
        self.assertIn('vcns: [{"name": "hub", "cidr": "10.0.0.0/16"}]', lines)
        self.assertIn('subscribed_regions: ["eu-frankfurt-1", "uk-london-1"]', lines)
        self.assertIn('home_region: "eu-frankfurt-1"', lines)
        self.assertIn('compartments: ["network"]', lines)
        self.assertIn("custom_flag: true", lines)
        self.assertNotIn("cli_warning", out)
        # Every string scalar round-trips through a JSON (== YAML double-quoted) parser.
        for line in lines[1:-1]:
            key, _, value = line.partition(": ")
            if value.startswith('"'):
                self.assertIsInstance(json.loads(value), str, line)
        self.assertEqual(json.loads(lines[1].partition(": ")[2]), 'Acme "Corp"')

    def test_none_values_skipped(self):
        self.assertEqual(ds.to_yaml_frontmatter({"region": None}), "---\n---")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class CliTests(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        env = dict(os.environ, **NO_CONFIG)
        env["PATH"] = str(Path(tempfile.gettempdir()) / "definitely-no-oci-here")
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              cwd=str(cwd or FIXTURES), env=env, timeout=60)

    def test_help(self):
        proc = self.run_cli("-h")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage", proc.stdout.lower())

    def test_fixture_prints_yaml_on_stdout_and_summary_on_stderr(self):
        proc = self.run_cli(str(FIXTURES / "var_default"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[-1], "---")
        self.assertIn('region: "eu-frankfurt-1"', lines)
        self.assertIn('region_label: "Frankfurt"', lines)
        self.assertIn('oci_profile: "FRANKFURT"', lines)
        self.assertIn('compartment: "network"', lines)
        self.assertNotIn("tenancy_ocid", proc.stdout)
        self.assertIn("Detected:", proc.stderr)
        # No tenancy OCID in this fixture, so the CLI is never consulted.
        self.assertNotIn("oci CLI", proc.stderr)

    def test_missing_cli_is_reported_when_a_tenancy_is_known(self):
        proc = self.run_cli(str(FIXTURES / "tfvars_precedence"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('tenancy_ocid: "ocid1.tenancy.oc1..aaaatf"', proc.stdout)
        self.assertNotIn("tenancy_name", proc.stdout)
        self.assertIn("Warning: oci CLI not found on PATH", proc.stderr)

    def test_no_cli_flag(self):
        proc = self.run_cli(str(FIXTURES / "tfvars_precedence"), "--no-cli")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('region: "uk-london-1"', proc.stdout)
        self.assertNotIn("Querying OCI CLI", proc.stderr)
        self.assertNotIn("oci CLI not found", proc.stderr)

    def test_missing_dir_exits_2(self):
        proc = self.run_cli(str(FIXTURES / "does_not_exist"))
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertIn("does not exist", proc.stderr)

    def test_nothing_detected_exits_1(self):
        with tempfile.TemporaryDirectory() as empty:
            proc = self.run_cli(str(FIXTURES / "backend_only"), cwd=empty)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertIn("No settings detected", proc.stderr)

    def test_alternatives_printed_to_stderr(self):
        with tempfile.TemporaryDirectory() as root:
            _write(Path(root) / "envs" / "dev" / "providers.tf", PROVIDER)
            _write(Path(root) / "envs" / "prod" / "main.tf", PROVIDER)
            _write(Path(root) / ".terraform" / "x" / "provider.tf", PROVIDER)
            proc = self.run_cli("--no-cli", cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('terraform_dir: "envs/dev"', proc.stdout)
        self.assertIn('terraform_dirs: ["envs/dev", "envs/prod"]', proc.stdout)
        self.assertIn("Alternatives: envs/prod", proc.stderr)


if __name__ == "__main__":
    unittest.main()
