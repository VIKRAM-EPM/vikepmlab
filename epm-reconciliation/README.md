# EPM Reconciliation Pipeline

A three-script pipeline that pulls data from **Oracle EPM Cloud (FreeForm/Planning)**, pulls comparison data from whatever your **source of truth** system is, reconciles the two, and emails an HTML report — built to be dropped into any organization's environment with minimal changes.

Written up in more detail on [the accompanying blog post](#) *(link me here once published)*, including a live in-browser demo you can try without installing anything.

---

## What this is for

If you push data into Oracle EPM (Planning, FreeForm, etc.) from an upstream system — a data warehouse, an ERP, a flat file export — this pipeline checks that what landed in EPM actually matches what the source system says it should be, and alerts you by email when it doesn't.

```
EPMDataExtract.py          SourceOfTruthExtract.py
        │                            │
        ▼                            ▼
exportdaily_normalized.json   sot_output.json
        │                            │
        └──────────────┬─────────────┘
                        ▼
                  reconcile.py
                        │
                        ▼
        reconciliation_report.html + email
```

## The three scripts

| Script | Purpose |
|---|---|
| **`EPMDataExtract.py`** | Pulls data from Oracle EPM Cloud via the `exportdataslice` REST API and normalizes it. |
| **`SourceOfTruthExtract.py`** | Pulls comparison data from your source of truth — a flat file, a SQL database (Oracle ERP, JDE, SAP HANA, SQL Server, Postgres), BigQuery, or Snowflake — and normalizes it into the same schema. |
| **`reconcile.py`** | Loads both normalized files, classifies each region/period as `MATCH` / `VARIANCE` / `MISSING`, builds an HTML report, and emails it via SMTP. |

All three read config from environment variables with sensible placeholder defaults, so nothing here has any of the original author's environment baked in — every value you need to supply is marked `# >>> UPDATE THIS <<<` in the code.

---

## Quick start (no real connections required)

Every script has a `--dry-run` mode that generates realistic mock data instead of connecting to anything real. This is the fastest way to see the whole pipeline work end to end:

```bash
pip install requests pytz

python EPMDataExtract.py --dry-run --weeks 4
python SourceOfTruthExtract.py --dry-run --weeks 4
python reconcile.py
```

This produces `reconciliation_report.html` — open it in a browser to see the report. The email step will print a clear error if SMTP credentials aren't set (see below) rather than failing silently.

---

## Setting it up for real

### 1. `EPMDataExtract.py`

| Env var | Purpose |
|---|---|
| `EPM_SERVER_URL` | Your EPM Cloud pod URL |
| `EPM_USERNAME` | Service account username |
| `EPM_PASSWORD` | Service account password (**required** unless `--dry-run`) |
| `EPM_APPLICATION` | Your EPM application name |
| `EPM_PLAN_TYPE` | Your plan type / cube name |

You'll also need to edit the **dimension config** near the top of the file (POV dimensions, entity list, measure name, `ENTITY_MAP`) to match your own application outline — these can't be inferred from an env var since they're specific to your outline design.

The fiscal calendar (`FISCAL_YEAR_START`, `PERIOD_WEEK_PATTERN`, `NUM_PERIODS`) is hardcoded for simplicity but ideally should mirror your EPM application's own Substitution Variables so it doesn't drift out of sync year over year.

```bash
python EPMDataExtract.py --weeks 14      # last 14 fiscal weeks
python EPMDataExtract.py --months 3      # ~ last 3 fiscal periods
python EPMDataExtract.py                 # interactive prompt if no flags given
```

### 2. `SourceOfTruthExtract.py`

Set `SOT_SOURCE_TYPE` to pick your backend — `flatfile` (default), `sql`, `bigquery`, or `snowflake`:

| Env var | Used by | Purpose |
|---|---|---|
| `SOT_SOURCE_TYPE` | all | `flatfile` / `sql` / `bigquery` / `snowflake` |
| `SOT_OUTPUT_FILE` | all | Output filename (default `sot_output.json`) |
| `SOT_FLATFILE_PATH`, `SOT_FLATFILE_REGION_COL`, `SOT_FLATFILE_PERIOD_COL`, `SOT_FLATFILE_DATE_COL`, `SOT_FLATFILE_VALUE_COL` | `flatfile` | CSV path and column names |
| `SOT_SQL_CONN_STRING`, `SOT_SQL_QUERY` | `sql` | SQLAlchemy connection string + query — covers Oracle ERP, JDE, SAP HANA, SQL Server, Postgres, etc. |
| `SOT_BQ_KEY_PATH`, `SOT_BQ_QUERY` | `bigquery` | Service account key path + query |
| `SOT_SNOWFLAKE_ACCOUNT`, `SOT_SNOWFLAKE_USER`, `SOT_SNOWFLAKE_PASSWORD`, `SOT_SNOWFLAKE_WAREHOUSE`, `SOT_SNOWFLAKE_DATABASE`, `SOT_SNOWFLAKE_SCHEMA`, `SOT_SNOWFLAKE_QUERY` | `snowflake` | Connection details + query |

Only the dependency for the backend you actually use is required:

```bash
pip install sqlalchemy cx_Oracle          # for --source-type sql against Oracle
pip install google-cloud-bigquery         # for bigquery
pip install snowflake-connector-python    # for snowflake
```

`flatfile` mode needs nothing beyond the standard library, and transparently handles BOM-prefixed CSVs (a common artifact from PowerShell, Excel, or Notepad saves).

### 3. `reconcile.py`

| Env var | Purpose |
|---|---|
| `RECON_EPM_FILE` | Path to the EPM-side JSON (default `exportdaily_normalized.json`) |
| `RECON_SOT_FILE` | Path to the source-of-truth JSON (default `sot_output.json`) |
| `RECON_CLOSE_DAY` | Optional label (e.g. `BD3`) — see **Month-end close** below |
| `SMTP_SERVER` | Default `smtp.gmail.com` — also works with `smtp.office365.com`, etc. |
| `SMTP_PORT` | Default `587` |
| `SMTP_USERNAME` | Your email address (**required**) |
| `SMTP_PASSWORD` | An **app password**, not your normal login password (**required**) |
| `RECON_FROM_EMAIL` | Defaults to `SMTP_USERNAME` |
| `RECON_TO_EMAIL` | Comma-separated recipient list (**required**) |

Email is sent via Python's built-in `smtplib` — free, no API key, no subscription. Works with Gmail (with an [App Password](https://myaccount.google.com/apppasswords)), Office365, Yahoo, or any SMTP server. If you'd rather use a dedicated transactional provider (SendGrid, AWS SES, Mailgun, Postmark), the comment above `send_email()` in the script explains exactly what to swap.

**Gmail note:** requires 2-Step Verification enabled, then an App Password generated separately from your normal login password.
**Office365 note:** if your account has Modern Auth/MFA (common for work accounts), plain SMTP AUTH may be disabled by tenant policy — check with your admin if login fails.

---

## Month-end close window usage

Many organizations run month-end close over several days — commonly "business day 1 through 5" (**BD1–BD5**) or "calendar day 1 through 10" — with data reloading daily as adjustments land. Running this pipeline **once per business day** throughout that window, rather than only weekly, catches discrepancies while there's still time to fix them.

### Manual usage

During the close window, run each script with a short `--weeks 1` (you mainly care about the period that's still settling, not weeks that are already final) and set `RECON_CLOSE_DAY` so each day's email subject and report title are labeled distinctly — otherwise several days' emails look identical in your inbox:

```bash
export RECON_CLOSE_DAY="BD3"
python EPMDataExtract.py --weeks 1
python SourceOfTruthExtract.py --weeks 1
python reconcile.py
```

### Fully automated: `run_daily_recon.ps1`

Manually setting `RECON_CLOSE_DAY` every morning doesn't scale, so the repo includes a PowerShell wrapper that **calculates which business day it is automatically** and runs the whole pipeline — this is the file you actually schedule, not the three Python scripts individually.

**Worked example** — say BD1 (the first day of your close window) is Monday, August 3, and your close spans 8 business days:

| Business Day | Calendar Date |
|---|---|
| BD1 | Mon, Aug 3 |
| BD2 | Tue, Aug 4 |
| BD3 | Wed, Aug 5 |
| BD4 | Thu, Aug 6 |
| BD5 | Fri, Aug 7 |
| BD6 | Mon, Aug 10 *(weekend skipped)* |
| BD7 | Tue, Aug 11 |
| BD8 | Wed, Aug 12 |

Only two values in `run_daily_recon.ps1` change per close cycle — everything else (EPM/source/SMTP config) stays fixed for the whole window:

```powershell
$CloseStartDate = Get-Date "2026-08-03"   # BD1 for this close cycle
$MaxBusinessDay = 8                        # BD1 through BD8
```

The script counts weekdays between `$CloseStartDate` and today, sets `RECON_CLOSE_DAY` accordingly, and runs all three scripts with `--weeks 1`. Outside the configured window (weekends, before BD1, or past BD8) it exits immediately without doing anything — so it's safe to schedule it to fire every weekday indefinitely.

**Scheduling it (Windows Task Scheduler):**
1. **Create Basic Task** → **Trigger**: Weekly → check only Mon–Fri
2. **Time**: right after your data load finishes each day (e.g. 7:30 AM if the load completes by 7:00 AM)
3. **Action**: Start a program
   - Program: `powershell.exe`
   - Arguments: `-ExecutionPolicy Bypass -File "C:\path\to\run_daily_recon.ps1"`
   - Start in: the folder containing all four files

> **Caveat:** this assumes your close calendar is always "N consecutive weekdays starting on a fixed date." If your organization's close calendar has exceptions (a holiday mid-window, a shifted start date some months), the business-day math won't account for that automatically — treat it as a starting point, not a guarantee for every fiscal calendar.

---

## Repo contents

```
EPMDataExtract.py          # Pulls & normalizes EPM Cloud data
SourceOfTruthExtract.py    # Pulls & normalizes source-of-truth data
reconcile.py               # Reconciles both sides and emails the report
run_daily_recon.ps1        # Wrapper for automated month-end close scheduling
README.md                  # You are here
```

---

## Disclaimer

These scripts are shared for **educational purposes** as working examples of an EPM data-extraction and reconciliation pattern. They are provided **"as is,"** without warranty of any kind, express or implied. Test thoroughly in a non-production environment before pointing them at any live system or relying on them for real financial or operational decisions. The author assumes no responsibility for data loss, missed alerts, service disruption, or any other consequence of using or modifying these scripts. You are responsible for securing your own credentials (never commit passwords, API keys, or connection strings to source control) and for complying with your organization's change-management and security policies.

---

## Author

**Vikram Kumar** — Oracle EPM Architect
Compiled and tested: 2026-08-03

Feedback, issues, and PRs welcome.
