#!/usr/bin/env python3
"""
fetch_dc_scheduled_runs_logs.py

Fetch GitHub Actions failed Terraform/Schematics job logs and classify all distinct
technical root-cause errors for dashboard consumption.

Main behavior:
- Error anchors are detected before noise filtering.
- Logs are split into focused error blocks.
- Each error block is classified directly by the LLM.
- AI output is validated and deduplicated.
- JSON parsing is hardened against extra LLM text and common JSON mistakes.
- Generic module values such as "standard" are normalized/replaced.
- Schematics wrapper-only failures are classified as Schematics Apply, Schematics Job,
  or Schematics Workspace only when no more specific root cause is visible.
- Python validation accepts only the new fine-grained category taxonomy.
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple

import requests

# Add parent directory to path to import utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.watsonx_client import WatsonXClient

# Import Schematics log fetcher
from fetch_schematics_logs import fetch_all_workspace_logs, get_iam_token


# -----------------------------
# Configuration / Constants
# -----------------------------

# Load categories from JSON file
def load_categories_config():
    """Load categories configuration from categories.json"""
    script_dir = Path(__file__).parent
    categories_file = script_dir.parent / "data" / "dc_categories.json"

    try:
        with open(categories_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        if not config or 'categories' not in config:
            print(f"ERROR: Invalid categories.json structure", file=sys.stderr)
            return None

        return config
    except FileNotFoundError:
        print(f"ERROR: categories.json not found at {categories_file}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in categories.json: {e}", file=sys.stderr)
        return None

# Load categories at module level
CATEGORIES_CONFIG = load_categories_config()
if CATEGORIES_CONFIG is None:
    print("ERROR: Failed to load categories configuration. Exiting.", file=sys.stderr)
    sys.exit(1)

# Build ALLOWED_CATEGORIES set from config
ALLOWED_CATEGORIES = {cat['name'] for cat in CATEGORIES_CONFIG['categories']}

BAD_MODULE_VALUES = {
    "",
    "unknown",
    "standard",
    "default",
    "main",
    "this",
    "module",
    "resource",
    "n/a",
    "none",
    "null",
}

# -----------------------------
# Terraform Log Filtering Patterns
# -----------------------------

_TERRAFORM_NOISE_PATTERNS: List[Pattern[str]] = [
    # Environment variables
    re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+:\s+\S"),
    re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+=\S"),
    re.compile(r"^export\s+[A-Z]"),

    # GitHub Actions metadata
    re.compile(r"^##\[(group|endgroup|debug|command)\]"),
    re.compile(r"^(Post job cleanup|Complete job|Set up job)"),
    re.compile(r"^(Cleaning up|Download action|Getting action)"),
    re.compile(r"^Run actions/"),
    re.compile(r"^\s*with:\s*$"),
    re.compile(r"^\s*env:\s*$"),
    re.compile(r"^Current runner version"),
    re.compile(r"^Runner name"),
    re.compile(r"^Runner group"),
    re.compile(r"^Machine name"),

    # Terraform success/progress messages
    re.compile(r"^\s*Terraform will perform"),
    re.compile(r"^\s*Plan:.*to add,.*to change,.*to destroy"),
    re.compile(r"^\s*Apply complete!"),
    re.compile(r"^\s*Destroy complete!"),
    re.compile(r"^\s*[a-z_]+\.[a-z_]+: (Creating|Modifying|Destroying)\.\.\."),
    re.compile(r"^\s*[a-z_]+\.[a-z_]+: (Creation|Modification|Destruction) complete"),
    re.compile(r"^\s*[a-z_]+\.[a-z_]+: Still (creating|modifying|destroying)"),
    re.compile(r"^\s*[a-z_]+\.[a-z_]+: Refreshing state"),

    # Terraform output suppressed messages
    re.compile(r"\(output suppressed due to sensitive value"),
    re.compile(r"^\s*Terraform (apply|plan|destroy) \|.*\(output suppressed"),

    # Terraform plan output, non-error
    re.compile(r"^\s*#.*will be (created|updated|destroyed)"),
    re.compile(r"^\s*\+\s+[a-z_]+="),
    re.compile(r"^\s*~\s+[a-z_]+="),

    # Warnings are usually not root cause
    re.compile(r"^\s*Warning:"),
    re.compile(r"^\s*\(and \d+ more similar warnings"),

    # IBM Cloud/Schematics progress only.
    # IMPORTANT: Do NOT add "SCHEMATICS DEPLOYMENT FAILED" here.
    re.compile(r"^\s*Schematics.*in progress"),
    re.compile(r"^\s*Workspace.*is being"),
    re.compile(r"^\s*Activity.*started"),

    # SSH connection details
    re.compile(r"^\s*Connecting to remote host via SSH"),
    re.compile(r"^\s*Using configured bastion host"),
    re.compile(r"^\s*Host:\s+[\d.]"),
    re.compile(r"^\s*User:\s+\w+"),
    re.compile(r"^\s*Password:\s+(true|false)"),
    re.compile(r"^\s*Private key:\s+(true|false)"),
    re.compile(r"^\s*Certificate:\s+(true|false)"),
    re.compile(r"^\s*SSH Agent:\s+(true|false)"),
    re.compile(r"^\s*Checking Host Key:\s+(true|false)"),
    re.compile(r"^\s*Target Platform:\s+\w+"),
    re.compile(r"^\s*Connected!"),

    # Test commands (not errors) - various forms of shell test commands
    re.compile(r'test\s+["\']?\$\(dig'),
    re.compile(r'^\s*\+\s+test\s+["\']?\$\(dig'),
    re.compile(r'test\s+.*dig\s+.*\+short'),

    # Provisioning and Ansible success output
    re.compile(r"^\s*Provisioning with .*(remote-exec|file|local-exec)"),
    re.compile(r"^\s*PLAY \[.*\]"),
    re.compile(r"^\s*TASK \[.*\]"),
    re.compile(r"^\s*ok:\s+\[[\d.]+\]"),
    re.compile(r"^\s*changed:\s+\[[\d.]+\]"),
    re.compile(r"^\s*skipping:\s+\[[\d.]+\]"),
    re.compile(r"^\s*PLAY RECAP"),
    re.compile(r"^\s*[\d.]+\s+:\s+ok=\d+\s+changed=\d+"),

    # Provisioning and Ansible success output
    re.compile(r"^\s*Provisioning with .*(remote-exec|file|local-exec)"),
    re.compile(r"^\s*PLAY \[.*\]"),
    re.compile(r"^\s*TASK \[.*\]"),
    re.compile(r"^\s*ok:\s+\[[\d.]+\]"),
    re.compile(r"^\s*changed:\s+\[[\d.]+\]"),
    re.compile(r"^\s*skipping:\s+\[[\d.]+\]"),
    re.compile(r"^\s*PLAY RECAP"),
    re.compile(r"^\s*[\d.]+\s+:\s+ok=\d+\s+changed=\d+"),

    # Blank/decorative lines
    re.compile(r"^\s*$"),
    re.compile(r"^\*{3,}$"),
    re.compile(r"^={3,}$"),
    re.compile(r"^-{3,}$"),
    re.compile(r"^─{3,}$"),
    re.compile(r"^│\s*$"),

    # Download/plugin progress
    re.compile(r"^\s*\d+%\s"),
    re.compile(r"^\s*(Downloading|Extracting|Unpacking)\s"),
    re.compile(r"^\s*\d+\s+(B|KB|MB|GB|MiB|GiB)\s+/\s+\d+"),
    re.compile(r"Plug-in.*was (already )?installed"),
    re.compile(r"Do you want to (update|install) it"),
    re.compile(r"Attempting to download the binary file"),
    re.compile(r"Installing binary"),
    re.compile(r"Use 'ibmcloud plugin show"),
]

_TERRAFORM_ERROR_PATTERNS: List[Pattern[str]] = [
    # Terraform errors
    re.compile(r"(?i)^Error:"),
    re.compile(r"(?i)^│\s*Error:"),
    re.compile(r"(?i)\bError:"),
    re.compile(r"(?i)\bErrors\s+(during|while|in)"),

    # IBM Cloud/Schematics concrete errors only.
    # Do NOT add generic wrapper anchors here:
    # - SCHEMATICS DEPLOYMENT FAILED
    # - schematics.*deployment.*failed
    # - schematics.*failed
    # - schematics.*error
    re.compile(r"(?i)schematics.*api.*error"),
    re.compile(r"(?i)ibmcloud schematics.*error"),
    re.compile(r"(?i)failed to start.*terraform job"),
    re.compile(r"(?i)Error response from server\. Status code:\s*[45]\d{2}"),
    re.compile(r"(?i)workspace.*failed"),
    re.compile(r"(?i)activity.*failed"),

    # Deployment failures
    re.compile(r"(?i)deploy[_\s]status.*failed"),
    re.compile(r"(?i)script execution.*failed"),
    re.compile(r"(?i)could not execute job"),

    # API/HTTP errors
    re.compile(r"(?i)\bHTTP[/ ](4\d{2}|5\d{2})"),
    re.compile(r"(?i)status[_\s]code[=:]\s*[45]\d{2}"),
    re.compile(r"(?i)Status code:\s*[45]\d{2}"),
    re.compile(r"(?i)API.*error"),
    re.compile(r"(?i)request failed"),
    re.compile(r"(?i)authentication.*failed"),
    re.compile(r"(?i)authorization.*failed"),
    re.compile(r"(?i)unexpected response code"),

    # Provider/resource errors
    re.compile(r"(?i)restapi.*error"),
    re.compile(r"(?i)restapi.*failed"),
    re.compile(r"(?i)document.*conflict"),
    re.compile(r"(?i)update conflict"),
    re.compile(r"(?i)database.*error"),
    re.compile(r"(?i)resource.*not found"),
    re.compile(r"(?i)resource.*already exists"),
    re.compile(r"(?i)resource.*creation failed"),
    re.compile(r"(?i)resource.*deletion failed"),
    re.compile(r"(?i)provider.*error"),
    re.compile(r"(?i)provider.*failed"),

    # OS/package manager
    re.compile(r"(?i)Failed to download"),
    re.compile(r"(?i)Cannot download"),
    re.compile(r"(?i)All mirrors were tried"),
    re.compile(r"(?i)repository.*not found"),
    re.compile(r"(?i)No package.*available"),
    re.compile(r"(?i)Package.*not found"),

    # Package manager / Repository errors (YUM, DNF, APT, etc.)
    re.compile(r'(?i)Failed to download'),
    re.compile(r'(?i)Cannot download'),
    re.compile(r'(?i)All mirrors were tried'),
    re.compile(r'(?i)repository.*not found'),
    re.compile(r'(?i)No package.*available'),
    re.compile(r'(?i)Package.*not found'),

    # General errors
    re.compile(r"(?i)\bfatal\b"),
    # Removed: re.compile(r"(?i)\bFAILED!?\b"),  - too generic, causes false positives
    # Removed: re.compile(r"(?i)\bERROR\b"),     - too generic, causes false positives
    re.compile(r"(?i)\bException\b"),
    re.compile(r"(?i)\bTraceback\b"),
    re.compile(r"(?i)exit[- ]?(code|status)[- ]?[1-9]"),
    re.compile(r"^##\[error\]"),
    re.compile(r"(?i)\bcommand not found\b"),
    re.compile(r"(?i)\bpermission denied\b"),
    re.compile(r"(?i)\bconnection refused\b"),
    re.compile(r"(?i)\btimed?\s*out\b"),
    re.compile(r"(?i)\bno such file\b"),
    re.compile(r"(?i)Process completed with exit code [1-9]"),

    # Terraform configuration
    re.compile(r"(?i)\bInvalid index\b"),
    re.compile(r"(?i)\bUnsupported attribute\b"),
    re.compile(r"(?i)\bReference to undeclared resource\b"),
    re.compile(r"(?i)\bInvalid value for input variable\b"),
    re.compile(r"(?i)\bInvalid for_each argument\b"),
    re.compile(r"(?i)\bDuplicate object key\b"),
    re.compile(r"(?i)\bnon-zero (exit )?code\b"),
    re.compile(r"(?i)\breturned non-zero\b"),
    re.compile(r"(?i)\bStill creating\.\.\. \[[4-9][0-9]m"),
]


# -----------------------------
# Helpers
# -----------------------------


def _is_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return any(p.search(s) for p in _TERRAFORM_NOISE_PATTERNS)


def _is_error_line(line: str) -> bool:
    """Check if a line is an error line, excluding warnings."""
    # First check if it's a warning - warnings should NOT be treated as errors
    s = line.strip()
    if re.match(r"^\s*Warning:", s, re.IGNORECASE):
        return False
    if re.match(r"^\s*│\s*Warning:", s, re.IGNORECASE):
        return False
    # Now check if it matches error patterns
    return any(p.search(line) for p in _TERRAFORM_ERROR_PATTERNS)

def get_log_snippet(block: str, max_lines: int = 20) -> str:
    """
    Extract a snippet from the error block for dashboard display.

    The block is already cleaned (timestamps removed, normalized by extract_error_blocks),
    so we just find the error line and show context around it.
    """
    lines = block.splitlines()
    if not lines:
        return block.strip() if block.strip() else "Error details not available"

    # Find the error line
    error_line_idx = None
    for i, line in enumerate(lines):
        if _is_error_line(line):
            error_line_idx = i
            break

    # Select lines around the error, or last lines if no error found
    if error_line_idx is not None:
        start_idx = max(0, error_line_idx - 3)
        end_idx = min(len(lines), start_idx + max_lines)
        selected_lines = lines[start_idx:end_idx]
    else:
        selected_lines = lines[-max_lines:]

    # Collapse repetitive "Still creating..." progress messages
    snippet_lines = []
    still_creating_pattern = re.compile(r'Still (creating|modifying|destroying)\.\.\.', re.IGNORECASE)
    still_creating_count = 0
    still_creating_kept = 0
    max_still_creating = 3

    for line in selected_lines:
        line = line.strip()
        if not line:
            continue

        if still_creating_pattern.search(line):
            still_creating_count += 1
            if still_creating_kept < max_still_creating:
                snippet_lines.append(line)
                still_creating_kept += 1
        else:
            snippet_lines.append(line)

    # Add note about omitted "Still creating..." lines
    if still_creating_count > max_still_creating:
        omitted = still_creating_count - max_still_creating
        snippet_lines.append(f"... ({omitted} more 'Still creating...' lines omitted)")

    return "\n".join(snippet_lines) if snippet_lines else (block.strip() if block.strip() else "Error details not available")

def has_non_schematics_root_cause(block: str) -> bool:
    """
    Detect whether the block contains a REAL technical root cause,
    not just a generic failure wrapper.
    """

    lines = block.splitlines()

    #  Step 1: Check if ANY real error signal exists
    has_error_anchor = any(_is_error_line(line) for line in lines)

    if not has_error_anchor:
        return False

    lower = block.lower()

    #  Step 2: Look for concrete technical indicators
    root_cause_indicators = [
        # Terraform resources
        "with module.",
        "ibm_is_",
        "ibm_pi_",
        "resource \"ibm_",
        "createloadbalancer",
        "createvpn",
        "createvpnserver",
        "power-iaas",
        "lpar",
        "placement api",
        "no valid host",
        "no allocation candidates",
        "image does not exist",
        "failed to perform",

        # OS / SSH / Ansible
        "remote-exec",
        "failed to connect to the host via ssh",
        "ssh:",
        "ansible",
        "failed to download metadata",
        "cannot download repomd",
        "no package",
        "repository",
        "permission denied",
        "connection timed out",
        "connection refused",

        # API / HTTP
        "status code:",
        "http 4",
        "http 5",
        "unexpected response code",
        "request failed",

        # Runtime
        "traceback",
        "exception",
        "command not found",
    ]

    return any(indicator in lower for indicator in root_cause_indicators)

def is_schematics_wrapper_failure(block: str) -> bool:
    """
    Detect Schematics execution/deployment wrapper failures.
    These are valid Schematics errors only if no more specific root cause is visible.
    """
    lower = block.lower()

    wrapper_indicators = [
        "schematics deployment failed",
        "deploy_status=\"failed\"",
        "schematics_workspace_id",
        "terraform apply error",
        "terraform destroy error",
        "terraform plan error",
        "could not execute job",
        "terraform apply errorexit status",
        "terraform destroy errorexit status",
        "error executing terraform",
    ]

    return any(indicator in lower for indicator in wrapper_indicators)

def remove_weak_errors(errors: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Remove weak wrapper errors if stronger root-cause errors exist.
    """

    if not errors:
        return errors

    strong_errors = [e for e in errors if not is_weak_schematics_error(e)]

    # If we have real errors → drop weak ones
    if strong_errors:
        return strong_errors

    # If ONLY weak errors exist → keep ONE clean Schematics fallback
    best = {
        "category": "IBMCLOUD Schematics",
        "module": "schematics_apply",
        "description": "Schematics Terraform apply failed without visible root cause",
    }

    return [best]

