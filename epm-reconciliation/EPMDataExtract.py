"""
================================================================================
Script Name : EPMDataExtract.py
Author      : Vikram Kumar (Oracle EPM Architect)
Compiled and Tested By : Vikram Kumar
Last Tested : 2026-08-03
Version     : 1.0
================================================================================
PURPOSE
Exports data from an Oracle EPM Cloud FreeForm / Planning application using
the exportdataslice REST API, then normalizes the result into a flat JSON
structure (region/period/value) for downstream reconciliation against a
source-of-truth system (see SourceOfTruthExtract.py and reconcile.py in this
same repo).

>>> BEFORE YOU RUN THIS <<<
Every block below marked  # >>> UPDATE THIS <<<  contains values that are
specific to YOUR EPM environment (server, application, dimensions, members).
Nothing else in the script needs to change for a typical FreeForm/Planning
ASO cube -- the fiscal calendar math, API call, and normalization logic are
all generic.

QUICK TEST (no EPM connection required):
    python EPMDataExtract.py --dry-run --weeks 4

MONTH-END / CLOSE-WINDOW USAGE
Many organizations don't finalize month-end data in a single load -- it
lands incrementally over a close window, commonly described as "business
day 1 through business day 5" (BD1-BD5) or "calendar day 1 through 10."
During that window the same day's numbers can change every time new data
is loaded, which is exactly when reconciliation is most valuable -- it
catches discrepancies *while* there's still time to fix them, rather than
after the books are closed.

If you're using this in that context:
  - Schedule EPMDataExtract.py, SourceOfTruthExtract.py, and reconcile.py
    to run once per business day throughout the close window (Windows Task
    Scheduler, cron, Airflow, whatever your shop uses), not just once a week.
  - Use a small --weeks value (1-2) during the close window instead of a
    long trailing window -- you mainly care about the period that's still
    settling, not weeks that are already final.
  - See reconcile.py's RECON_CLOSE_DAY setting to label each day's report
    (e.g. "BD3") so multiple same-day-of-week emails during close are easy
    to tell apart in your inbox.

DISCLAIMER
This script is shared for educational purposes as a working example of an
EPM Cloud data extraction pattern. It is provided "as is," without warranty
of any kind, express or implied. Test thoroughly in a non-production
environment before pointing it at any live system. The author assumes no
responsibility for data loss, service disruption, or any other consequence
of using or modifying this script. You are responsible for securing your
own credentials (never commit passwords or API keys to source control) and
for complying with your organization's change-management and security
policies.
================================================================================
"""

import os
import re
import sys
import json
import random
import argparse
import requests
from requests.auth import HTTPBasicAuth
from datetime import date, timedelta, datetime, timezone

# =====================================
# CLI ARGS (parsed once, used throughout)
# =====================================
def parse_args():
    parser = argparse.ArgumentParser(description="EPM FreeForm export/reconciliation window")
    parser.add_argument("--weeks", type=int, help="Number of trailing fiscal weeks to pull")
    parser.add_argument("--months", type=int, help="Number of trailing fiscal periods (months) to pull")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip the real EPM API call and use generated mock data instead. "
             "Lets you test the fiscal-calendar math, normalization, and file "
             "output end-to-end with no server, credentials, or network access."
    )
    return parser.parse_args()


ARGS = parse_args()

# =====================================
# 1. EPM CONNECTION CONFIG
# =====================================
# >>> UPDATE THIS <<<
# Point these at your own EPM Cloud environment. Never hardcode
# credentials in the script itself — use environment variables
# (or a secrets manager) so this file stays safe to publish/share.
SERVER_URL  = os.environ.get("EPM_SERVER_URL",  "https://<your-pod>.epm.<region>.ocs.oraclecloud.com")
USERNAME    = os.environ.get("EPM_USERNAME",    "<service-account-username>")
PASSWORD    = os.environ.get("EPM_PASSWORD",    "")  # set via env var, do NOT hardcode
APPLICATION = os.environ.get("EPM_APPLICATION", "<your-application-name>")
PLAN_TYPE   = os.environ.get("EPM_PLAN_TYPE",   "<your-plan-type>")   # e.g. an ASO cube name

if not PASSWORD and not ARGS.dry_run:
    sys.exit("ERROR: Set the EPM_PASSWORD environment variable before running (or use --dry-run to test without EPM access).")

