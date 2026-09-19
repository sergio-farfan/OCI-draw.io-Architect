#!/usr/bin/env python3
"""Auto-detect OCI diagram settings from Terraform configs, OCI config and OCI CLI.

Probe order and sources
-----------------------
1. Terraform directory discovery (unless a path is given on the command line):
   walk downward from the current directory, pruning ``.terraform``, ``.git``,
   ``node_modules``, ``.venv``, ``venv`` and ``__pycache__``; pick the shallowest
   directory whose ``*.tf`` files declare a ``provider "oci" {}`` block, else the
   shallowest directory holding ``*.tfvars`` / ``*.tfvars.json``.  Ties at the same
   depth are ordered lexically; every tied candidate is reported in
   ``terraform_dirs`` and the first one is used.

2. Terraform files in that directory (every ``*.tf``, comments stripped):
   - the non-aliased ``provider "oci"`` block supplies ``region``,
     ``config_file_profile`` (-> ``oci_profile``), ``tenancy_ocid`` and ``auth``;
     ``terraform {}`` / ``backend {}`` blocks and non-OCI providers are ignored.
   - ``var.NAME`` / ``local.NAME`` references are resolved against
     ``terraform.tfvars``, ``terraform.tfvars.json`` and ``*.auto.tfvars[.json]``
     (lexical order, later wins), then the ``default`` of ``variable "NAME" {}``
     (brace-matched, any formatting), then any other ``*.tfvars`` as a last resort.
   - ``tenancy_ocid`` must match ``^ocid1.tenancy.``; ``compartment_ocid`` /
     ``compartment_id`` are read the same way.
   - ``resource "oci_core_vcn"`` / ``resource "oci_identity_compartment"`` blocks
     and the loose tfvars pattern ``vcns = { ... display_name = "..." cidr = ... }``
     populate ``vcns`` and ``compartments``.

3. ``~/.oci/config`` (or ``$OCI_CLI_CONFIG_FILE``): the profile named by Terraform,
   ``$OCI_CLI_PROFILE`` or ``DEFAULT``; keys inherit from ``[DEFAULT]``.  Supplies a
   fallback ``region``, the auth identity ``auth_tenancy_ocid`` and
   ``oci_auth: security_token`` when ``security_token_file`` is set.

4. OCI CLI (only when ``oci`` is on PATH): ``oci iam tenancy get`` for
   ``tenancy_name`` and ``oci iam region-subscription list`` for
   ``subscribed_regions`` / ``home_region``.  Each call is bounded by an 8 s
   timeout; failures are surfaced as a one-line ``cli_warning`` on stderr.

5. Logo scan: ``logos/``, ``assets/logos/``, ``assets/images/``, ``docs/logos/``
   (project-relative paths), then the optional plugin-local ``logos/`` directory
   (absolute paths).  Files named ``*dark*``/``*black*`` become ``logo_light`` (a dark
   logo for light backgrounds); ``*white*``/``*light*`` become ``logo_dark``.

The probe never detects a VIEW choice. ``purpose`` (v1.5.0, ANSWERED_KEYS) is the one view key the
settings file carries: the command's Step 1 asks it and writes it back, and this module only gives
it a stable position in the frontmatter.

Output: a YAML frontmatter block on stdout suitable for
``.claude/oci-drawio-architect.local.md``; a human summary goes to stderr.

Usage:
    python3 detect_settings.py [-h] [--no-cli] [terraform_dir]

Exit codes: 0 success, 1 nothing useful detected, 2 terraform_dir does not exist.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_DIRS = frozenset({
    ".terraform", ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".terragrunt-cache", ".idea", ".vscode",
})
MAX_WALK_DEPTH = 12
CLI_TIMEOUT = 8.0

REGION_ID_RE = re.compile(r"^[a-z]{2}-[a-z]+(?:-[a-z]+)*-\d+$")
TENANCY_OCID_RE = re.compile(r"^ocid1\.tenancy\.")
COMPARTMENT_OCID_RE = re.compile(r"^ocid1\.(?:compartment|tenancy)\.")
CIDR_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\b")

LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg", ".svg")

# ---------------------------------------------------------------------------
# Region display names
# ---------------------------------------------------------------------------

REGION_LABELS: Dict[str, str] = {
    # Africa
    "af-casablanca-1": "Casablanca",
    "af-johannesburg-1": "Johannesburg",
    # Asia Pacific
    "ap-batam-1": "Batam",
    "ap-chuncheon-1": "Chuncheon",
    "ap-hyderabad-1": "Hyderabad",
    "ap-kulai-2": "Kulai",
    "ap-melbourne-1": "Melbourne",
    "ap-mumbai-1": "Mumbai",
    "ap-osaka-1": "Osaka",
    "ap-seoul-1": "Seoul",
    "ap-singapore-1": "Singapore",
    "ap-singapore-2": "Singapore West",
    "ap-sydney-1": "Sydney",
    "ap-tokyo-1": "Tokyo",
    # Canada
    "ca-montreal-1": "Montreal",
    "ca-toronto-1": "Toronto",
    # Europe
    "eu-amsterdam-1": "Amsterdam",
    "eu-frankfurt-1": "Frankfurt",
    "eu-frankfurt-2": "Frankfurt 2",
    "eu-jovanovac-1": "Jovanovac",
    "eu-madrid-1": "Madrid",
    "eu-madrid-2": "Madrid 2",
    "eu-madrid-3": "Madrid 3",
    "eu-marseille-1": "Marseille",
    "eu-milan-1": "Milan",
    "eu-paris-1": "Paris",
    "eu-stockholm-1": "Stockholm",
    "eu-turin-1": "Turin",
    "eu-zurich-1": "Zurich",
    # Israel / Middle East
    "il-jerusalem-1": "Jerusalem",
    "me-abudhabi-1": "Abu Dhabi",
    "me-dubai-1": "Dubai",
    "me-jeddah-1": "Jeddah",
    "me-riyadh-1": "Riyadh",
    # Latin America
    "mx-monterrey-1": "Monterrey",
    "mx-queretaro-1": "Queretaro",
    "sa-bogota-1": "Bogota",
    "sa-santiago-1": "Santiago",
    "sa-saopaulo-1": "Sao Paulo",
    "sa-valparaiso-1": "Valparaiso",
    "sa-vinhedo-1": "Vinhedo",
    # United Kingdom
    "uk-cardiff-1": "Newport",
    "uk-london-1": "London",
    # United States
    "us-ashburn-1": "Ashburn",
    "us-chicago-1": "Chicago",
    "us-phoenix-1": "Phoenix",
    "us-saltlake-2": "Salt Lake City",
    "us-sanjose-1": "San Jose",
    # Government realms (commonly seen in tenancies alongside commercial regions)
    "us-langley-1": "Langley",
    "us-luke-1": "Luke",
    "us-gov-ashburn-1": "Ashburn (Gov)",
    "us-gov-chicago-1": "Chicago (Gov)",
    "us-gov-phoenix-1": "Phoenix (Gov)",
    "uk-gov-london-1": "London (Gov)",
    "uk-gov-cardiff-1": "Newport (Gov)",
}

# City tokens that are compound words in the region identifier.
_CITY_OVERRIDES: Dict[str, str] = {
    "abudhabi": "Abu Dhabi",
    "buenosaires": "Buenos Aires",
    "capetown": "Cape Town",
    "hongkong": "Hong Kong",
    "kualalumpur": "Kuala Lumpur",
    "losangeles": "Los Angeles",
    "mexicocity": "Mexico City",
    "newyork": "New York",
    "saltlake": "Salt Lake",
    "sanjose": "San Jose",
    "saopaulo": "Sao Paulo",
    "telaviv": "Tel Aviv",
}


def _derive_region_label(region: str) -> str:
    """Derive a human label from a region identifier without consulting the table.

    ``eu-madrid-2`` -> ``Madrid 2``, ``me-abudhabi-1`` -> ``Abu Dhabi``,
    ``us-gov-ashburn-1`` -> ``Gov Ashburn``.  Anything that does not look like an
    OCI region identifier is title-cased with separators turned into spaces.
    """
    ident = (region or "").strip().lower()
    m = re.match(r"^[a-z]{2}-([a-z]+(?:-[a-z]+)*)-(\d+)$", ident)
    if not m:
        words = [w for w in re.split(r"[-_\s]+", ident) if w]
        return " ".join(w.capitalize() for w in words) or "Region"
    city_tokens, number = m.group(1).split("-"), int(m.group(2))
    city = " ".join(_CITY_OVERRIDES.get(tok, tok.capitalize()) for tok in city_tokens)
    return f"{city} {number}" if number != 1 else city


def region_display_label(region: str) -> str:
    """Return the display label for ``region`` (table lookup, derived fallback)."""
    if not region:
        return ""
    key = region.strip().lower()
    return REGION_LABELS.get(key) or _derive_region_label(key)


# ---------------------------------------------------------------------------
# HCL scanning helpers (string / template / heredoc aware, no external deps)
# ---------------------------------------------------------------------------

_HEREDOC_RE = re.compile(r"<<-?[ \t]*([A-Za-z_][A-Za-z0-9_-]*)[ \t]*\r?\n")


def _skip_string(text: str, i: int) -> int:
    """``i`` is at an opening quote; return the index just past the closing quote."""
    n = len(text)
    i += 1
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        if c in "$%" and text.startswith("{", i + 1):
            i = _skip_template(text, i + 2)
            continue
        i += 1
    return n


def _skip_template(text: str, i: int) -> int:
    """``i`` is just past ``${`` / ``%{``; return the index past the matching ``}``."""
    depth, n = 1, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _skip_heredoc(text: str, i: int) -> Optional[int]:
    """If a heredoc starts at ``i``, return the index past its terminator line."""
    m = _HEREDOC_RE.match(text, i)
    if not m:
        return None
    marker = re.escape(m.group(1))
    end = re.compile(r"^[ \t]*" + marker + r"[ \t]*$", re.MULTILINE).search(text, m.end())
    if not end:
        return len(text)
    nl = text.find("\n", end.end())
    return len(text) if nl == -1 else nl + 1


def strip_hcl_comments(text: str) -> str:
    """Remove ``#``, ``//`` and ``/* */`` comments, preserving strings, heredocs and newlines."""
    out: List[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = _skip_string(text, i)
            out.append(text[i:j])
            i = j
            continue
        if c == "<":
            j = _skip_heredoc(text, i)
            if j is not None:
                out.append(text[i:j])
                i = j
                continue
        if c == "#" or text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("\n" * text.count("\n", i, j))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _find_block_end(text: str, open_idx: int) -> int:
    """``open_idx`` is at ``{``; return the index just past the matching ``}`` (or -1)."""
    depth, i, n = 0, open_idx, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c == "<":
            j = _skip_heredoc(text, i)
            if j is not None:
                i = j
                continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


_BLOCK_HEADER_RE = re.compile(r'[ \t]*([A-Za-z_][\w-]*)((?:[ \t]+"[^"\n]*")*)[ \t]*\{')


def iter_top_level_blocks(text: str) -> Iterator[Tuple[str, List[str], str]]:
    """Yield ``(kind, labels, body)`` for each top-level block in comment-stripped HCL.

    Brace matching is real (string-aware), so one-line blocks, indented closing
    braces and nested blocks are all handled.
    """
    pos, n = 0, len(text)
    while pos < n:
        m = _BLOCK_HEADER_RE.match(text, pos)
        if m:
            open_idx = m.end() - 1
            end = _find_block_end(text, open_idx)
            body = text[open_idx + 1:] if end == -1 else text[open_idx + 1:end - 1]
            labels = re.findall(r'"([^"\n]*)"', m.group(2))
            yield m.group(1), labels, body
            pos = n if end == -1 else end
        nl = text.find("\n", pos)
        pos = n if nl == -1 else nl + 1


def _split_statements(body: str) -> List[str]:
    """Split a block body into depth-0 statements (multi-line values stay whole)."""
    stmts: List[str] = []
    depth, start, i, n = 0, 0, 0, len(body)
    while i < n:
        c = body[i]
        if c == '"':
            i = _skip_string(body, i)
            continue
        if c == "<":
            j = _skip_heredoc(body, i)
            if j is not None:
                i = j
                continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth = max(0, depth - 1)
        elif c == "\n" and depth == 0:
            stmts.append(body[start:i])
            start = i + 1
        i += 1
    stmts.append(body[start:])
    return [s.strip() for s in stmts if s.strip()]


_ATTR_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*=(?!=)\s*(.*)$", re.DOTALL)


def top_level_attrs(body: str) -> Dict[str, str]:
    """Return ``{name: raw_value}`` for depth-0 ``name = value`` assignments in ``body``."""
    attrs: Dict[str, str] = {}
    for stmt in _split_statements(body):
        m = _ATTR_RE.match(stmt)
        if m:
            attrs[m.group(1)] = m.group(2).strip().rstrip(",")
    return attrs


_REF_RE = re.compile(r"^(var|local)\.([\w-]+)$")
_TEMPLATE_REF_RE = re.compile(r"^\$\{\s*(var|local)\.([\w-]+)\s*\}$")


def _parse_value(raw: str):
    """Classify a raw HCL value: ('lit', str), ('ref', kind, name) or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith('"'):
        end = _skip_string(raw, 0)
        inner = raw[1:end - 1]
        if "${" in inner:
            m = _TEMPLATE_REF_RE.match(inner.strip())
            return ("ref", m.group(1), m.group(2)) if m else None
        return ("lit", inner.replace('\\"', '"').replace("\\\\", "\\"))
    m = _REF_RE.match(raw)
    if m:
        return ("ref", m.group(1), m.group(2))
    if re.fullmatch(r"-?\d+(?:\.\d+)?|true|false|null", raw):
        return ("lit", raw)
    return None


def _to_hcl_raw(value) -> str:
    """Render a JSON-decoded tfvars value as HCL-like raw text (JSON is valid enough)."""
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, indent=2)


# ---------------------------------------------------------------------------
# Terraform context: files, variables, providers, resources
# ---------------------------------------------------------------------------

class TerraformContext:
    """Comment-stripped view of one Terraform directory with variable resolution."""

    def __init__(self, tf_dir: Path):
        self.tf_dir = Path(tf_dir)
        self.tf_texts: Dict[str, str] = {}
        self.var_defaults: Dict[str, str] = {}
        self.locals: Dict[str, str] = {}
        self.tfvars: Dict[str, str] = {}          # auto-loaded (later wins)
        self.extra_tfvars: Dict[str, str] = {}    # other *.tfvars (first wins)
        self.providers: List[Dict[str, str]] = []  # provider "oci" blocks
        self.resources: List[Tuple[str, str, Dict[str, str]]] = []
        self._load()

    # -- loading -----------------------------------------------------------
    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _load(self) -> None:
        if not self.tf_dir.is_dir():
            return
        for tf in sorted(self.tf_dir.glob("*.tf")):
            text = strip_hcl_comments(self._read(tf))
            self.tf_texts[tf.name] = text
            for kind, labels, body in iter_top_level_blocks(text):
                if kind == "variable" and labels:
                    attrs = top_level_attrs(body)
                    if "default" in attrs:
                        self.var_defaults.setdefault(labels[0], attrs["default"])
                elif kind == "locals":
                    for k, v in top_level_attrs(body).items():
                        self.locals.setdefault(k, v)
                elif kind == "provider" and labels and labels[0] == "oci":
                    self.providers.append(top_level_attrs(body))
                elif kind == "resource" and len(labels) >= 2:
                    self.resources.append((labels[0], labels[1], top_level_attrs(body)))

        auto_files: List[Path] = []
        for name in ("terraform.tfvars", "terraform.tfvars.json"):
            if (self.tf_dir / name).is_file():
                auto_files.append(self.tf_dir / name)
        auto_files += sorted(
            list(self.tf_dir.glob("*.auto.tfvars")) + list(self.tf_dir.glob("*.auto.tfvars.json")),
            key=lambda p: p.name,
        )
        for f in auto_files:
            self.tfvars.update(self._parse_tfvars(f))

        auto_names = {f.name for f in auto_files}
        others = sorted(
            [p for p in list(self.tf_dir.glob("*.tfvars")) + list(self.tf_dir.glob("*.tfvars.json"))
             if p.name not in auto_names],
            key=lambda p: p.name,
        )
        for f in others:
            for k, v in self._parse_tfvars(f).items():
                self.extra_tfvars.setdefault(k, v)

    def _parse_tfvars(self, path: Path) -> Dict[str, str]:
        text = self._read(path)
        if path.suffix == ".json":
            try:
                data = json.loads(text)
            except ValueError:
                return {}
            return {k: _to_hcl_raw(v) for k, v in data.items()} if isinstance(data, dict) else {}
        return top_level_attrs(strip_hcl_comments(text))

    # -- resolution --------------------------------------------------------
    def var_raw(self, name: str) -> Optional[str]:
        if name in self.tfvars:
            return self.tfvars[name]
        if name in self.var_defaults:
            return self.var_defaults[name]
        return self.extra_tfvars.get(name)

    def resolve_raw(self, raw: Optional[str], _depth: int = 0) -> Optional[str]:
        """Follow ``var.X`` / ``local.X`` references and return the final raw value."""
        if raw is None or _depth > 8:
            return None
        parsed = _parse_value(raw)
        if parsed is None:
            return raw.strip() if raw.strip()[:1] in "{[" else None
        if parsed[0] == "lit":
            return raw.strip()
        kind, name = parsed[1], parsed[2]
        target = self.var_raw(name) if kind == "var" else self.locals.get(name)
        return self.resolve_raw(target, _depth + 1) if target is not None else None

    def resolve(self, raw: Optional[str]) -> Optional[str]:
        """Resolve ``raw`` to a scalar string, or None when it is not a literal."""
        final = self.resolve_raw(raw)
        if final is None:
            return None
        parsed = _parse_value(final)
        return parsed[1] if parsed and parsed[0] == "lit" else None

    def var_value(self, name: str) -> Optional[str]:
        return self.resolve(self.var_raw(name))

    # -- derived facts -----------------------------------------------------
    def primary_provider(self) -> Optional[Dict[str, str]]:
        """The ``provider "oci"`` block without ``alias`` (first aliased one as fallback)."""
        unaliased = [p for p in self.providers if "alias" not in p]
        if unaliased:
            return unaliased[0]
        return self.providers[0] if self.providers else None

    def provider_settings(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        prov = self.primary_provider() or {}

        # Provider attribute first, then a same-named variable (tfvars / default).
        region = self.resolve(prov.get("region")) or self.var_value("region")
        if region and REGION_ID_RE.match(region.strip().lower()):
            out["region"] = region.strip().lower()

        profile = self.resolve(prov.get("config_file_profile")) or self.var_value("config_file_profile")
        if profile:
            out["oci_profile"] = profile.strip()

        tenancy = self.resolve(prov.get("tenancy_ocid"))
        if not (tenancy and TENANCY_OCID_RE.match(tenancy.strip())):
            tenancy = self.var_value("tenancy_ocid")
        if tenancy and TENANCY_OCID_RE.match(tenancy.strip()):
            out["tenancy_ocid"] = tenancy.strip()

        for var_name in ("compartment_ocid", "compartment_id"):
            comp = self.var_value(var_name)
            if comp and COMPARTMENT_OCID_RE.match(comp.strip()):
                out["compartment_ocid"] = comp.strip()
                break

        auth = self.resolve(prov.get("auth")) if "auth" in prov else None
        if auth:
            out["oci_auth"] = _normalise_auth(auth)
        return out

    def vcns(self) -> List[Dict[str, Optional[str]]]:
        found: List[Dict[str, Optional[str]]] = []
        for rtype, label, attrs in self.resources:
            if rtype != "oci_core_vcn":
                continue
            name = self.resolve(attrs.get("display_name"))
            cidr = None
            for key in ("cidr_block", "cidr_blocks"):
                if key in attrs:
                    final = self.resolve_raw(attrs[key])
                    m = CIDR_RE.search(final or "")
                    if m:
                        cidr = m.group(1)
                        break
            if name is None and cidr is None:
                continue
            found.append({"name": name or label, "cidr": cidr})

        for attrs in (self.tfvars, self.extra_tfvars, self.var_defaults):
            for key in sorted(attrs):
                if "vcn" in key.lower() and (attrs[key] or "").lstrip()[:1] in "{[":
                    found.extend(loose_vcn_entries(attrs[key]))

        unique: List[Dict[str, Optional[str]]] = []
        seen = set()
        for v in found:
            marker = (v["name"] or "", v["cidr"] or "")
            if marker not in seen:
                seen.add(marker)
                unique.append(v)
        return unique

    def compartments(self) -> List[str]:
        names: List[str] = []
        for rtype, _label, attrs in self.resources:
            if rtype == "oci_identity_compartment":
                name = self.resolve(attrs.get("name"))
                if name and name not in names:
                    names.append(name)
        return names


_AUTH_MAP = {
    "apikey": "api_key",
    "securitytoken": "security_token",
    "instanceprincipal": "instance_principal",
    "resourceprincipal": "resource_principal",
    "okeworkloadidentity": "oke_workload_identity",
}


def _normalise_auth(value: str) -> str:
    key = re.sub(r"[^a-z]", "", value.lower())
    return _AUTH_MAP.get(key, value.strip().lower())


_LOOSE_NAME_RE = re.compile(r'(?<![\w-])"?(?:display_name|vcn_name|name)"?\s*[=:]\s*"([^"\n]+)"')
_LOOSE_CIDR_RE = re.compile(
    r'(?<![\w-])"?(?:vcn_cidr_blocks?|vcn_cidrs?|cidr_blocks?|cidrs?)"?\s*[=:]\s*\[?\s*'
    r'"(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})"'
)


def loose_vcn_entries(raw: str) -> List[Dict[str, Optional[str]]]:
    """Loosely extract ``{name, cidr}`` pairs from a ``vcns = { ... }`` style value."""
    inner = (raw or "").strip()
    if inner[:1] in "{[" and inner[-1:] in "}]":
        inner = inner[1:-1]
    stmts = [s for s in _split_statements(inner) if _LOOSE_NAME_RE.search(s)]
    entries: List[Dict[str, Optional[str]]] = []
    for stmt in stmts or [inner]:
        nm = _LOOSE_NAME_RE.search(stmt)
        if not nm:
            continue
        cm = _LOOSE_CIDR_RE.search(stmt)
        entries.append({"name": nm.group(1), "cidr": cm.group(1) if cm else None})
    return entries


# ---------------------------------------------------------------------------
# Terraform directory discovery
# ---------------------------------------------------------------------------

_PROVIDER_OCI_RE = re.compile(r'(?m)^[ \t]*provider[ \t]+"oci"[ \t]*\{')


def _has_oci_provider(tf_file: Path) -> bool:
    try:
        text = tf_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_PROVIDER_OCI_RE.search(strip_hcl_comments(text)))


def find_terraform_dirs(root: Optional[Path] = None) -> List[Path]:
    """Return all candidate Terraform dirs at the shallowest matching depth (sorted).

    Preference: directories with a ``provider "oci"`` block, then directories with
    ``*.tfvars`` / ``*.tfvars.json``.  Ignored directories are pruned during the walk.
    """
    root = Path(root or Path.cwd())
    provider_hits: List[Tuple[int, str]] = []
    tfvars_hits: List[Tuple[int, str]] = []
    best_depth: Optional[int] = None  # shallowest provider hit so far
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if best_depth is not None and depth > best_depth:
            dirnames[:] = []  # nothing deeper can beat an existing provider hit
            continue
        if depth >= MAX_WALK_DEPTH:
            dirnames[:] = []
        tf_files = sorted(f for f in filenames if f.endswith(".tf"))
        if any(_has_oci_provider(Path(dirpath) / f) for f in tf_files):
            provider_hits.append((depth, dirpath))
            best_depth = depth if best_depth is None else min(best_depth, depth)
        elif any(f.endswith((".tfvars", ".tfvars.json")) for f in filenames):
            tfvars_hits.append((depth, dirpath))

    hits = provider_hits or tfvars_hits
    if not hits:
        return []
    best = min(d for d, _ in hits)
    return [Path(p) for d, p in sorted(hits) if d == best]


def find_terraform_dir(root: Optional[Path] = None) -> Optional[Path]:
    """Shallowest Terraform directory below ``root`` (first candidate), or None."""
    dirs = find_terraform_dirs(root)
    return dirs[0] if dirs else None


# ---------------------------------------------------------------------------
# OCI config (~/.oci/config)
# ---------------------------------------------------------------------------

def _oci_config_path(config_path: Optional[str] = None) -> Path:
    raw = config_path or os.environ.get("OCI_CLI_CONFIG_FILE") or str(Path.home() / ".oci" / "config")
    return Path(raw).expanduser()


def parse_oci_config(profile: str = "DEFAULT", config_path: Optional[str] = None) -> dict:
    """Extract tenancy OCID, region and auth mode for ``profile`` from the OCI config.

    Named profiles inherit keys from ``[DEFAULT]``; keys are case-insensitive and
    inline ``#`` / ``;`` comments are stripped.  ``security_token_file`` marks the
    profile as session-token based (``oci_auth: security_token``).
    """
    path = _oci_config_path(config_path)
    if not path.is_file():
        return {}
    parser = configparser.RawConfigParser(
        strict=False, allow_no_value=True, inline_comment_prefixes=("#", ";"),
    )
    parser.optionxform = str.lower  # type: ignore[assignment]
    try:
        parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
    except configparser.Error:
        return {}

    wanted = (profile or "DEFAULT").strip()
    section: Optional[str] = None
    if parser.has_section(wanted):
        section = wanted
    else:
        for s in parser.sections():
            if s.lower() == wanted.lower():
                section = s
                break
    if section is None:
        if wanted.upper() != parser.default_section.upper():
            return {}
        section = parser.default_section

    items = {k.lower(): (v or "").strip() for k, v in parser.items(section)}
    result: Dict[str, str] = {}
    tenancy = items.get("tenancy", "")
    if TENANCY_OCID_RE.match(tenancy):
        result["tenancy_ocid"] = tenancy
    region = items.get("region", "").lower()
    if REGION_ID_RE.match(region):
        result["region"] = region
    if items.get("security_token_file"):
        result["oci_auth"] = "security_token"
    return result


# ---------------------------------------------------------------------------
# OCI CLI
# ---------------------------------------------------------------------------

def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _run_oci(args: List[str], timeout: float) -> Tuple[Optional[dict], str]:
    """Run an ``oci`` command; return ``(parsed_json, warning)``."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"oci {' '.join(args[1:3])} timed out after {timeout:g}s"
    except (FileNotFoundError, OSError) as exc:
        return None, f"oci could not be executed: {exc}"
    if proc.returncode != 0:
        return None, _first_line(proc.stderr) or f"oci exited with status {proc.returncode}"
    try:
        data = json.loads(proc.stdout or "")
    except ValueError:
        return None, "oci returned non-JSON output"
    return (data if isinstance(data, dict) else None), ("" if isinstance(data, dict) else "unexpected oci output")


def query_oci_cli(tenancy_ocid: str, profile: str = "DEFAULT", auth: Optional[str] = None,
                  timeout: float = CLI_TIMEOUT) -> dict:
    """Query the OCI CLI for tenancy name and subscribed regions.

    Runs only when ``oci`` is on PATH.  Adds ``--auth security_token`` for
    session-token profiles.  Each call is bounded by ``timeout`` seconds; on
    failure the first stderr line is returned as ``cli_warning``.
    """
    result: Dict[str, object] = {}
    if not tenancy_ocid:
        return result
    if shutil.which("oci") is None:
        result["cli_warning"] = "oci CLI not found on PATH; tenancy name not resolved"
        return result

    common = ["--tenancy-id", tenancy_ocid, "--profile", profile or "DEFAULT"]
    if auth == "security_token":
        common += ["--auth", "security_token"]

    print(f"Querying OCI CLI (profile {profile or 'DEFAULT'})...", file=sys.stderr, flush=True)
    data, warning = _run_oci(["oci", "iam", "tenancy", "get"] + common, timeout)
    payload = data.get("data") if data else None
    name = payload.get("name") if isinstance(payload, dict) else None
    if not name:
        result["cli_warning"] = warning or "oci iam tenancy get returned no tenancy name"
        return result
    result["tenancy_name"] = str(name)

    data, warning = _run_oci(["oci", "iam", "region-subscription", "list"] + common, timeout)
    subs = (data or {}).get("data") if data else None
    if isinstance(subs, list):
        regions = [r.get("region-name") for r in subs if isinstance(r, dict) and r.get("region-name")]
        if regions:
            result["subscribed_regions"] = regions
        for r in subs:
            if isinstance(r, dict) and r.get("is-home-region") and r.get("region-name"):
                result["home_region"] = r["region-name"]
                break
    elif warning:
        result["cli_warning"] = warning
    return result


# ---------------------------------------------------------------------------
# Logos
# ---------------------------------------------------------------------------

def _classify_logo(name_lower: str) -> Optional[str]:
    """Dark/black artwork is for light backgrounds; white/light artwork is for dark ones."""
    if "dark" in name_lower or "black" in name_lower:
        return "logo_light"
    if "white" in name_lower or "light" in name_lower:
        return "logo_dark"
    return None


def find_logos(project_dir: Path, plugin_logos_dir: Optional[Path] = None) -> dict:
    """Find logo files in common project locations, then the plugin-local ``logos/``.

    Project paths are returned relative to ``project_dir`` (portable settings);
    plugin-local paths are absolute.  Earlier directories win.
    """
    project_dir = Path(project_dir)
    if plugin_logos_dir is None:
        plugin_logos_dir = Path(__file__).resolve().parent.parent / "logos"
    search: List[Tuple[Path, bool]] = [
        (project_dir / "logos", True),
        (project_dir / "assets" / "logos", True),
        (project_dir / "assets" / "images", True),
        (project_dir / "docs" / "logos", True),
        (Path(plugin_logos_dir), False),
    ]
    result: Dict[str, str] = {}
    for logos_dir, is_project in search:
        if not logos_dir.is_dir():
            continue
        is_logos_dir = logos_dir.name.lower() == "logos"
        files = sorted(
            (f for f in logos_dir.iterdir() if f.is_file() and f.suffix.lower() in LOGO_EXTENSIONS),
            key=lambda p: p.name.lower(),
        )

        def _display(f: Path) -> str:
            if is_project:
                return Path(os.path.relpath(f, project_dir)).as_posix()
            return str(f.resolve())

        generic: List[Path] = []
        for f in files:
            name_lower = f.name.lower()
            has_logo_word = "logo" in name_lower
            if not is_logos_dir and not has_logo_word:
                continue
            key = _classify_logo(name_lower)
            if key:
                result.setdefault(key, _display(f))
            elif has_logo_word:
                generic.append(f)
        for f in generic:
            result.setdefault("logo_light", _display(f))
    return result


# ---------------------------------------------------------------------------
# Detection pipeline
# ---------------------------------------------------------------------------

def _display_path(path: Path, project_dir: Path) -> str:
    try:
        rel = path.resolve().relative_to(project_dir.resolve())
    except ValueError:
        return str(path)
    return rel.as_posix() or "."


def detect(tf_dir_arg: Optional[str] = None, project_dir: Optional[Path] = None,
           query_cli: bool = True) -> dict:
    """Run the full detection pipeline and return the merged settings dict."""
    settings: Dict[str, object] = {}
    project_dir = Path(project_dir or Path.cwd())

    # 1. Terraform directory
    tf_dir: Optional[Path] = None
    if tf_dir_arg:
        candidate = Path(tf_dir_arg).expanduser()
        tf_dir = candidate.resolve() if candidate.is_dir() else None
    else:
        candidates = find_terraform_dirs(project_dir)
        if candidates:
            tf_dir = candidates[0]
            if len(candidates) > 1:
                settings["terraform_dirs"] = [_display_path(c, project_dir) for c in candidates]

    # 2. Terraform files
    if tf_dir is not None:
        ctx = TerraformContext(tf_dir)
        settings.update(ctx.provider_settings())
        vcns = ctx.vcns()
        if vcns:
            settings["vcns"] = vcns
        compartments = ctx.compartments()
        if compartments:
            settings["compartments"] = compartments
            if len(compartments) == 1:
                settings["compartment"] = compartments[0]
        elif ctx.var_value("compartment_name"):
            settings["compartment"] = ctx.var_value("compartment_name")
        settings["terraform_dir"] = _display_path(tf_dir, project_dir)

    # 3. OCI config (auth identity)
    profile = str(settings.get("oci_profile") or os.environ.get("OCI_CLI_PROFILE") or "DEFAULT")
    oci_config = parse_oci_config(profile)
    tf_tenancy = settings.get("tenancy_ocid")
    auth_tenancy = oci_config.get("tenancy_ocid")
    if oci_config.get("region"):
        settings.setdefault("region", oci_config["region"])
    if oci_config.get("oci_auth"):
        settings["oci_auth"] = oci_config["oci_auth"]
    if auth_tenancy:
        settings.setdefault("tenancy_ocid", auth_tenancy)
        if auth_tenancy != settings["tenancy_ocid"]:
            settings["auth_tenancy_ocid"] = auth_tenancy

    # 4. OCI CLI (Terraform tenancy first, auth identity second)
    if query_cli:
        auth_mode = settings.get("oci_auth")
        auth_arg = "security_token" if auth_mode == "security_token" else None
        tried = []
        for ocid in (tf_tenancy, auth_tenancy):
            if not ocid or ocid in tried:
                continue
            tried.append(ocid)
            cli = query_oci_cli(str(ocid), profile, auth=auth_arg)
            if cli.get("tenancy_name"):
                settings.pop("cli_warning", None)
                for k in ("tenancy_name", "subscribed_regions", "home_region"):
                    if k in cli:
                        settings[k] = cli[k]
                if ocid != settings.get("tenancy_ocid"):
                    settings["terraform_tenancy_ocid"] = settings["tenancy_ocid"]
                    settings["tenancy_ocid"] = ocid
                    settings.pop("auth_tenancy_ocid", None)
                break
            if cli.get("cli_warning"):
                settings["cli_warning"] = cli["cli_warning"]

    # 5. Labels
    region = str(settings.get("region") or "")
    if region:
        settings.setdefault("region_label", region_display_label(region))

    # 6. Logos
    for k, v in find_logos(project_dir).items():
        settings.setdefault(k, v)

    return settings


USEFUL_KEYS = ("region", "tenancy_ocid", "tenancy_name", "logo_light", "logo_dark", "vcns", "compartments")


def has_useful_settings(settings: dict) -> bool:
    return any(settings.get(k) for k in USEFUL_KEYS)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

FIELD_ORDER = (
    "tenancy_name",
    "tenancy_ocid",
    "auth_tenancy_ocid",
    "terraform_tenancy_ocid",
    "region",
    "region_label",
    "home_region",
    "subscribed_regions",
    "oci_profile",
    "oci_auth",
    "compartment",
    "compartment_ocid",
    "compartments",
    "vcns",
    # A4: the ONE view choice that is remembered between runs, because the
    # guidelines ask for the diagram's purpose to be recorded with the diagram.
    # It is never DETECTED - Step 1 asks it and writes it back. Every other view
    # key (detail, label_mode, layers, filter, mode, global_services) is a
    # per-run choice, and a stale remembered filter is a correctness problem.
    "purpose",
    "logo_light",
    "logo_dark",
    "terraform_dir",
    "terraform_dirs",
)
ANSWERED_KEYS = ("purpose",)
INTERNAL_KEYS = frozenset({"cli_warning"})


def _yaml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    # json.dumps produces a double-quoted scalar with valid YAML escapes.
    return json.dumps(str(value), ensure_ascii=False)


def to_yaml_frontmatter(settings: dict) -> str:
    """Format settings as a YAML frontmatter block (strings JSON-quoted, lists as JSON)."""
    lines = ["---"]
    emitted = set()
    for key in FIELD_ORDER:
        if key in settings and settings[key] is not None:
            lines.append(f"{key}: {_yaml_scalar(settings[key])}")
            emitted.add(key)
    for key in sorted(settings):
        if key in emitted or key in INTERNAL_KEYS or settings[key] is None:
            continue
        lines.append(f"{key}: {_yaml_scalar(settings[key])}")
    lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="detect_settings.py",
        description="Auto-detect OCI diagram settings from Terraform, ~/.oci/config and the OCI CLI. "
                    "Prints YAML frontmatter for .claude/oci-drawio-architect.local.md to stdout.",
        epilog="Exit codes: 0 success, 1 nothing detected, 2 terraform_dir does not exist.",
    )
    parser.add_argument("terraform_dir", nargs="?",
                        help="Terraform environment directory (default: auto-detect below the current directory)")
    parser.add_argument("--no-cli", action="store_true", help="skip OCI CLI queries")
    args = parser.parse_args(argv)

    if args.terraform_dir is not None and not Path(args.terraform_dir).expanduser().is_dir():
        print(f"Error: Terraform directory does not exist: {args.terraform_dir}", file=sys.stderr)
        return 2

    settings = detect(args.terraform_dir, query_cli=not args.no_cli)

    def _report_alternatives() -> None:
        alternatives = settings.get("terraform_dirs")
        if isinstance(alternatives, list) and len(alternatives) > 1:
            print(f"\nMultiple Terraform directories found at the same depth; using {alternatives[0]!r}. "
                  f"Alternatives: {', '.join(alternatives[1:])}. "
                  "Re-run with a directory argument to choose another.", file=sys.stderr)

    if not has_useful_settings(settings):
        print("No settings detected (no region, tenancy, logos or VCNs found). "
              "Provide a Terraform directory as argument.", file=sys.stderr)
        _report_alternatives()
        return 1

    print(to_yaml_frontmatter(settings))

    print("\nDetected:", file=sys.stderr)
    for k, v in settings.items():
        if k in INTERNAL_KEYS:
            continue
        shown = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
        print(f"  {k}: {shown}", file=sys.stderr)
    _report_alternatives()
    if settings.get("cli_warning"):
        print(f"\nWarning: {settings['cli_warning']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
