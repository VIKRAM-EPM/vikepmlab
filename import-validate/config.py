# =============================================================================
# config.py — EPM Pre-Load Import & Validate — Configuration Template
#
# HOW TO USE THIS FILE:
#   Sections 1, 2, and 3 are what you need to edit to point this pipeline at
#   YOUR data and YOUR Oracle EPM Cloud instance.
#   Sections 4, 5, and 6 have working defaults — only touch them if you need to.
# =============================================================================

import os


# =============================================================================
# SECTION 1 — Your Data Source   [EDIT THIS]
# =============================================================================

# Folder containing your CSV file(s)
CSV_DIR = r"C:\path\to\your\data"

# Filename pattern — e.g. "*.csv" to match every CSV in the folder,
# or a specific filename like "sales_data.csv"
CSV_GLOB = "*.csv"

# Delimiter used in your file (most CSVs use a comma)
CSV_DELIMITER = ","

# Map your CSV column headers (left) to your EPM dimension names (right).
#
# Oracle Planning applications include seven standard dimensions present in
# most Planning apps: Account, Entity, Scenario, Version, Period, Year, and
# Currency (Currency applies to multi-currency applications).
# Reference: https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/ebest/dimension_design_considerations.html
#
# Beyond these, every organization adds its own custom dimensions (Product,
# Location, Department, etc.) — these are unique to your application and
# can't be pre-filled, so add your own below.
#
# Example (from this repo's demo dataset — a FreeForm/custom-dimension case):
#   DIMENSION_MAP = {
#       "Category":       "Product_Category",
#       "Item":           "SKU",
#       "Payment Method": "Tender_Type",
#   }
DIMENSION_MAP = {
    # ---- Standard Planning dimensions [EDIT: map to your CSV headers] ----
    "your_csv_column_for_account":  "Account",
    "your_csv_column_for_entity":   "Entity",
    "your_csv_column_for_scenario": "Scenario",
    "your_csv_column_for_version":  "Version",
    "your_csv_column_for_period":   "Period",
    "your_csv_column_for_year":     "Year",
    "your_csv_column_for_currency": "Currency",   # remove if not multi-currency

    # ---- Your custom dimensions [EDIT: add as many as your app has] ----
    "your_csv_column_1": "Your_Custom_Dimension_1",
    "your_csv_column_2": "Your_Custom_Dimension_2",
}

# Numeric / fact columns to exclude — these hold data values, not dimension
# members, so they should NOT be validated against EPM.
# Example: ["Total Spent", "Price Per Unit", "Quantity"]
EXCLUDE_COLUMNS = ["your_numeric_column_1"]


# =============================================================================
# SECTION 2 — Your Oracle EPM Cloud Connection   [EDIT THIS]
# =============================================================================

# Your EPM Cloud REST base URL — found in Oracle's REST API documentation
# for your instance. Format:
#   https://<your-instance>.epm.<region>.ocs.oraclecloud.com/HyperionPlanning/rest/v3
EPM_BASE_URL = "https://your-instance.epm.us-region-1.ocs.oraclecloud.com/HyperionPlanning/rest/v3"

# Your EPM application name and plan type / cube name
EPM_APPLICATION = "YourAppName"
EPM_PLAN_TYPE   = "YourPlanType"

# Your EPM username (service account recommended over a personal login)
EPM_USERNAME = "your_service_account"

# Your EPM password is NOT stored here. Set it as an environment variable
# before running the script:
#
#   Windows (PowerShell):     $env:EPM_PASSWORD = "your-password"
#   Windows (Command Prompt): set EPM_PASSWORD=your-password
#   macOS / Linux:            export EPM_PASSWORD="your-password"
#
# Recommended: don't use your plain EPM password at all — encrypt it first
# using Oracle's built-in EPM Automate password encryption, then reference
# the encrypted value instead. See:
#   https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/cepma/epm_auto_encrypt.html
EPM_PASSWORD = os.environ.get("EPM_PASSWORD")

# REST call behavior — safe to leave as-is
EPM_REQUEST_TIMEOUT = 60   # seconds per dimension fetch
EPM_MAX_RETRIES     = 3    # retries on timeout / 5xx errors
EPM_RETRY_BACKOFF   = 2    # base seconds, doubles each retry (2s, 4s, 8s)


# =============================================================================
# SECTION 3 — Validation Mode   [EDIT THIS]
# =============================================================================

# "mock" — validates against a small built-in sample member set. No EPM
#          connection needed. Good for trying the pipeline out first.
# "live" — validates against your real EPM Cloud instance using Section 2
#          above. Requires EPM_PASSWORD to be set.
VALIDATION_MODE = "mock"


# =============================================================================
# SECTION 4 — DuckDB Performance Tuning   [defaults provided — optional]
# =============================================================================

DUCKDB_MEMORY_LIMIT = "4GB"                     # increase if you have more RAM
DUCKDB_THREADS      = 2                         # match your CPU core count
DUCKDB_TEMP_DIR     = r"C:\path\to\your\data\duckdb_tmp"


# =============================================================================
# SECTION 5 — Output Locations   [defaults provided — optional]
# =============================================================================

OUTPUT_DIR  = r"C:\path\to\your\data\output"
USE_PARQUET = False                              # True after running --convert once
PARQUET_DIR = r"C:\path\to\your\data\parquet"


# =============================================================================
# SECTION 6 — Email Notifications   [optional feature — safe to skip]
# =============================================================================

# Set to False to skip the email step entirely — the pipeline will still
# run Import + Validate and print results to the console.
SEND_EMAIL = False

SMTP_HOST     = "smtp.office365.com"   # or your own company's SMTP relay
SMTP_PORT     = 587
SMTP_USERNAME = "your_email@example.com"

# Not stored here — set as an environment variable, same pattern as EPM_PASSWORD:
#   $env:EPM_SMTP_PASSWORD = "your-password-or-app-password"
SMTP_PASSWORD = os.environ.get("EPM_SMTP_PASSWORD")

FROM_EMAIL = "your_email@example.com"
TO_EMAIL   = ["team@example.com"]
CC_EMAIL   = []

EMAIL_SUBJECT_PASS = "PASS — EPM Pre-Load Validation — All Members Valid"
EMAIL_SUBJECT_FAIL = "FAIL — EPM Pre-Load Validation — {invalid_count} Invalid Member(s) Found"