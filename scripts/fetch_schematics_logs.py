"""
fetch_schematics_logs.py
------------------------
Fetches the latest Terraform execution log from IBM Cloud Schematics workspaces
using the Schematics REST API.

Usage:
    python3 scripts/fetch_schematics_logs.py

Required environment variables:
    IBM_CLOUD_API_KEY   - Your IBM Cloud API key

Optional environment variables:
    SCHEMATICS_WS_ID    - Single workspace ID (e.g. us-south.workspace.myws.abc12345)
                          If NOT set, the script lists all workspaces and prompts you to pick one.
    SCHEMATICS_REGION   - API region prefix: us | eu | uk  (default: us)
    LOG_OUTPUT_DIR      - Directory to save logs in bulk mode (default: ./data/apply_logs)

Modes:
    Single workspace  — set SCHEMATICS_WS_ID, or leave unset to pick interactively.
    Bulk (all)        — set SCHEMATICS_WS_ID=ALL to fetch logs for every workspace
                        in the account (all statuses, latest action of any type).
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Configuration — read from environment variables
# ---------------------------------------------------------------------------
API_KEY        = os.environ.get("IBM_CLOUD_API_KEY", "")
WORKSPACE_ID   = os.environ.get("SCHEMATICS_WS_ID", "")
REGION         = os.environ.get("SCHEMATICS_REGION", "us").lower()
LOG_OUTPUT_DIR = os.environ.get("LOG_OUTPUT_DIR", "data/apply_logs")

IAM_TOKEN_URL      = "https://iam.cloud.ibm.com/identity/token"
SCHEMATICS_BASE_URL = f"https://{REGION}.schematics.cloud.ibm.com"

# SCHEMATICS_WS_ID=ALL triggers bulk mode
BULK_MODE = WORKSPACE_ID.strip().upper() == "ALL"


# ---------------------------------------------------------------------------
# Step 1 — Get IAM Bearer token
# ---------------------------------------------------------------------------
def get_iam_token(api_key: str) -> str:
    """Exchange an IBM Cloud API key for an IAM Bearer token."""
    print("→ Fetching IAM token ...")
    response = requests.post(
        IAM_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise ValueError("IAM response did not contain an access_token.")
    print("✓ IAM token obtained.")
    return token


# ---------------------------------------------------------------------------
# Step 2 — List all workspaces
# ---------------------------------------------------------------------------
def list_workspaces(token: str) -> list[dict]:
    """
    Return all Schematics workspaces visible to this token.
    Handles pagination automatically.
    """
    print("→ Listing all Schematics workspaces ...")

    url = f"{SCHEMATICS_BASE_URL}/v1/workspaces"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Auth-Refresh-Token": token,
    }

    workspaces = []
    offset = 0
    limit = 100  # maximum page size allowed by the API

    while True:
        response = requests.get(
            url,
            headers=headers,
            params={"offset": offset, "limit": limit},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        page = data.get("workspaces", [])
        workspaces.extend(page)

        if len(page) < limit:
            break
        offset += limit

    print(f"✓ {len(workspaces)} workspace(s) found.")
    return workspaces


def print_workspace_table(workspaces: list[dict]) -> None:
    """Print a formatted table of workspaces."""
    print(f"\n  {'#':<4}  {'Name':<40}  {'Status':<20}  {'ID'}")
    print(f"  {'-'*4}  {'-'*40}  {'-'*20}  {'-'*50}")
    for idx, ws in enumerate(workspaces, start=1):
        name   = ws.get("name", "—")[:40]
        status = ws.get("status", "—")[:20]
        ws_id  = ws.get("id", "—")
        print(f"  {idx:<4}  {name:<40}  {status:<20}  {ws_id}")
    print()


def select_workspace(token: str) -> str:
    """
    Fetch all workspaces and prompt the user to pick one interactively.
    Returns the chosen workspace ID.
    """
    workspaces = list_workspaces(token)

    if not workspaces:
        raise RuntimeError(
            "No Schematics workspaces found in this region. "
            "Try a different SCHEMATICS_REGION (us / eu / uk)."
        )

    print_workspace_table(workspaces)

    while True:
        try:
            choice = input(f"Enter workspace number [1-{len(workspaces)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(workspaces):
                chosen_id   = workspaces[idx]["id"]
                chosen_name = workspaces[idx].get("name", chosen_id)
                print(f"✓ Selected: {chosen_name} ({chosen_id})\n")
                return chosen_id
            print(f"  Please enter a number between 1 and {len(workspaces)}.")
        except (ValueError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)


# ---------------------------------------------------------------------------
# Step 3 — Get latest action for a workspace
# ---------------------------------------------------------------------------
def get_latest_action(workspace_id: str, token: str):
    """
    Return the most recent action for the given workspace, or None if none exist.
    """
    url = f"{SCHEMATICS_BASE_URL}/v1/workspaces/{workspace_id}/actions"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Auth-Refresh-Token": token,
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    actions = response.json().get("actions", [])

    if not actions:
        return None

    def parse_time(action: dict) -> datetime:
        ts = action.get("performed_at", "")
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return datetime.min

    return sorted(actions, key=parse_time, reverse=True)[0]


# ---------------------------------------------------------------------------
# Step 4 — Fetch log via log_url from the action response
# ---------------------------------------------------------------------------
def fetch_action_log(action: dict, token: str) -> str:
    """
    Extract log_url from the action's templates list and fetch the log from it.
    The action response looks like:
      { "templates": [ { "log_url": "https://...", ... } ] }
    """
    templates = action.get("templates", [])
    if not templates:
        raise RuntimeError(
            f"Action '{action.get('action_id')}' has no templates — cannot find log_url."
        )

    log_url = templates[0].get("log_url", "")
    if not log_url:
        raise RuntimeError(
            f"Action '{action.get('action_id')}' template has no log_url field."
        )

    print(f"   log_url : {log_url}")

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Auth-Refresh-Token": token,
    }
    response = requests.get(log_url, headers=headers, timeout=60)
    response.raise_for_status()
    return response.text


# ---------------------------------------------------------------------------
# Step 5 — Save log to file
# ---------------------------------------------------------------------------
def save_log(log_text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(log_text, encoding="utf-8")
    print(f"   ✓ Saved → {output_path}")


# ---------------------------------------------------------------------------
# Single-workspace flow
# ---------------------------------------------------------------------------
def run_single(token: str, workspace_id: str) -> None:
    print(f"\n  Workspace : {workspace_id}\n")

    action = get_latest_action(workspace_id, token)
    if action is None:
        raise RuntimeError(
            "No actions found for this workspace. Has it ever been applied/planned?"
        )

    print(
        f"✓ Latest action:\n"
        f"   ID     : {action.get('action_id')}\n"
        f"   Type   : {action.get('name')}\n"
        f"   Status : {action.get('status')}\n"
        f"   Time   : {action.get('performed_at')}\n"
    )

    log_text = fetch_action_log(action, token)
    print(f"✓ Log retrieved ({len(log_text):,} characters).")

    print(f"\n{'='*60}")
    print(f"  Terraform Log Output")
    print(f"{'='*60}\n")
    print(log_text)


# ---------------------------------------------------------------------------
# fetch_all_workspace_logs — importable by other scripts
# ---------------------------------------------------------------------------
def fetch_all_workspace_logs(token: str) -> list:
    """
    Fetch the latest log text for every workspace in the account.

    Returns a list of dicts — one per workspace that had a retrievable log:
        {
            "ws_id":        str,   # workspace ID
            "ws_name":      str,   # workspace name
            "ws_status":    str,   # ACTIVE / INACTIVE / etc.
            "action_id":    str,
            "action_type":  str,   # WORKSPACE_APPLY / WORKSPACE_PLAN / etc.
            "action_status": str,  # COMPLETED / FAILED / etc.
            "performed_at": str,   # ISO-8601 timestamp
            "log_text":     str,   # raw Terraform log
        }

    Workspaces with no actions or HTTP errors are silently skipped.
    This function does NOT write anything to disk.
    """
    workspaces = list_workspaces(token)
    if not workspaces:
        raise RuntimeError(
            "No Schematics workspaces found in this region. "
            "Try a different SCHEMATICS_REGION (us / eu / uk)."
        )

    print_workspace_table(workspaces)
    print(f"→ Fetching logs for {len(workspaces)} workspace(s) ...\n")

    log_entries = []

    for ws in workspaces:
        ws_id     = ws.get("id", "")
        ws_name   = ws.get("name", ws_id)
        ws_status = ws.get("status", "—")

        print(f"  [{ws_name}] ({ws_status})")

        try:
            action = get_latest_action(ws_id, token)

            if action is None:
                print(f"   ⚠ No actions found — skipping.\n")
                continue

            action_id     = action["action_id"]
            action_type   = action.get("name", "—")
            action_status = action.get("status", "—")
            performed_at  = action.get("performed_at", "")

            print(f"   Action : {action_type} | {action_status} | {performed_at}")

            log_text = fetch_action_log(action, token)
            print(f"   ✓ {len(log_text):,} chars retrieved.\n")

            log_entries.append({
                "ws_id":         ws_id,
                "ws_name":       ws_name,
                "ws_status":     ws_status,
                "action_id":     action_id,
                "action_type":   action_type,
                "action_status": action_status,
                "performed_at":  performed_at,
                "log_text":      log_text,
            })

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "?"
            print(f"   ✗ HTTP {status_code} — skipping.\n")

    print(f"✓ {len(log_entries)}/{len(workspaces)} logs retrieved.")
    return log_entries


# ---------------------------------------------------------------------------
# Bulk-workspace flow (standalone — saves logs to disk)
# ---------------------------------------------------------------------------
def run_bulk(token: str) -> None:
    """
    Fetch the latest log for every workspace and save each to LOG_OUTPUT_DIR.
    Prints a summary table at the end.
    """
    log_entries = fetch_all_workspace_logs(token)

    out_dir = Path(LOG_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"→ Saving {len(log_entries)} log(s) to {out_dir}/\n")

    results = []
    for entry in log_entries:
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in entry["ws_name"])
        filename  = out_dir / f"{safe_name}__{entry['action_id']}.log"
        save_log(entry["log_text"], filename)
        results.append({**entry, "file": str(filename)})

    # Summary table
    print(f"\n{'='*60}")
    print(f"  Bulk Fetch Summary")
    print(f"{'='*60}")
    print(f"  {'Workspace':<35}  {'WS Status':<12}  {'Job Type':<20}  {'Job Status':<15}  {'File'}")
    print(f"  {'-'*35}  {'-'*12}  {'-'*20}  {'-'*15}  {'-'*40}")
    for r in results:
        print(
            f"  {r['ws_name'][:35]:<35}  {r['ws_status'][:12]:<12}  "
            f"{r['action_type'][:20]:<20}  {r['action_status'][:15]:<15}  {r['file']}"
        )
    print(f"\n  {len(results)} log(s) saved to {out_dir}/")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    if not API_KEY:
        print("ERROR: Missing required environment variable: IBM_CLOUD_API_KEY", file=sys.stderr)
        print("  export IBM_CLOUD_API_KEY=<your-api-key>", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  IBM Cloud Schematics Log Fetcher")
    print(f"{'='*60}")
    print(f"  Region : {REGION}")
    print(f"  Mode   : {'BULK (all workspaces)' if BULK_MODE else 'Single workspace'}")
    print(f"{'='*60}\n")

    try:
        token = get_iam_token(API_KEY)

        if BULK_MODE:
            run_bulk(token)
        else:
            workspace_id = WORKSPACE_ID if WORKSPACE_ID else select_workspace(token)
            run_single(token, workspace_id)

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        body   = e.response.text if e.response is not None else ""
        print(f"\nHTTP ERROR {status}: {e}", file=sys.stderr)
        print(f"Response body: {body}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        print(f"\nCONNECTION ERROR: Could not reach the API. Check SCHEMATICS_REGION.\n{e}", file=sys.stderr)
        sys.exit(1)
    except (RuntimeError, ValueError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
