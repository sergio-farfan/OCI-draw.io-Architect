#!/usr/bin/env python3
"""
build_icon_catalog.py - regenerate references/icon-catalog.md from the bundled SVGs.

Every SVG under the icon directory is usable with ``add_icon()`` by its filename
stem (e.g. ``compute_virtual_machine_vm``) without any registration.  On top of
that a set of short aliases (``vm``, ``drg``, ...) is maintained in
``drawio_builder.ICON_ALIASES``; when that attribute is not available the aliases
can be supplied as a JSON file (``{"alias": "category/file.svg", ...}``).

Usage
-----
    build_icon_catalog.py                    # write references/icon-catalog.md
    build_icon_catalog.py --out FILE         # write somewhere else (preview/dry run)
    build_icon_catalog.py --check            # validate only, exit 1 on any problem
    build_icon_catalog.py --aliases FILE     # alias JSON fallback

Environment
-----------
    OCI_SVG_DIR   icon directory (default: ../icons next to this script)

Exit codes: 0 ok, 1 validation problems, 2 usage / missing inputs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent
DEFAULT_ICON_DIR = PLUGIN_ROOT / "icons"
DEFAULT_OUT = PLUGIN_ROOT / "skills" / "oci-drawio-architect" / "references" / "icon-catalog.md"
TEMPLATES_DIR = PLUGIN_ROOT / "skills" / "oci-drawio-architect" / "references" / "templates"

SVG_NS = "{http://www.w3.org/2000/svg}"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Leftover label-placeholder rectangle from the icon-set export.
PLACEHOLDER_RE = re.compile(
    r'<path d="M 0 100 L 100 100 L 100 0 L 0 0 L 0 100" fill="none" stroke="#000000"'
)

CATEGORY_TITLES = {
    "analytics_and_ai": "Analytics & AI",
    "applications": "Applications",
    "compute": "Compute",
    "database": "Database",
    "developer_services": "Developer Services",
    "general": "General",
    "governance_and_administration": "Governance & Administration",
    "identity_and_security": "Identity & Security",
    "migration": "Migration",
    "networking": "Networking",
    "observability_and_management": "Observability & Management",
    "storage": "Storage",
}

# Words that should not be plain title-cased when deriving descriptions.
WORD_MAP = {
    "ai": "AI", "adb": "ADB", "adw": "ADW", "atp": "ATP", "apex": "APEX", "api": "API",
    "apm": "APM", "bi": "BI", "byoip": "BYOIP", "cdn": "CDN", "cpe": "CPE", "cpq": "CPQ", "db": "DB",
    "ddos": "DDoS", "devops": "DevOps", "dns": "DNS", "drg": "DRG", "epm": "EPM",
    "erp": "ERP", "goldengate": "GoldenGate", "hcm": "HCM", "hp": "HP", "iam": "IAM",
    "ip": "IP", "jet": "JET", "mysql": "MySQL", "nat": "NAT", "nosql": "NoSQL",
    "nsg": "NSG", "oco": "OCO", "opensearch": "OpenSearch", "rac": "RAC", "vcn": "VCN",
    "vm": "VM", "vtap": "VTAP", "waf": "WAF", "and": "and", "for": "for", "of": "of",
    "d": "Dedicated",
}
PHRASE_MAP = {
    "Exadata C C": "Exadata Cloud@Customer",
    "E Business Suite": "E-Business Suite",
    "Back Up Restore": "Backup / Restore",
    "On Premises": "On-Premises",
    "Plug In": "Plug-In",
    "Non Stop": "NonStop",
}

# ---------------------------------------------------------------------------
# Semantic mapping guidance.  Every key mentioned in backticks that looks like
# an identifier (KEY_RE) is validated against the icon set at build time, so
# this section can never recommend a key that does not exist.
# ---------------------------------------------------------------------------
SEMANTIC_GUIDANCE: List[Tuple[str, List[Tuple[str, Optional[str], str]]]] = [
    ("Compute", [
        ("Compute instance (VM)", "vm",
         "Flex shape: `flex_vm`; burstable: `burstable_vm`; bare metal: `bare_metal`; "
         "instance pool: `instance_pools`; autoscaling: `autoscaling`."),
        ("Functions", "functions", ""),
        ("Container Engine for Kubernetes (OKE)", "oke",
         "Registry (OCIR): `container_registry`; generic container / pod: `container`; "
         "Service Mesh: `service_mesh`."),
        ("Container Instances", "container",
         "No dedicated glyph exists; the generic container icon is the closest key."),
    ]),
    ("Database", [
        ("Autonomous Database", "autonomous_db",
         "Workload-specific: `adw` / `atp`; dedicated infrastructure: `adb_d`, `adw_d`, `atp_d`."),
        ("MySQL HeatWave", "mysql", ""),
        ("NoSQL Database", "nosql", ""),
        ("OCI Cache (Redis / Valkey)", "nosql",
         "No dedicated OCI Cache glyph exists; `nosql` is the closest key (label it \"OCI Cache\")."),
        ("Base Database / DB System", "db_system",
         "RAC: `rac`; Exadata: `exadata`; Exadata Cloud@Customer: `exadata_cc`."),
        ("GoldenGate", "goldengate", "Generic database glyph: `generic_database`."),
        ("OpenSearch", "opensearch", ""),
        ("Data Safe", "data_safe", "Database Management: `database_management`."),
    ]),
    ("Storage", [
        ("Object Storage", "object_storage", "Individual buckets: `buckets`."),
        ("Block Volume", "block_storage", "Volume backups: `backup`; clones: `block_cloning`."),
        ("File Storage", "file_storage", ""),
        ("Local NVMe", "local_storage", ""),
    ]),
    ("Networking", [
        ("VCN", "vcn",
         "Draw the VCN itself as a container with `add_group(..., group_type=\"vcn\")`; use the "
         "icon only when a VCN must appear as a node (e.g. a peered remote VCN)."),
        ("Load Balancer", "load_balancer", "Flexible LB: `flexible_lb`."),
        ("Network Load Balancer (NLB)", "load_balancer",
         "No dedicated NLB glyph exists; reuse `load_balancer` and label it \"NLB\"."),
        ("Dynamic Routing Gateway (DRG)", "drg", ""),
        ("Internet Gateway", "internet_gateway", ""),
        ("NAT Gateway", "nat_gateway", ""),
        ("Service Gateway", "service_gateway", "Storage-flavoured variant: `storage_sgw`."),
        ("Local Peering Gateway (LPG)", "rpg",
         "No dedicated LPG glyph exists; the Remote Peering glyph `rpg` is the closest key (label it \"LPG\")."),
        ("Remote Peering Connection", "rpg", ""),
        ("Customer-Premises Equipment (CPE)", "cpe", "On-premises data centre: `data_center`."),
        ("Site-to-Site VPN", "cpe",
         "No dedicated site-to-site VPN glyph exists; draw `cpe` on the customer side connected to "
         "`drg` and label the edge \"IPSec VPN\"."),
        ("FastConnect", "backbone",
         "No dedicated FastConnect glyph exists; use `backbone` for the circuit, or connect `cpe` to "
         "`drg` and label the edge \"FastConnect\"."),
        ("DNS", "dns", ""),
        ("Route Table / Security List / NSG", "route_table", "`security_lists`, `nsg`."),
        ("WAF", "waf", "DDoS protection: `ddos`; Network Firewall: `firewall`."),
        ("Private Endpoint", "private_endpoint", ""),
        ("API Gateway", "api_gateway", ""),
    ]),
    ("Security & Identity", [
        ("Vault (secrets / keys)", "vault",
         "Key Management: `key_mgmt`; key vault: `key_vault`; Certificates: `certificates`; "
         "encryption at rest: `encryption`."),
        ("Bastion", "bastion", ""),
        ("Cloud Guard", "cloud_guard",
         "Security Zones: `max_security_zone`; Vulnerability Scanning: `vuln_scanning`; "
         "Threat Intelligence: `threat_intel`."),
        ("IAM / Identity Domain", "iam", "Generic identity: `identity`; federated AD: `active_directory`."),
        ("User / Group", "user", "Groups: `user_group`."),
        ("Policy", "policies", ""),
        ("Compartment", "compartments",
         "Prefer `add_group(..., group_type=\"compartment\")`; use the icon only when a compartment "
         "must appear as a node."),
        ("Tenancy", None,
         "No tenancy glyph exists; draw it as a container with `add_group(..., group_type=\"tenancy\")`. "
         "For multi-tenancy / organisations use `organization`."),
        ("Region / Availability Domain / Fault Domain", None,
         "No glyphs - always containers: `group_type=\"region\"`, `group_type=\"availability_domain\"`, "
         "`group_type=\"fault_domain\"`. Dedicated Region Cloud@Customer: `dedicated_region`."),
    ]),
    ("Observability & Messaging", [
        ("Logging", "logging",
         "Logging Analytics: `logging_analytics`; VCN Flow Logs: `flow_logs`; Audit: `auditing`."),
        ("Monitoring", "monitoring", "Alarms: `alarms`; Health Checks: `health_checks`."),
        ("APM", "apm", "Operations Insights: `ops_insights`."),
        ("Streaming", "streaming", ""),
        ("Queue", "queuing", ""),
        ("Events", "events", ""),
        ("Notifications", "notifications", "Email Delivery: `email`."),
        ("Service Connector Hub", "connector_hub", ""),
    ]),
    ("Analytics & AI", [
        ("Data Science", "data_science", "Machine learning: `ml`."),
        ("Generative AI / AI services", "ai",
         "No dedicated GenAI glyph exists; `ai` (Artificial Intelligence) is the closest key. "
         "Digital Assistant: `digital_assistant`."),
        ("Analytics Cloud (OAC)", "big_data",
         "No dedicated OAC glyph exists; `big_data` (used as OAC in the shipped examples) or the generic "
         "`analytics_and_ai_general` are the closest keys."),
        ("Big Data Service", "big_data", ""),
        ("Data Integration", "data_integration", "OIC application integration: `integrations`."),
        ("Data Catalog", "data_catalog", ""),
        ("Data Flow", "data_flow", ""),
    ]),
    ("Developer & Governance", [
        ("DevOps", "devops",
         "Resource Manager (Terraform): `resource_manager`; APEX: `apex`; Visual Builder: `visual_builder`."),
        ("Marketplace", "marketplace", ""),
        ("Tagging / Advisor / Licensing", "tagging", "`cloud_advisor`, `license_mgr`."),
    ]),
]


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
class Icon:
    __slots__ = ("stem", "category", "rel", "path")

    def __init__(self, path: Path, icon_dir: Path) -> None:
        self.path = path
        self.stem = path.stem
        self.category = path.parent.name
        self.rel = path.relative_to(icon_dir).as_posix()


def resolve_icon_dir() -> Path:
    env = os.environ.get("OCI_SVG_DIR")
    return Path(env).expanduser().resolve() if env else DEFAULT_ICON_DIR


def scan_icons(icon_dir: Path) -> List[Icon]:
    return sorted((Icon(p, icon_dir) for p in icon_dir.rglob("*.svg")), key=lambda i: (i.category, i.stem))


def validate_svg(icon: Icon) -> List[str]:
    problems: List[str] = []
    text = icon.path.read_text(encoding="utf-8")
    if PLACEHOLDER_RE.search(text):
        problems.append(f"{icon.rel}: contains the label-placeholder rectangle")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return problems + [f"{icon.rel}: XML parse error: {exc}"]
    if len(root) == 0 or not root.findall(f".//{SVG_NS}path"):
        problems.append(f"{icon.rel}: empty SVG (no drawable content)")
    vb = root.get("viewBox")
    try:
        parts = [float(v) for v in (vb or "").split()]
        if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
            raise ValueError
    except ValueError:
        problems.append(f"{icon.rel}: missing or non-positive viewBox ({vb!r})")
    return problems


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------
def load_aliases(aliases_path: Optional[Path]) -> Tuple[Dict[str, str], str]:
    """Prefer drawio_builder.ICON_ALIASES; fall back to the JSON file."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        import drawio_builder  # type: ignore

        aliases = getattr(drawio_builder, "ICON_ALIASES", None)
        if isinstance(aliases, dict) and aliases:
            return dict(aliases), "drawio_builder.ICON_ALIASES"
    except Exception as exc:  # pragma: no cover - import failures are a fallback path
        print(f"note: could not import drawio_builder ({exc}); falling back to --aliases", file=sys.stderr)
    if aliases_path is None:
        sys.exit("error: drawio_builder.ICON_ALIASES is unavailable; pass --aliases icon_aliases.json")
    with open(aliases_path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        sys.exit(f"error: {aliases_path} must contain a JSON object of alias -> 'category/file.svg'")
    return {str(k): str(v) for k, v in data.items()}, str(aliases_path)


def validate_aliases(aliases: Dict[str, str], icons: List[Icon]) -> List[str]:
    problems: List[str] = []
    by_rel = {i.rel: i for i in icons}
    by_stem = {i.stem: i for i in icons}
    for key, rel in sorted(aliases.items()):
        if not KEY_RE.match(key):
            problems.append(f"alias {key!r}: invalid key (must match {KEY_RE.pattern})")
        if rel not in by_rel:
            problems.append(f"alias {key!r} -> {rel}: file does not exist")
        elif key in by_stem and by_stem[key].rel != rel:
            problems.append(f"alias {key!r} -> {rel}: shadows filename stem {by_stem[key].rel}")
    return problems


def validate_guidance(resolvable: Dict[str, str]) -> List[str]:
    problems: List[str] = []
    for _, rows in SEMANTIC_GUIDANCE:
        for service, key, note in rows:
            mentioned = ([key] if key else []) + [
                tok for tok in re.findall(r"`([^`]+)`", note) if KEY_RE.match(tok)
            ]
            for tok in mentioned:
                if tok not in resolvable:
                    problems.append(f"guidance '{service}': key {tok!r} does not resolve to an icon")
    return problems


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def category_title(cat: str) -> str:
    return CATEGORY_TITLES.get(cat, cat.replace("_and_", " & ").replace("_", " ").title())


def describe(stem: str, category: str) -> str:
    words = stem[len(category) + 1:] if stem.startswith(category + "_") else stem
    text = " ".join(WORD_MAP.get(w, w.capitalize()) for w in words.split("_") if w)
    for old, new in PHRASE_MAP.items():
        text = text.replace(old, new)
    return text


def render(icons: List[Icon], aliases: Dict[str, str], alias_source: str, icon_dir: Path) -> str:
    by_rel = {i.rel: i for i in icons}
    categories = sorted({i.category for i in icons}, key=lambda c: (c == "general", c))
    aliases_for: Dict[str, List[str]] = {}
    for key, rel in sorted(aliases.items()):
        if key != by_rel[rel].stem:
            aliases_for.setdefault(rel, []).append(key)

    out: List[str] = []
    w = out.append
    w("# OCI SVG Icon Catalog")
    w("")
    w("<!-- Generated by scripts/build_icon_catalog.py - do not edit by hand. -->")
    w("")
    w(f"Icons bundled at: `${{CLAUDE_PLUGIN_ROOT}}/icons/` (override with the `OCI_SVG_DIR` env var).  ")
    w(f"**{len(icons)} icons** across **{len(categories)} categories**.")
    w("")
    w("## How icon keys work")
    w("")
    w("- **Every icon is usable by its filename stem, with no registration.** The key is the SVG file name "
      "without `.svg`, e.g. `add_icon(\"DB\", \"database_mysql\", ...)` or `add_icon(\"App\", "
      "\"compute_virtual_machine_vm\", ...)`. All stems are listed in the per-category tables below.")
    w(f"- **Short aliases** (`vm`, `drg`, `oke`, ...) are convenience keys defined in `{alias_source}` "
      "and listed in the next section. An alias and its stem are interchangeable.")
    w("- Both key forms match `^[a-z][a-z0-9_]*$`. Unknown keys raise an error with close-match suggestions; "
      "`add_icons_to_map({\"key\": \"category/file.svg\"})` still works for custom icons.")
    w("- Every viewBox hugs its glyph (1 unit padding), so icons render at a consistent visual size; "
      "`add_icon()` derives the cell width from each icon's native aspect ratio.")
    w("")
    w("---")
    w("")
    w(f"## Short aliases ({len(aliases)})")
    w("")
    w("| Alias | SVG Path | Description |")
    w("|-------|----------|-------------|")
    for key, rel in sorted(aliases.items()):
        icon = by_rel[rel]
        w(f"| `{key}` | `{rel}` | {describe(icon.stem, icon.category)} |")
    w("")
    w("---")
    w("")
    w("## Full icon inventory by category")
    w("")
    w("The **Key** column is the filename stem and always works. The **Aliases** column lists any short "
      "aliases that point at the same file.")
    w("")
    for cat in categories:
        cat_icons = [i for i in icons if i.category == cat]
        w(f"### {category_title(cat)} ({len(cat_icons)} icons)")
        w("")
        w("| Key (filename stem) | SVG Path | Description | Aliases |")
        w("|---------------------|----------|-------------|---------|")
        for icon in cat_icons:
            al = ", ".join(f"`{a}`" for a in aliases_for.get(icon.rel, [])) or "-"
            w(f"| `{icon.stem}` | `{icon.rel}` | {describe(icon.stem, icon.category)} | {al} |")
        w("")
    w("---")
    w("")
    w("## Semantic mapping guidance")
    w("")
    w("Recommended keys for common OCI services. Where OCI has no dedicated glyph in this icon set the "
      "closest key is given explicitly - do not invent keys. Containers (region, tenancy, AD, FD, "
      "compartment, VCN, subnet) are drawn with `add_group(...)`, not icons.")
    w("")
    for group, rows in SEMANTIC_GUIDANCE:
        w(f"### {group}")
        w("")
        w("| Service | Recommended key | Notes |")
        w("|---------|-----------------|-------|")
        for service, key, note in rows:
            k = f"`{key}`" if key else "*(container)*"
            w(f"| {service} | {k} | {note or '-'} |")
        w("")
    templates = sorted(TEMPLATES_DIR.glob("*.svg")) if TEMPLATES_DIR.is_dir() else []
    if templates:
        w("---")
        w("")
        w("## Not icons: composite reference drawings")
        w("")
        w(f"`references/templates/` holds {len(templates)} large composite example drawings from the OCI "
          "icon set (`" + "`, `".join(t.name for t in templates) + "`). They are layout references "
          "only and are not valid `add_icon()` keys.")
        w("")
    w(f"Regenerate this file with `python3 scripts/build_icon_catalog.py` (validate with `--check`).")
    w("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate only; exit 1 on any problem")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output markdown path (default: {DEFAULT_OUT})")
    ap.add_argument("--aliases", type=Path, default=None,
                    help="alias JSON used when drawio_builder.ICON_ALIASES is unavailable")
    args = ap.parse_args(argv)

    icon_dir = resolve_icon_dir()
    if not icon_dir.is_dir():
        sys.exit(f"error: icon directory not found: {icon_dir}")
    icons = scan_icons(icon_dir)
    if not icons:
        sys.exit(f"error: no SVG files under {icon_dir}")

    aliases, alias_source = load_aliases(args.aliases)

    problems: List[str] = []
    for icon in icons:
        problems += validate_svg(icon)
    problems += validate_aliases(aliases, icons)
    resolvable = {i.stem: i.rel for i in icons}
    resolvable.update({k: v for k, v in aliases.items() if k not in resolvable})
    problems += validate_guidance(resolvable)

    cats = sorted({i.category for i in icons})
    print(f"icons: {len(icons)} in {len(cats)} categories under {icon_dir}")
    print(f"aliases: {len(aliases)} from {alias_source}")
    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    if args.check:
        print("check: OK")
        return 0

    text = render(icons, aliases, alias_source, icon_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
