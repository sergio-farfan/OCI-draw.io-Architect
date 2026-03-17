#!/usr/bin/env python3
"""Auto-detect OCI diagram settings from Terraform configs and OCI CLI.

Probes three sources in order:
  1. Terraform files (provider.tf, variables.tf, *.auto.tfvars)
  2. OCI CLI (oci iam tenancy get, oci iam region-subscription list)
  3. OCI config file (~/.oci/config)

Outputs a YAML frontmatter block suitable for .claude/oci-drawio-architect.local.md

Usage:
    python3 detect_settings.py [terraform_dir]

    terraform_dir: Path to a Terraform environment directory (default: auto-detect)

Examples:
    python3 detect_settings.py
    python3 detect_settings.py terraform/environments/frankfurt
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


def find_terraform_dir() -> Optional[Path]:
    """Walk up from cwd looking for provider.tf or *.auto.tfvars."""
    candidates = [
        Path.cwd(),
        *Path.cwd().rglob("provider.tf"),
    ]
    # Direct children first
    for f in Path.cwd().glob("**/provider.tf"):
        return f.parent
    return None


def parse_provider_tf(tf_dir: Path) -> dict:
    """Extract region and profile from provider.tf."""
    result = {}
    provider_tf = tf_dir / "provider.tf"
    if not provider_tf.exists():
        return result

    text = provider_tf.read_text()

    m = re.search(r'region\s*=\s*"([^"]+)"', text)
    if m:
        result["region"] = m.group(1)

    m = re.search(r'config_file_profile\s*=\s*"([^"]+)"', text)
    if m:
        result["oci_profile"] = m.group(1)

    return result


def parse_terraform_tfvars(tf_dir: Path) -> dict:
    """Extract tenancy_ocid from .tfvars or variables."""
    result = {}

    # Check terraform.tfvars
    for tfvars in tf_dir.glob("*.tfvars"):
        text = tfvars.read_text()
        m = re.search(r'tenancy_ocid\s*=\s*"([^"]+)"', text)
        if m:
            result["tenancy_ocid"] = m.group(1)
            break

    # Check variables.tf for default value
    if "tenancy_ocid" not in result:
        var_tf = tf_dir / "variables.tf"
        if var_tf.exists():
            text = var_tf.read_text()
            m = re.search(
                r'variable\s+"tenancy_ocid".*?default\s*=\s*"([^"]+)"',
                text, re.DOTALL)
            if m:
                result["tenancy_ocid"] = m.group(1)

    return result


def parse_oci_config(profile: str = "DEFAULT") -> dict:
    """Extract tenancy OCID and region from ~/.oci/config."""
    result = {}
    config_path = Path.home() / ".oci" / "config"
    if not config_path.exists():
        return result

    text = config_path.read_text()
    # Find the right profile section
    sections = re.split(r'^\[([^\]]+)\]', text, flags=re.MULTILINE)
    for i in range(1, len(sections), 2):
        if sections[i].strip() == profile:
            body = sections[i + 1]
            m = re.search(r'^tenancy\s*=\s*(.+)$', body, re.MULTILINE)
            if m:
                result["tenancy_ocid"] = m.group(1).strip()
            m = re.search(r'^region\s*=\s*(.+)$', body, re.MULTILINE)
            if m:
                result.setdefault("region", m.group(1).strip())
            break

    return result


def query_oci_cli(tenancy_ocid: str, profile: str = "DEFAULT") -> dict:
    """Query OCI CLI for tenancy name and subscribed regions."""
    result = {}

    # Get tenancy name
    try:
        out = subprocess.run(
            ["oci", "iam", "tenancy", "get",
             "--tenancy-id", tenancy_ocid,
             "--profile", profile],
            capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            data = json.loads(out.stdout)
            result["tenancy_name"] = data["data"]["name"]
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    # Get subscribed regions
    try:
        out = subprocess.run(
            ["oci", "iam", "region-subscription", "list",
             "--tenancy-id", tenancy_ocid,
             "--profile", profile],
            capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            data = json.loads(out.stdout)
            regions = [r["region-name"] for r in data["data"]]
            result["subscribed_regions"] = regions
            # Find home region
            for r in data["data"]:
                if r.get("is-home-region"):
                    result["home_region"] = r["region-name"]
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    return result


# ---------------------------------------------------------------------------
# Region display names
# ---------------------------------------------------------------------------
REGION_LABELS = {
    "eu-frankfurt-1": "Frankfurt",
    "ap-singapore-1": "Singapore",
    "us-ashburn-1": "Ashburn",
    "us-phoenix-1": "Phoenix",
    "eu-amsterdam-1": "Amsterdam",
    "eu-london-1": "London",
    "ap-tokyo-1": "Tokyo",
    "ap-mumbai-1": "Mumbai",
    "ap-sydney-1": "Sydney",
    "ca-toronto-1": "Toronto",
    "sa-saopaulo-1": "Sao Paulo",
    "me-jeddah-1": "Jeddah",
    "eu-zurich-1": "Zurich",
    "ap-seoul-1": "Seoul",
    "ap-osaka-1": "Osaka",
    "eu-marseille-1": "Marseille",
    "eu-milan-1": "Milan",
    "eu-stockholm-1": "Stockholm",
    "eu-paris-1": "Paris",
    "eu-madrid-1": "Madrid",
    "me-dubai-1": "Dubai",
    "af-johannesburg-1": "Johannesburg",
    "us-chicago-1": "Chicago",
    "us-sanjose-1": "San Jose",
    "ap-melbourne-1": "Melbourne",
    "ap-hyderabad-1": "Hyderabad",
    "il-jerusalem-1": "Jerusalem",
}


def find_logos(project_dir: Path) -> dict:
    """Find logo files in common locations."""
    result = {}
    search_paths = [
        project_dir / "Network" / "Documents" / "logos",
        project_dir / "logos",
        project_dir / "assets" / "logos",
        project_dir / "images",
    ]
    for logos_dir in search_paths:
        if not logos_dir.is_dir():
            continue
        for f in logos_dir.iterdir():
            name_lower = f.name.lower()
            if not f.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg"):
                continue
            # Prefer files with "black" or "light" for light backgrounds
            if "black" in name_lower or "light" in name_lower:
                result.setdefault("logo_light", str(f))
            # Files with "white" or "dark" for dark backgrounds
            elif "white" in name_lower or "dark" in name_lower:
                result.setdefault("logo_dark", str(f))
            # Generic logo
            elif "logo" in name_lower and "logo_light" not in result:
                result.setdefault("logo_light", str(f))

    return result


def detect(tf_dir_arg: str | None = None) -> dict:
    """Run full detection pipeline. Returns merged settings dict."""
    settings: dict = {}
    project_dir = Path.cwd()

    # 1. Find Terraform directory
    tf_dir = None
    if tf_dir_arg:
        tf_dir = Path(tf_dir_arg).resolve()
    else:
        tf_dir_path = find_terraform_dir()
        if tf_dir_path:
            tf_dir = tf_dir_path

    # 2. Parse Terraform files (region, profile, terraform tenancy OCID)
    tf_tenancy_ocid = None
    if tf_dir and tf_dir.exists():
        settings.update(parse_provider_tf(tf_dir))
        tf_data = parse_terraform_tfvars(tf_dir)
        tf_tenancy_ocid = tf_data.get("tenancy_ocid")
        settings.update(tf_data)
        settings["terraform_dir"] = str(tf_dir)

    # 3. Parse OCI config file - its tenancy OCID is the auth identity,
    #    which may differ from the one in terraform.tfvars (e.g., cross-tenancy)
    profile = settings.get("oci_profile", "DEFAULT")
    oci_config = parse_oci_config(profile)
    # OCI config tenancy is the auth OCID - prefer it for CLI queries
    config_tenancy_ocid = oci_config.get("tenancy_ocid")
    for k, v in oci_config.items():
        settings.setdefault(k, v)

    # 4. Query OCI CLI for tenancy name - use config OCID (auth identity)
    #    falling back to terraform OCID
    cli_tenancy_ocid = config_tenancy_ocid or tf_tenancy_ocid
    if cli_tenancy_ocid:
        cli_data = query_oci_cli(cli_tenancy_ocid, profile)
        for k, v in cli_data.items():
            settings.setdefault(k, v)
        # Ensure we store the auth tenancy OCID (the one that works with CLI)
        if config_tenancy_ocid:
            settings["tenancy_ocid"] = config_tenancy_ocid

    # 5. Derive display labels
    region = settings.get("region", "")
    settings.setdefault("region_label", REGION_LABELS.get(region, region))

    # 6. Find logos
    logos = find_logos(project_dir)
    settings.update(logos)

    return settings


def to_yaml_frontmatter(settings: dict) -> str:
    """Format settings as YAML frontmatter for .local.md file."""
    lines = ["---"]

    # Ordered output for readability
    field_order = [
        ("tenancy_name", "Tenancy display name"),
        ("tenancy_ocid", "Tenancy OCID"),
        ("region", "OCI region identifier"),
        ("region_label", "Region display name (for diagram titles)"),
        ("oci_profile", "OCI CLI profile name"),
        ("compartment", "Default compartment (set manually)"),
        ("logo_light", "Logo for light backgrounds"),
        ("logo_dark", "Logo for dark backgrounds"),
        ("terraform_dir", "Terraform directory used for detection"),
    ]

    for key, comment in field_order:
        if key in settings:
            val = settings[key]
            if isinstance(val, str):
                lines.append(f'{key}: "{val}"')
            elif isinstance(val, list):
                lines.append(f'{key}: {json.dumps(val)}')
            else:
                lines.append(f'{key}: {val}')

    lines.append("---")
    return "\n".join(lines)


def main():
    tf_dir_arg = sys.argv[1] if len(sys.argv) > 1 else None
    settings = detect(tf_dir_arg)

    if not settings:
        print("No settings detected. Provide a Terraform directory as argument.", file=sys.stderr)
        sys.exit(1)

    yaml = to_yaml_frontmatter(settings)
    print(yaml)

    # Also print a summary to stderr
    print("\nDetected:", file=sys.stderr)
    for k, v in settings.items():
        if k in ("subscribed_regions",):
            continue
        print(f"  {k}: {v}", file=sys.stderr)


if __name__ == "__main__":
    main()
