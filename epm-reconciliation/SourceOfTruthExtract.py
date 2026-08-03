"""
================================================================================
Script Name : SourceOfTruthExtract.py
Author      : Vikram Kumar (Oracle EPM Architect)
Compiled and Tested By : Vikram Kumar
Last Tested : 2026-08-03
Version     : 1.0
================================================================================
PURPOSE
Pulls comparison data from whatever your "source of truth" system is, and
normalizes it into the same region/period/value schema that
EPMDataExtract.py produces -- so the two can be reconciled directly by
reconcile.py in this same repo.

The idea: the reconciliation logic doesn't care whether your source of
truth is a BigQuery warehouse, a Snowflake warehouse, a flat file export
from Oracle FCCS, or a SQL query against SAP/JDE/Oracle ERP. It only cares
that you end up with rows shaped like:
    { "region": "...", "period": "...", "net_sales": 12345.67 }

This script picks HOW to pull that data based on SOURCE_TYPE, so the same
script works no matter what sits behind your source of truth.

>>> BEFORE YOU RUN THIS <<<
Set SOURCE_TYPE (below, or via the SOT_SOURCE_TYPE env var) to match your
environment, then fill in the config block for that source type. Every
block marked  # >>> UPDATE THIS <<<  is specific to your setup.

QUICK TEST (no external connection required):
    python SourceOfTruthExtract.py --dry-run --weeks 4

MONTH-END / CLOSE-WINDOW USAGE
If your organization's month-end close spans several days -- often called
"business day 1 through 5" (BD1-BD5) or "calendar day 1 through 10" --
your source-of-truth data (BigQuery, a warehouse, an ERP export) is likely
still settling during that window too, same as the EPM side. Run this
script once per business day alongside EPMDataExtract.py during close,
using a short --weeks value (1-2) rather than a long trailing window, so
each day's reconciliation focuses on the period that's still open rather
than re-checking weeks that already closed.

DISCLAIMER
This script is shared for educational purposes as a working example of a
generic data-extraction pattern. It is provided "as is," without warranty
of any kind, express or implied. Test thoroughly in a non-production
environment before pointing it at any live system. The author assumes no
responsibility for data loss, service disruption, or any other consequence
of using or modifying this script. You are responsible for securing your
own credentials (never commit passwords, keys, or connection strings to
source control) and for complying with your organization's change-
management and security policies.
================================================================================
"""

import os
import re
import sys
import json
import random
import argparse
from datetime import date, timedelta, datetime, timezone

# =====================================
# CLI ARGS
# =====================================
def parse_args():
    parser = argparse.ArgumentParser(description="Source-of-truth data extraction")
    parser.add_argument("--weeks", type=int, help="Number of trailing fiscal weeks to pull")
    parser.add_argument("--months", type=int, help="Number of trailing fiscal periods (months) to pull")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip the real source connection and use generated mock data instead."
    )
    return parser.parse_args()


ARGS = parse_args()

# =====================================
# 1. SOURCE TYPE
# =====================================
# >>> UPDATE THIS <<<
# Which system holds your source-of-truth data? Pick one:
#   "flatfile"   — a CSV/Excel export dropped in a folder (from any
#                  system — Oracle FCCS, SAP, JDE, a manual export, etc.)
#   "sql"        — any system reachable via a SQL/ODBC driver:
#                  Oracle ERP, JDE, SAP HANA, SQL Server, Postgres,
#                  Snowflake (via its SQLAlchemy dialect), etc.
#   "bigquery"   — Google BigQuery specifically (native client, no SQLAlchemy needed)
#   "snowflake"  — Snowflake specifically (native connector)
SOURCE_TYPE = os.environ.get("SOT_SOURCE_TYPE", "flatfile")

OUTPUT_FILE = os.environ.get("SOT_OUTPUT_FILE", "sot_output.json")

# =====================================
# 2. FISCAL CALENDAR CONFIG
# =====================================
# >>> UPDATE THIS <<<
# Should match the same calendar used in EPMDataExtract.py so periods
# line up for reconciliation. As there, these ideally live as EPM
# Substitution Variables rather than hardcoded constants.
FISCAL_YEAR_START = date(2025, 12, 29)
PERIOD_WEEK_PATTERN = [5, 4, 4]
NUM_PERIODS = 12

# =====================================
# 3. ENTITY / REGION MAPPING
# =====================================
# >>> UPDATE THIS <<<
# Map however your source system labels regions/entities to the same
# normalized keys used in EPMDataExtract.py, so both sides reconcile
# on identical region values.
ENTITY_MAP = {
    "Entity A": "entity_a",
    "Entity B": "entity_b",
    "Entity C": "entity_c",
}

# =====================================
# 4. SOURCE-SPECIFIC CONFIG
# =====================================
# >>> UPDATE THIS <<<
# Only the block matching your SOURCE_TYPE needs to be filled in —
# the others are ignored at runtime.