def select_root_causes(errors: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Keep ALL independent root causes.
    Remove cascading follow-up errors.
    """

    if not errors:
        return errors

    result = []

    categories = [e["category"] for e in errors]

    has_ssh = "SSH Connectivity" in categories
    has_power = any(c.startswith("PowerVS") for c in categories)

    for err in errors:
        cat = err["category"]

        if has_ssh:
            if cat in {"Remote Exec", "Ansible", "OS Registration"}:
                continue

        if has_power:
            if cat in {"Remote Exec", "Ansible"}:
                continue

        if cat.startswith("Schematics") or cat.startswith("Terraform"):
            continue

        result.append(err)

    # Final dedupe again
    seen = set()
    final = []
    for e in result:
        key = (e["category"], e["module"])
        if key not in seen:
            final.append(e)
            seen.add(key)

    return final



def is_weak_schematics_error(error: Dict[str, str]) -> bool:
    """
    Detect weak Schematics / Terraform wrapper errors that are not root causes.
    """
    desc = str(error.get("description", "")).lower()
    module = str(error.get("module", "")).lower()

    text = f"{module} {desc}"

    weak_patterns = [
        "terraform apply failed",
        "terraform apply error",
        "apply failed",
        "apply exited",
        "exit code 1",
        "errorexit status",
        "could not execute job",
        "schematics job failed",
        "workspace deployment failed",
        "deployment failed",
        "timeout occurred during workspace apply",
        "workspace apply timed out",
        "timed out during apply",
    ]

    return any(p in text for p in weak_patterns)

def is_generic_schematics_wrapper_block(block: str) -> bool:
    """
    Detect blocks that contain ONLY final Schematics wrapper output
    without any concrete root cause.
    """
    lower = block.lower()

    final_wrapper_patterns = [
        "terraform apply error",
        "terraform apply errorexit status",
        "could not execute job",
        "schematics deployment failed",
        "deploy_status=\"failed\"",
        "process completed with exit code",
    ]

    has_wrapper = any(p in lower for p in final_wrapper_patterns)

    has_real_error = has_non_schematics_root_cause(block)

    return has_wrapper and not has_real_error


def filter_generic_schematics_blocks(blocks: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Drop generic Schematics wrapper blocks only if other more specific blocks exist.
    If the wrapper block is the only block, keep it so it can be classified as Schematics.
    """
    if len(blocks) <= 1:
        return blocks

    filtered_blocks = [
    block for block in blocks
    if not is_generic_schematics_wrapper_block(block["clean"])
    ]


    if filtered_blocks and len(filtered_blocks) != len(blocks):
        print(
            f"    [filter_generic_schematics_blocks] Dropped "
            f"{len(blocks) - len(filtered_blocks)} generic Schematics wrapper block(s)"
        )
        return filtered_blocks

    return blocks

def normalize_category(category: str) -> str:
    """
    Normalize LLM category output to the new allowed category taxonomy.
    Only categories from ALLOWED_CATEGORIES are accepted.
    Unknown or legacy values become "Unknown".
    """
    if not category:
        return "Unknown"

    raw = str(category).strip()

    if raw in ALLOWED_CATEGORIES:
        return raw

    raw_lower = raw.lower()
    for allowed in ALLOWED_CATEGORIES:
        if raw_lower == allowed.lower():
            return allowed

    return "Unknown"

def correct_false_schematics(error: Dict[str, str], block: str) -> Dict[str, str]:
    """
    Normalize category output and keep Schematics corrections minimal.
    This function must NOT reintroduce legacy categories.
    """
    error["category"] = normalize_category(error.get("category", "Unknown"))

    return error

def correct_unknown_schematics_wrapper(error: Dict[str, str], block: str) -> Dict[str, str]:
    """
    Reclassify Unknown to a concrete Schematics category only when the block clearly shows
    a Schematics wrapper failure and no more specific root cause exists.
    """
    error["category"] = normalize_category(error.get("category", "Unknown"))

    if error.get("category") != "Unknown":
        return error

    if not is_schematics_wrapper_failure(block):
        return error

    if has_non_schematics_root_cause(block):
        return error

    lower = block.lower()

    if "terraform apply" in lower:
        error["category"] = "Schematics Apply"
        error["module"] = "schematics_apply"
    elif "terraform destroy" in lower:
        error["category"] = "Schematics Apply"
        error["module"] = "schematics_destroy"
    elif "terraform plan" in lower:
        error["category"] = "Terraform Apply"
        error["module"] = "schematics_plan"
    elif "workspace" in lower:
        error["category"] = "Schematics Workspace"
        error["module"] = "schematics_workspace"
    elif "could not execute job" in lower or "job" in lower:
        error["category"] = "Schematics Job"
        error["module"] = "schematics_job"
    else:
        error["category"] = "Schematics Apply"
        error["module"] = "deployment"

    print(f"    [correct_unknown_schematics_wrapper] Reclassified Unknown -> {error['category']}")
    return error

def extract_error_blocks(
    log_content: str,
    context_before: int = 25,
    context_after: int = 60,
    merge_gap: int = 15,
    #max_block_size: int = 4000,
) -> List[Dict[str, str]]:
    """
    Extract separate error blocks from the full normalized log.
    Important: this searches error anchors in the complete log before filtering noise.
    """
    raw_lines = log_content.splitlines()
    lines = [normalize_log_line(line) for line in raw_lines]

    print(f"    [extract_error_blocks] Total lines: {len(lines)}")

    anchor_indices = [i for i, line in enumerate(lines) if _is_error_line(line)]
    print(f"    [extract_error_blocks] Found {len(anchor_indices)} error anchor(s)")

    if not anchor_indices:
        print("    [extract_error_blocks] ⚠ No error anchors found")
        return []

    windows: List[Tuple[int, int]] = []
    for idx in anchor_indices:
        start = max(0, idx - context_before)
        end = min(len(lines), idx + context_after + 1)
        windows.append((start, end))

    windows.sort()
    merged: List[List[int]] = []
    for start, end in windows:
        if not merged:
            merged.append([start, end])
            continue
        if start <= merged[-1][1] + merge_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    blocks: List[Dict[str, str]] = []
    for block_idx, (start, end) in enumerate(merged, 1):
        block_lines = lines[start:end]
        raw_block_lines = raw_lines[start:end]

        cleaned_block_lines = []
        for line in block_lines:
            s = line.strip()
            if not s:
                continue
            if re.match(r"^[=*─-]{3,}$", s):
                continue
            # Filter out excessive noise
            if _is_noise_line(s):
                continue
            cleaned_block_lines.append(line)

        block = "\n".join(cleaned_block_lines).strip()
        raw_block = "\n".join(raw_block_lines).strip()

        if block or raw_block:
            blocks.append({"clean": block, "raw": raw_block})
            print(f"    [extract_error_blocks] Block {block_idx}: lines {start}-{end}, chars={len(block)}")

    return blocks

def normalize_log_line(line: str) -> str:
    """Normalize timestamps, Terraform prefixes, ANSI sequences and HTML entities."""
    line = re.sub(r"\x1b\[[0-9;]*m", "", line)
    line = html.unescape(line)

    line = re.sub(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*", "", line)

    line = re.sub(
        r"^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\s+[^|]*\|\s*",
        "",
        line,
    )

    return line.rstrip()

def is_warning_like_error(error: Dict[str, str]) -> bool:
    """
    Detect warnings disguised as errors after LLM extraction.
    """

    category = str(error.get("category", "")).lower()
    description = str(error.get("description", "")).lower()

    text = f"{category} {description}"

    warning_patterns = [
        # Classic warnings
        "warning:",
        "deprecated",
        "will be removed",
        "no longer supported",
        "has no effect",
        "ignore_changes has no effect",
        "redundant",
        "deprecated feature",
        "deprecated attribute",

        # Terraform typical warnings
        "argument is deprecated",
        "attribute is deprecated",
        "use protocol instead",

        # non-failure informational issues
        "does not take effect",
    ]

    return any(p in text for p in warning_patterns)

def infer_module_from_log(text: str) -> str:
    """Infer Terraform module/resource name from an error block."""
    patterns = [
        # Most specific Terraform addresses first:
        # with module.powervs_workspace.ibm_resource_instance.pi_workspace
        r"with\s+module\.[A-Za-z0-9_-]+\.([A-Za-z0-9_]+)\.([A-Za-z0-9_-]+)",
        r"module\.[A-Za-z0-9_-]+\.([A-Za-z0-9_]+)\.([A-Za-z0-9_-]+)",

        # Resource block:
        # resource "ibm_resource_instance" "pi_workspace"
        r"resource\s+\"[^\"]+\"\s+\"([^\"]+)\"",

        # Direct resource reference:
        # with ibm_is_lb.load_balancer
        r"with\s+([A-Za-z0-9_]+)\.([A-Za-z0-9_-]+)",

        # Common IBM resource fallback
        r"ibm_resource_instance\.([A-Za-z0-9_-]+)",
        r"ibm_pi_([a-z_]+)",
        r"ibm_is_([a-z_]+)",

        # Generic module references last
        r"with\s+module\.([A-Za-z0-9_-]+)",
        r"module\.([A-Za-z0-9_-]+)\.",
        r"\.terraform/modules/([A-Za-z0-9_-]+)/",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue

        groups = match.groups()
        result = groups[-1] if groups else match.group(1)
        result = result.strip().lower()

        if result in BAD_MODULE_VALUES:
            continue
        if len(result) > 60:
            continue
        if result.startswith("crn:"):
            continue
        if re.search(r"[a-f0-9]{16,}", result):
            continue

        return result

    return "unknown"

def validate_and_dedupe_errors(errors: List[Dict[str, str]]) -> List[Dict[str, str]]:
    valid: List[Dict[str, str]] = []
    seen = set()

    for error in errors:
        if not isinstance(error, dict):
            continue

        category = normalize_category(error.get("category", "Unknown"))
        module = str(error.get("module", "unknown")).strip().lower() or "unknown"

        if module in BAD_MODULE_VALUES:
            module = "unknown"

        item = {
            "category": category,
            "module": module,
        }

        if "raw_log" in error:
            item["raw_log"] = error["raw_log"]

        # Dedupe key based on category and module only
        key = (item["category"], item["module"].lower())

        if key not in seen:
            valid.append(item)
            seen.add(key)

    return valid


def extract_job_pattern(s: str) -> Optional[str]:
    parts = [p.strip() for p in s.split("/") if p.strip()]
    return parts[-1] if parts else None


def save_scheduled_runs_json(logs_summary: List[Dict[str, Any]], filename: str) -> None:
    # Sort by date descending (newest first)
    def extract_date_for_sort(run):
        try:
            date_html = run.get("Date", "")
            match = re.search(r'>(\d{4}-\d{2}-\d{2})<', date_html)
            return match.group(1) if match else ""
        except (AttributeError, TypeError):
            return ""

    sorted_logs = sorted(logs_summary, key=extract_date_for_sort, reverse=True)

    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted_logs, indent=2), encoding="utf-8")
    print(f"Saved {len(sorted_logs)} records to {filename} (sorted by date, newest first)")


def load_existing_runs(json_file: str) -> List[Dict[str, Any]]:
    path = Path(json_file)
    if not path.is_file():
        print(f"JSON file {json_file} not found. Processing all runs.")
        return []

    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            print(f"JSON file {json_file} is empty. Treating as no existing runs.")
            return []
        data = json.loads(content)
        if not isinstance(data, list):
            print(f"Unexpected JSON structure in {json_file}, expected list.")
            return []
        print(f"Loaded {len(data)} records from {json_file}")
        return data
    except json.JSONDecodeError as e:
        print(f"JSON decode error reading {json_file}: {e}. Treating as empty.")
        return []
    except Exception as e:
        print(f"Unexpected error reading JSON file {json_file}: {e}")
        return []


# -----------------------------
# LLM extraction
# -----------------------------


def _extract_first_json_array(raw: str) -> str:
    """
    Extract the first complete JSON array from raw text.
    Handles markdown code blocks and trailing text after the JSON.
    Returns empty string if no valid JSON array structure is found.
    """
    if not raw or not raw.strip():
        print("WARNING: Empty LLM response")
        return ""

    raw = raw.strip()

    # Remove markdown code fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()

    # Remove common LLM prefixes
    prefixes_to_remove = [
        r"^Here is the analysis:?\s*",
        r"^Here is the JSON:?\s*",
        r"^Here are the errors:?\s*",
        r"^The analysis is:?\s*",
        r"^Output:?\s*",
        r"^Result:?\s*",
    ]
    for prefix in prefixes_to_remove:
        raw = re.sub(prefix, "", raw, flags=re.IGNORECASE).strip()

    first = raw.find("[")
    if first == -1:
        print(f"WARNING: No JSON array found in LLM response. Response starts with: {raw[:100]!r}")
        return ""

    depth = 0
    in_string = False
    escape = False

    for i in range(first, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                json_text = raw[first : i + 1]
                remaining = raw[i + 1:].strip()
                if remaining:
                    print(f"WARNING: Found trailing text after JSON array (length={len(remaining)}): {remaining[:100]!r}")
                return json_text

    print("WARNING: Incomplete JSON array in LLM response")
    return raw[first:]


def extract_errors_with_regex(text: str) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []
    pattern = (
        r"\{[^}]*?(?:category|\"category\")\s*[:=]\s*[\"']?([^\"',}\]]+)"
        r"[^}]*?(?:module|\"module\")\s*[:=]\s*[\"']?([^\"',}\]]+)"
        r"[^}]*?(?:description|\"description\")\s*[:=]\s*[\"']?(.+?)[\"']?\s*[,}]"
    )

    for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
        errors.append(
            {
                "category": match.group(1).strip(),
                "module": match.group(2).strip(),
                "description": re.sub(r"\s+", " ", match.group(3).strip()),
            }
        )
    return errors


def extract_multiple_errors(job_log: str, llm_apikey: str) -> Dict[str, Any]:
    """Use watsonx to extract errors from ONE focused error block."""
    print("Running extract_multiple_errors() via mistralai/mistral-medium-2505")

    project_id = "944a0ac5-a521-4a51-b513-77d50534f0fe"
    client = WatsonXClient(
        api_key=llm_apikey,
        project_id=project_id,
        url="https://us-south.ml.cloud.ibm.com",
        model_id="mistralai/mistral-medium-2505",
    )

    gen_params = {
        "Decoding": "Greedy",
        "MIN_NEW_TOKENS": 10,
        "MAX_NEW_TOKENS": 800,
        #"TEMPERATURE": 0.1,
        #"TOP_P": 0.95,
        #"TOP_K": 50,
    }

    prompt_path = Path(__file__).parent.parent / "prompts" / "prototypev1_terraform_log_analysis.md"

    try:
        prompt_content = prompt_path.read_text(encoding="utf-8")

        # Build categories list from config
        categories_list = "\n".join(sorted(ALLOWED_CATEGORIES))

        # Build detailed category guide with patterns and examples
        category_details = []
        for cat in CATEGORIES_CONFIG['categories']:
            name = cat['name']
            patterns = cat.get('patterns', [])
            examples = cat.get('examples', [])

            detail = f"\n**{name}**"
            if patterns:
                detail += f"\n  Patterns: {', '.join(patterns)}"
            if examples:
                detail += f"\n  Examples: {'; '.join(examples)}"
            category_details.append(detail)

        categories_guide = "\n".join(category_details)

        # Replace placeholders in prompt
        prompt_template = prompt_content.replace("{log_content}", job_log)
        prompt_template = prompt_template.replace("{categories_list}", categories_list)
        prompt_template = prompt_template.replace("{categories_guide}", categories_guide)

    except Exception as e:
        print(f"Error loading prompt file: {e}; using fallback prompt")

        allowed_categories_text = "\n".join(sorted(ALLOWED_CATEGORIES))

        # Build category patterns for fallback
        category_patterns = []
        for cat in CATEGORIES_CONFIG['categories']:
            name = cat['name']
            patterns = cat.get('patterns', [])
            if patterns:
                category_patterns.append(f"{name}: {', '.join(patterns[:3])}")
        patterns_text = "\n".join(category_patterns)

        prompt_template = f"""
Analyze this Terraform/IBM Cloud error log and extract root-cause errors.

Return a JSON array. Each error needs:
- category: ONE of these: {allowed_categories_text}
- module: FULL Terraform module path (e.g., "module.sap_system.module.pi_hana_instance.module.pi_instance.ibm_pi_instance.instance") or "unknown"

Category Patterns (match errors to these):
{patterns_text}

CRITICAL MATCHING RULES:
- Check EVERY category pattern before considering "Unknown"
- Look for partial matches - if any pattern keyword appears, use that category
- Consider context: what resource/service is involved?
- "Unknown" should be RARE - only when NO pattern matches
- If you see infrastructure terms (instance, volume, network), match to PowerVS categories
- If you see connectivity terms (timeout, refused, connection), match to SSH/DNS categories

Rules:
- Use ONLY the allowed categories
- Match errors to categories based on the patterns above
- Do NOT use Schematics categories if a specific technical error exists
- Return [] if no errors found
- Output ONLY valid JSON, no explanations
- IMPORTANT: Provide the FULL module path as it appears in the error log, do NOT shorten it

Example output:
[
  {{
    "category": "PowerVS Instance",
    "module": "module.sap_system.module.pi_hana_instance.module.pi_instance.ibm_pi_instance.instance"
  }}
]

ERROR LOG:
{job_log}
"""

    try:
        generated_response = client.generate(prompt_template, gen_params)
        raw = generated_response["results"][0]["generated_text"].strip()
        print(f"RAW LLM RESPONSE length={len(raw)} first500={raw[:500]!r}")

        json_text = _extract_first_json_array(raw).strip()
        print(f"EXTRACTED JSON length={len(json_text)} first200={json_text[:200]!r}")

        if not json_text:
            return {
                "errorCount": 0,
                "categories": [],
                "details": [],
                "analysis_error": "No JSON array found in LLM response",
            }

        try:
            errors_array = json.loads(json_text)
        except json.JSONDecodeError as parse_error:
            print(f"Initial JSON parse failed: {parse_error}; json_text={json_text!r}")
            print("Trying conservative repair")
            repaired = re.sub(r",(\s*[}\]])", r"\1", json_text)
            repaired = re.sub(r"([\{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', repaired)
            repaired = re.sub(r":\s*'([^']*)'(\s*[,}\]])", r': "\1"\2', repaired)
            try:
                errors_array = json.loads(repaired)
            except json.JSONDecodeError:
                print("JSON repair failed; trying regex extraction")
                errors_array = extract_errors_with_regex(repaired)
                if not errors_array:
                    return {
                        "errorCount": 0,
                        "categories": [],
                        "details": [],
                        "analysis_error": f"Failed to parse LLM response as JSON: {parse_error.msg}",
                    }

        if isinstance(errors_array, dict):
            errors_array = errors_array.get("errors") or errors_array.get("details") or []
        if not isinstance(errors_array, list):
            errors_array = []

        validated_errors = validate_and_dedupe_errors(errors_array)
        for err in validated_errors:
            if not err.get("module") or err.get("module") in BAD_MODULE_VALUES:
                inferred = infer_module_from_log(job_log)
                if inferred != "unknown":
                    err["module"] = inferred

        return {
            "errorCount": len(validated_errors),
            "categories": sorted(set(e["category"] for e in validated_errors)),
            "details": validated_errors,
        }

    except Exception as e:
        print(f"Error calling WatsonX or parsing response: {e}")
        return {
            "errorCount": 0,
            "categories": [],
            "details": [],
            "analysis_error": f"Error analyzing log with WatsonX: {str(e)}",
        }


def _ensure_module(error: Dict[str, str], block: str) -> Dict[str, str]:
    if not error.get("module") or error.get("module") in BAD_MODULE_VALUES:
        inferred = infer_module_from_log(block)
        error["module"] = inferred if inferred != "unknown" else "unknown"
    return error


def analyze_job_log_errors(job_log: str, llm_apikey: str) -> Dict[str, Any]:
    """
    Extract error blocks and classify EACH block directly via LLM.
    No regex-based classification is used anymore.
    """
    blocks = extract_error_blocks(job_log, context_before=30, context_after=80)

    if not blocks:
        return {"errorCount": 0, "categories": [], "details": []}

    # Remove generic Schematics wrapper blocks only if more specific root-cause blocks exist
    blocks = filter_generic_schematics_blocks(blocks)

    all_errors: List[Dict[str, str]] = []
    analysis_errors: List[str] = []

    for idx, block_data in enumerate(blocks, 1):
        clean_block = block_data["clean"]
        raw_block = block_data["raw"]

        print(f"  Analyzing error block {idx}/{len(blocks)}, chars={len(clean_block)}")



        llm_input = clean_block if len(clean_block) > 200 else raw_block[:4000]

        llm_result = extract_multiple_errors(llm_input, llm_apikey)
        llm_errors = llm_result.get("details", [])
        print("LLM ERRORS RAW:", llm_errors)

        for err in llm_errors:
            err = correct_false_schematics(err, clean_block)
            err = correct_unknown_schematics_wrapper(err, clean_block)
            err = _ensure_module(err, clean_block)


            err["raw_log"] = get_log_snippet(clean_block, 20)

            all_errors.append(err)

        if llm_result.get("analysis_error"):
            analysis_errors.append(llm_result["analysis_error"])

    all_errors = validate_and_dedupe_errors(all_errors)

    #  Step 1: remove Terraform/Schematics wrappers
    all_errors = remove_weak_errors(all_errors)

    #  Step 3: keep only real root causes
    all_errors = select_root_causes(all_errors)


    for err in all_errors:
        if "raw_log" in err:
            err["description"] = err["raw_log"]
            del err["raw_log"]

    result: Dict[str, Any] = {
        "errorCount": len(all_errors),
        "categories": sorted(set(e["category"] for e in all_errors)),
        "details": all_errors,
    }

    if analysis_errors:
        result["analysis_errors"] = analysis_errors

    return result


# -----------------------------
# Job variation mapping
# -----------------------------


def get_variation_name(job_name: str) -> str:
    lower_name = job_name.lower()
    job_variation_map = {
        "SAP ready to go": "sap-ready-to-go-catalog",
        "SAP solution": "infrastructure-deployment",
        "Import Image": "pi-image-import-git",
        "standard Landscape": "sap-ready-to-go-catalog",
        "Quickstart": "quickstart-catalog-deployment",
        "OpenShift": "standard-openshift-catalog",
    }

    for variation, pattern in job_variation_map.items():
        if pattern.lower() in lower_name:
            return variation
    return "Unknown"


# -----------------------------
# Core GitHub functions
# -----------------------------


def get_schematics_run_logs(
    ibm_api_key: str,
    json_file: str,
    llm_apikey: str,
) -> List[Dict[str, Any]]:
    """
    Fetch Terraform logs from IBM Cloud Schematics (all workspaces) and
    analyse each log for errors using the existing LLM pipeline.

    Replaces get_github_run_logs() — no GitHub dependency.
    Produces the dc_scheduled_runs.json record shape:
        Date, workspacename, Repo, Version, Error
    (action_id is tracked internally under "_action_id" for dedup only —
    it is not written out as a user-facing field.)
    """
    print(f"\n{'='*80}\nSTARTING SCHEMATICS FETCH PROCESS\n{'='*80}")
    print(f"Output JSON file: {json_file}")

    logs_summary: List[Dict[str, Any]] = []
    existing_runs = load_existing_runs(json_file)
    # Use action_id as the deduplication key
    existing_action_ids = {
        str(item.get("_action_id")) for item in existing_runs if "_action_id" in item
    }

    try:
        # Authenticate with IBM Cloud IAM
        token = get_iam_token(ibm_api_key)

        # Fetch all workspace logs (returns list of dicts with log_text, metadata)
        log_entries = fetch_all_workspace_logs(token)

        print(f"\nTotal workspace logs fetched: {len(log_entries)}")

        # Skip workspaces whose action_id was already processed
        log_entries = [
            e for e in log_entries
            if str(e["action_id"]) not in existing_action_ids
        ]
        print(f"New entries to process (before status filter): {len(log_entries)}")

        # Keep only workspaces whose latest action failed
        log_entries = [
            e for e in log_entries
            if e.get("action_status", "").upper() == "FAILED"
        ]
        print(f"Failed workspace actions to analyse: {len(log_entries)}")

        for idx, entry in enumerate(log_entries, 1):
            ws_name      = entry["ws_name"]
            action_id    = entry["action_id"]
            action_type  = entry["action_type"]
            performed_at = entry["performed_at"]
            log_text     = entry["log_text"]
            catalog_variation = entry.get("catalog_variation", "Unknown")
            catalog_version   = entry.get("catalog_version", "Unknown")

            print(f"\n--- Processing {idx}/{len(log_entries)}: '{ws_name}' action={action_id} ---")
            print(f"  Type={action_type}, performed_at={performed_at}, log={len(log_text):,} chars")

            # Parse date from performed_at (ISO-8601)
            job_started_date = "N/A"
            if performed_at:
                try:
                    job_started_date = datetime.fromisoformat(
                        performed_at.replace("Z", "+00:00")
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    job_started_date = performed_at

            # Use the full workspace name as the workspacename field
            workspace_name = ws_name

            print(
                f"  Metadata: workspacename={workspace_name}, Repo={catalog_variation}, "
                f"Version={catalog_version}, Date={job_started_date}"
            )

            error_object = analyze_job_log_errors(log_text, llm_apikey)

            data = {
                "Date": job_started_date,
                "workspacename": workspace_name,
                "Repo": catalog_variation,
                "Version": catalog_version,
                "Error": error_object,
                "_action_id": action_id,
            }
            logs_summary.append(data)

            print(
                f"  ✓ RESULT: action={action_id}, Date={job_started_date}, "
                f"workspacename={workspace_name}, Errors={error_object['errorCount']} "
                f"categories={', '.join(error_object['categories'])}"
            )

    except Exception as e:
        import traceback
        print(f"An unexpected error occurred: {e}")
        print(traceback.format_exc())

    print(f"\nSuccessfully processed {len(logs_summary)} workspace logs.")
    return logs_summary


# -----------------------------
# Main / CLI entrypoint
# -----------------------------


def main() -> None:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_file = os.path.join(base_dir, "data", "dc_scheduled_runs.json")

    parser = argparse.ArgumentParser(
        description=(
            "Fetch Schematics workspace Terraform logs, analyse errors with LLM, "
            "and update dc_scheduled_runs.json."
        )
    )
    parser.add_argument(
        "-k",
        "--llm_apikey",
        required=True,
        help="IBM watsonx project API key for the foundation model.",
    )
    args = parser.parse_args()

    ibm_api_key = os.environ.get("IBM_CLOUD_API_KEY", "")
    if not ibm_api_key:
        print(
            "ERROR: IBM_CLOUD_API_KEY environment variable is not set.\n"
            "  export IBM_CLOUD_API_KEY=<your-ibm-cloud-api-key>",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.llm_apikey:
        print(
            "ERROR: LLM API key cannot be empty.\n"
            "Run the script using:\n"
            "  python fetch_dc_scheduled_runs_logs.py -k <LLM_APIKEY>",
            file=sys.stderr,
        )
        return

    logs_summary = get_schematics_run_logs(
        ibm_api_key=ibm_api_key,
        json_file=json_file,
        llm_apikey=args.llm_apikey,
    )

    if logs_summary:
        existing = load_existing_runs(json_file)
        existing.extend(logs_summary)
        save_scheduled_runs_json(existing, json_file)
    else:
        print(f"No new logs to update in json file: {json_file}")


if __name__ == "__main__":
    main()