# =====================================
# 2. FISCAL CALENDAR CONFIG
# =====================================
# >>> UPDATE THIS <<<
# Adjust to match your organization's fiscal calendar. This example
# uses a standard retail 5-4-4 pattern (13 four/five-week periods per
# quarter), but the get_fiscal() logic below will work for any
# 5-4-4-style calendar once you set the correct start date and pattern.
#
# NOTE: FISCAL_YEAR_START, PERIOD_WEEK_PATTERN, and NUM_PERIODS are
# hardcoded here for simplicity, but in a real EPM deployment these
# should live as Substitution Variables on your EPM application
# (Application > Substitution Variables) — e.g. &FiscalYearStart,
# &CurrMonth, &CurrYear — rather than baked into the script. That way
# the calendar rolls forward automatically as your admins maintain the
# app, and this script (or an EPMAutomate `getVariables` / REST call)
# just reads the values at runtime instead of needing a code change
# every fiscal year.
FISCAL_YEAR_START = date(2025, 12, 29)   # first day of fiscal year/period 1
PERIOD_WEEK_PATTERN = [5, 4, 4]          # weeks-per-period pattern, repeats every quarter
NUM_PERIODS = 12                         # total fiscal periods in a year

# =====================================
# 3. DIMENSION / MEMBER CONFIG
# =====================================
# >>> UPDATE THIS <<<
# These reflect the dimension names and member names in YOUR
# application outline. Update the dimension names, POV members,
# row members, and the measure(s) you want to export.

POV_DIMENSIONS = ["Year", "Currency", "Version", "Scenario"]   # example generic POV dims
POV_MEMBERS    = [["FY26"], ["Local"], ["Working"], ["Actual"]]  # one member list per POV dim

TIME_DIMENSION = "Time"   # the dimension driving your fiscal week columns

ROW_DIMENSIONS = ["Entity", "Account"]        # example: your entity + measure dims
ROW_ENTITY_MEMBERS  = ["Entity A", "Entity B", "Entity C"]   # replace with your real entities
ROW_MEASURE_MEMBERS = ["Measure Name"]                        # replace with your real measure(s)

# Map each raw entity member name (as it appears in EPM) to a short,
# normalized key used in the output records. Update to match your
# own entity list — this keeps downstream files clean and generic.
# >>> UPDATE THIS <<<
ENTITY_MAP = {
    "Entity A": "entity_a",
    "Entity B": "entity_b",
    "Entity C": "entity_c",
}

# =====================================
# 4. OUTPUT FILE NAMES
# =====================================
RAW_OUTPUT_FILE        = "exportdaily.json"
NORMALIZED_OUTPUT_FILE = "exportdaily_normalized.json"