# --- flatfile ---
FLATFILE_PATH        = os.environ.get("SOT_FLATFILE_PATH", "source_export.csv")
FLATFILE_REGION_COL  = os.environ.get("SOT_FLATFILE_REGION_COL", "region")
FLATFILE_PERIOD_COL  = os.environ.get("SOT_FLATFILE_PERIOD_COL", "period")   # e.g. already "P01_WK1"
FLATFILE_DATE_COL    = os.environ.get("SOT_FLATFILE_DATE_COL", "")           # OR a raw date column, converted via get_fiscal()
FLATFILE_VALUE_COL   = os.environ.get("SOT_FLATFILE_VALUE_COL", "net_sales")

# --- sql (generic: Oracle ERP, JDE, SAP HANA, SQL Server, Postgres, Snowflake-via-SQLAlchemy, etc.) ---
SQL_CONNECTION_STRING = os.environ.get("SOT_SQL_CONN_STRING", "")  # e.g. "oracle+cx_oracle://user:pass@host:1521/service"
SQL_QUERY = os.environ.get("SOT_SQL_QUERY", """
    SELECT region, period, net_sales
    FROM your_source_table
    WHERE fiscal_week_end_date >= :start_date
""")

# --- bigquery ---
BQ_KEY_PATH = os.environ.get("SOT_BQ_KEY_PATH", "/path/to/service-account.json")
BQ_QUERY = os.environ.get("SOT_BQ_QUERY", """
    SELECT region, time AS period, net_sales
    FROM `your_project.your_dataset.your_table`
    WHERE fiscal_wk_end_date >= @start_date
""")

# --- snowflake ---
SNOWFLAKE_ACCOUNT   = os.environ.get("SOT_SNOWFLAKE_ACCOUNT", "")
SNOWFLAKE_USER      = os.environ.get("SOT_SNOWFLAKE_USER", "")
SNOWFLAKE_PASSWORD  = os.environ.get("SOT_SNOWFLAKE_PASSWORD", "")
SNOWFLAKE_WAREHOUSE = os.environ.get("SOT_SNOWFLAKE_WAREHOUSE", "")
SNOWFLAKE_DATABASE  = os.environ.get("SOT_SNOWFLAKE_DATABASE", "")
SNOWFLAKE_SCHEMA    = os.environ.get("SOT_SNOWFLAKE_SCHEMA", "")
SNOWFLAKE_QUERY = os.environ.get("SOT_SNOWFLAKE_QUERY", """
    SELECT region, period, net_sales
    FROM your_table
    WHERE fiscal_week_end_date >= %(start_date)s
""")

# =====================================
# FISCAL CALCULATION (generic — matches EPMDataExtract.py)
# =====================================
def get_fiscal(cal_date, fiscal_start=FISCAL_YEAR_START, pattern=PERIOD_WEEK_PATTERN, num_periods=NUM_PERIODS):
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
    period = str(period).strip().upper()
    match = re.match(r'P0*(\d+)_WK0*(\d+)', period)
    if match:
        return f"P{match.group(1)}_WK{match.group(2)}"
    print(f"WARNING: Unrecognized period format '{period}'")
    return period


def normalize_entity(entity: str) -> str:
    entity = str(entity).strip()
    mapped = ENTITY_MAP.get(entity)
    if not mapped:
        print(f"WARNING: Unmapped entity '{entity}' — add it to ENTITY_MAP")
        return entity.lower().replace(" ", "_")
    return mapped

# =====================================
# RECON WINDOW (mirrors EPMDataExtract.py)
# =====================================
def get_recon_window():
    if ARGS.weeks:
        return ARGS.weeks
    if ARGS.months:
        avg_weeks_per_period = sum(PERIOD_WEEK_PATTERN) / len(PERIOD_WEEK_PATTERN)
        return round(ARGS.months * avg_weeks_per_period)
    if ARGS.dry_run:
        print("No --weeks/--months given with --dry-run; defaulting to 14 weeks.")
        return 14
    while True:
        raw = input("How many weeks of data do you want to pull? (e.g. 14): ").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("Please enter a positive whole number of weeks.")


NUM_TRAILING_WEEKS = get_recon_window()
today = date.today()
base_date = today - timedelta(weeks=1)
start_date = base_date - timedelta(weeks=NUM_TRAILING_WEEKS - 1)
window_labels = [get_fiscal(base_date - timedelta(weeks=(NUM_TRAILING_WEEKS - i))) for i in range(1, NUM_TRAILING_WEEKS + 1)]

print(f"Pulling last {NUM_TRAILING_WEEKS} fiscal week(s) from source: {SOURCE_TYPE}")
print(f"Window: {window_labels[0]} through {window_labels[-1]} (calendar start: {start_date})")

# =====================================
# MOCK DATA (used by --dry-run, any SOURCE_TYPE)
# =====================================
def build_mock_records():
    records = []
    for entity in ENTITY_MAP.keys():
        for period in window_labels:
            records.append({
                "region": normalize_entity(entity),
                "period": normalize_period(period),
                "net_sales": round(random.uniform(50000, 250000), 2)
            })
    return records