# =====================================
# FISCAL CALCULATION (generic — no edits needed)
# =====================================
def get_fiscal(cal_date, fiscal_start=FISCAL_YEAR_START, pattern=PERIOD_WEEK_PATTERN, num_periods=NUM_PERIODS):
    """Convert a calendar date into a 'P##_WK#' fiscal period/week label."""
    total_days = (cal_date - fiscal_start).days
    total_weeks = (total_days // 7) + 1
    remaining_weeks = total_weeks - 1
    fiscal_month = 1

    while True:
        if fiscal_month > num_periods:
            fiscal_month = num_periods
        weeks_in_period = pattern[(fiscal_month - 1) % len(pattern)]

        if fiscal_month == num_periods:
            return f"P{num_periods:02d}_WK{remaining_weeks + 1}"

        if remaining_weeks < weeks_in_period:
            return f"P{fiscal_month:02d}_WK{remaining_weeks + 1}"

        remaining_weeks -= weeks_in_period
        fiscal_month += 1


def normalize_period(period: str) -> str:
    """Strip leading zeros so period labels compare consistently."""
    period = period.strip().upper()
    match = re.match(r'P0*(\d+)_WK0*(\d+)', period)
    if match:
        return f"P{match.group(1)}_WK{match.group(2)}"
    print(f"WARNING: Unrecognized period format '{period}'")
    return period


def normalize_entity(entity: str) -> str:
    """Map a raw EPM entity/member name to a normalized key via ENTITY_MAP."""
    entity = entity.strip()
    mapped = ENTITY_MAP.get(entity)
    if not mapped:
        print(f"WARNING: Unmapped entity '{entity}' — add it to ENTITY_MAP")
        return entity.lower().replace(" ", "_")
    return mapped

# =====================================
# RECON WINDOW — how far back to pull
# =====================================
# Instead of hardcoding a trailing-week count, this is asked for at
# runtime — either via CLI flags (for scheduled/cron use) or an
# interactive prompt (for ad-hoc runs). This makes the same script
# reusable for a quick 4-week check or a full 52-week rebuild without
# any code edits.
def get_recon_window():
    if ARGS.weeks:
        return ARGS.weeks
    if ARGS.months:
        # Fiscal periods aren't a fixed length (5-4-4 pattern), so this
        # converts months -> weeks using the average period length from
        # PERIOD_WEEK_PATTERN. Good enough for a trailing window; if you
        # need exact period boundaries, pull &NUM_PERIODS-style
        # substitution variables and sum the real period lengths instead.
        avg_weeks_per_period = sum(PERIOD_WEEK_PATTERN) / len(PERIOD_WEEK_PATTERN)
        return round(ARGS.months * avg_weeks_per_period)

    # No CLI args given -> fall back to an interactive prompt.
    # (In --dry-run mode with no args, default to 14 weeks instead of
    # prompting, so the script can be tested non-interactively too.)
    if ARGS.dry_run:
        print("No --weeks/--months given with --dry-run; defaulting to 14 weeks.")
        return 14

    while True:
        raw = input("How many weeks of data do you want to reconcile? (e.g. 14): ").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("Please enter a positive whole number of weeks.")


NUM_TRAILING_WEEKS = get_recon_window()

# =====================================
# GENERATE TRAILING FISCAL WEEK LABELS
# =====================================
today = date.today()
base_date = today - timedelta(weeks=1)  # last fully completed week

members = []
for i in range(1, NUM_TRAILING_WEEKS + 1):
    calc_date = base_date - timedelta(weeks=(NUM_TRAILING_WEEKS - i))
    members.append(get_fiscal(calc_date))

column_members = [members]

print(f"Reconciliation window: last {NUM_TRAILING_WEEKS} fiscal week(s) — {members[0]} through {members[-1]}")

# =====================================
# MOCK MODE — for testing without EPM access
# =====================================
# Generates a fake response in the exact same shape the real
# exportdataslice API returns, using whatever entities/measures/
# periods are set in the config above. This lets you sanity-check
# the fiscal-week math, normalization, and output files without a
# server, credentials, or network access. Run with:
#   python EPMDaily.py --dry-run --weeks 4
def build_mock_response():
    rows = []
    for entity in ROW_ENTITY_MEMBERS:
        for measure in ROW_MEASURE_MEMBERS:
            rows.append({
                "headers": [entity, measure],
                "data": [round(random.uniform(50000, 250000), 2) for _ in members]
            })
    return {
        "columns": [members],
        "rows": rows
    }


# =====================================
# EPM EXPORT (generic — no edits needed below this line)
# =====================================
api_url = f"{SERVER_URL}/HyperionPlanning/rest/v3/applications/{APPLICATION}/plantypes/{PLAN_TYPE}/exportdataslice"


def export_dataslice():
    response = None
    try:
        if ARGS.dry_run:
            print(f"[DRY RUN] Skipping real EPM API call — generating mock data for "
                  f"{APPLICATION}.{PLAN_TYPE} instead.")
            data = build_mock_response()
        else:
            print(f"Connecting to EPM to export data slice from {APPLICATION}.{PLAN_TYPE}...")
            payload = {
                "exportPlanningData": False,
                "gridDefinition": {
                    "suppressMissingBlocks": True,
                    "suppressMissingRows": True,
                    "suppressMissingColumns": False,
                    "pov": {
                        "dimensions": POV_DIMENSIONS,
                        "members": POV_MEMBERS
                    },
                    "columns": [
                        {
                            "dimensions": [TIME_DIMENSION],
                            "members": column_members
                        }
                    ],
                    "rows": [
                        {
                            "dimensions": ROW_DIMENSIONS,
                            "members": [
                                ROW_ENTITY_MEMBERS,
                                ROW_MEASURE_MEMBERS
                            ]
                        }
                    ]
                }
            }

            response = requests.post(
                api_url,
                auth=HTTPBasicAuth(USERNAME, PASSWORD),
                headers={"Content-Type": "application/json"},
                json=payload
            )
            response.raise_for_status()
            data = response.json()

        for row in data.get("rows", []):
            row["data"] = [0 if v is None or v == "" else v for v in row["data"]]

        if "rows" in data:
            row_count = len(data["rows"])
            print(f"Success! Retrieved {row_count} rows of data.")

            with open(RAW_OUTPUT_FILE, 'w') as f:
                json.dump(data, f, indent=4)
            print(f"Raw data saved to {RAW_OUTPUT_FILE}")

            columns = data.get("columns", [])
            if columns and isinstance(columns[0], list):
                columns = [item for sublist in columns for item in sublist]

            records = []
            for row in data.get("rows", []):
                headers = row.get("headers", [])
                values = row.get("data", [])
                entity = headers[0] if len(headers) > 0 else "UNKNOWN"

                for period, value in zip(columns, values):
                    records.append({
                        "region": normalize_entity(entity),
                        "period": normalize_period(period),
                        "net_sales": round(float(value), 2)
                    })

            normalized_output = {
                "source": "EPM",
                "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "row_count": len(records),
                "data": records
            }

            with open(NORMALIZED_OUTPUT_FILE, 'w') as f:
                json.dump(normalized_output, f, indent=2)
            print(f"Normalized data saved to: {NORMALIZED_OUTPUT_FILE}")

        else:
            print("API call was successful, but no 'rows' were found in the response.")
            print("Response:", json.dumps(data, indent=2))

    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error occurred: {err}")
        if response is not None and response.text:
            print(f"EPM Error Details: {response.text}")
    except Exception as err:
        print(f"An error occurred: {err}")


if __name__ == "__main__":
    export_dataslice()