# =====================================
# SOURCE ADAPTERS — one function per SOURCE_TYPE, each returns a
# list of {"region", "period", "net_sales"} dicts. Add a new adapter
# here for any other system (e.g. an EPM REST pull from Oracle FCCS,
# an API call to a SaaS finance tool, etc.) and register it in
# extract_data() below.
# =====================================
def extract_from_flatfile():
    import csv
    records = []
    # utf-8-sig strips a BOM if present (common when a CSV is saved via
    # PowerShell's Out-File, Excel, or Notepad) and is a harmless no-op
    # if there isn't one -- so this works regardless of how the file
    # was created.
    with open(FLATFILE_PATH, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if FLATFILE_PERIOD_COL in row and row.get(FLATFILE_PERIOD_COL):
                period = row[FLATFILE_PERIOD_COL]
            elif FLATFILE_DATE_COL and row.get(FLATFILE_DATE_COL):
                raw_date = datetime.strptime(row[FLATFILE_DATE_COL], "%Y-%m-%d").date()
                period = get_fiscal(raw_date)
            else:
                print(f"WARNING: Row missing both period and date column, skipping: {row}")
                continue

            records.append({
                "region": normalize_entity(row[FLATFILE_REGION_COL]),
                "period": normalize_period(period),
                "net_sales": round(float(row[FLATFILE_VALUE_COL]), 2)
            })
    return records


def extract_from_sql():
    # Generic catch-all for anything with a SQL/ODBC driver: Oracle ERP,
    # JDE, SAP HANA, SQL Server, Postgres, Snowflake (via its SQLAlchemy
    # dialect), etc. Requires: pip install sqlalchemy plus the relevant
    # DB driver (cx_Oracle, pyodbc, psycopg2, snowflake-sqlalchemy, ...).
    from sqlalchemy import create_engine, text
    if not SQL_CONNECTION_STRING:
        sys.exit("ERROR: Set SOT_SQL_CONN_STRING before using SOURCE_TYPE=sql")

    engine = create_engine(SQL_CONNECTION_STRING)
    with engine.connect() as conn:
        result = conn.execute(text(SQL_QUERY), {"start_date": start_date})
        rows = result.mappings().all()

    return [
        {
            "region": normalize_entity(row["region"]),
            "period": normalize_period(row["period"]),
            "net_sales": round(float(row["net_sales"]), 2)
        }
        for row in rows
    ]


def extract_from_bigquery():
    # Requires: pip install google-cloud-bigquery
    from google.cloud import bigquery
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(BQ_KEY_PATH)
    client = bigquery.Client(credentials=credentials, project=credentials.project_id)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("start_date", "DATE", start_date)]
    )
    results = client.query(BQ_QUERY, job_config=job_config).result()

    return [
        {
            "region": normalize_entity(row["region"]),
            "period": normalize_period(row["period"]),
            "net_sales": round(float(row["net_sales"]), 2)
        }
        for row in results
    ]


def extract_from_snowflake():
    # Requires: pip install snowflake-connector-python
    import snowflake.connector

    conn = snowflake.connector.connect(
        account=SNOWFLAKE_ACCOUNT,
        user=SNOWFLAKE_USER,
        password=SNOWFLAKE_PASSWORD,
        warehouse=SNOWFLAKE_WAREHOUSE,
        database=SNOWFLAKE_DATABASE,
        schema=SNOWFLAKE_SCHEMA,
    )
    try:
        cur = conn.cursor(snowflake.connector.DictCursor)
        cur.execute(SNOWFLAKE_QUERY, {"start_date": start_date})
        rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "region": normalize_entity(row["REGION"]),
            "period": normalize_period(row["PERIOD"]),
            "net_sales": round(float(row["NET_SALES"]), 2)
        }
        for row in rows
    ]


SOURCE_ADAPTERS = {
    "flatfile":  extract_from_flatfile,
    "sql":       extract_from_sql,
    "bigquery":  extract_from_bigquery,
    "snowflake": extract_from_snowflake,
}


def extract_data():
    if ARGS.dry_run:
        print(f"[DRY RUN] Skipping real connection to '{SOURCE_TYPE}' — generating mock data instead.")
        return build_mock_records()

    adapter = SOURCE_ADAPTERS.get(SOURCE_TYPE)
    if not adapter:
        sys.exit(f"ERROR: Unknown SOURCE_TYPE '{SOURCE_TYPE}'. "
                 f"Valid options: {', '.join(SOURCE_ADAPTERS.keys())}")

    print(f"Connecting to source-of-truth system ({SOURCE_TYPE})...")
    return adapter()


def main():
    try:
        records = extract_data()
        print(f"Success! Retrieved {len(records)} record(s).")

        normalized_output = {
            "source": SOURCE_TYPE,
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "row_count": len(records),
            "data": records
        }

        with open(OUTPUT_FILE, 'w') as f:
            json.dump(normalized_output, f, indent=2)
        print(f"Normalized data saved to: {OUTPUT_FILE}")

    except Exception as err:
        print(f"An error occurred: {err}")


if __name__ == "__main__":
    main()
