# Import-Validate for EPM Cloud

A lightweight Python pipeline that substitutes for Oracle EPM Cloud Data
Integration's built-in **Import** and **Validate** steps — scan a CSV file,
extract the unique dimension member values it contains, and check them
against your EPM Planning/FreeForm application **before** you attempt a load.

Catching bad dimension members here means you find out about them in
seconds, with the exact file and value that caused the problem — instead of
after Data Integration's load has already failed.

---

## Why this exists

Oracle EPM Cloud Data Integration runs its own Import and Validate steps as
part of a load, but:

- Validation errors often surface late, buried in a load-process log
- There's no lightweight way to "pre-flight" a file before committing to a
  full Data Integration run
- Large files can be slow to iterate on when you're just trying to catch a
  handful of bad values

This pipeline runs entirely outside Data Integration, on your own machine or
server, using [DuckDB](https://duckdb.org/) for fast local CSV scanning and
Oracle's own EPM Cloud REST API for the actual validation — so you can catch
problems early, iterate quickly, and only push a load through Data
Integration once you're confident it'll succeed.

---

## Why this is fast

Oracle's own documentation describes Data Integration's internal
import/validate flow as a multi-step process built around relational
staging tables: the file is staged and loaded into a `TDATASEG_T` table,
mapping rules are processed, prior integrations in `TDATASEG` are cleaned
up, the mapping results are copied from `TDATASEG_T` into `TDATASEG`, and
only then is validation run against that staged data. Oracle's `TDATASEG`
reference table also notes that a large `TDATASEG` table can slow down
query performance during a load — the more rows staged, the heavier that
process gets.

In other words, **every row of your file gets physically written into a
relational table, then copied again to a second table**, with validation
running as a database operation against that full row-level data.

This pipeline skips staging entirely. `importStep.py` scans your file
directly with DuckDB and extracts only the **distinct dimension values** —
typically a handful of unique strings per column, regardless of whether
your file has a thousand rows or ten million. `validator.py` then checks
that small, already-deduplicated set against EPM. The amount of data
actually being validated has nothing to do with your file's row count —
it's bounded by how many *unique* members each dimension actually has.

That's the core reason this is fast for a pre-flight check: no staging
table writes, no row-by-row database operations, and validation work that
scales with dimension cardinality instead of file size.

**My honest caveat:** this isn't a benchmarked "N times faster" claim, and
it isn't a replacement for Data Integration's full capabilities — the
staging-table approach exists for good reasons, including a complete audit
trail and drill-through access in Workbench, which this lightweight
pipeline doesn't attempt to replicate. Think of this as a fast sanity check
you run *before* committing to a full Data Integration load, not a
substitute for what Data Integration does once a load is actually underway.

*Sources: [Administering Data Integration](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/diepm/toc.htm),
[TDATASEG Table Reference](https://docs.oracle.com/cloud/latest/epm-common/ERPIA/toc.htm)*

---

## How it works

```
CSV file(s)
    │
    ▼
importStep.py   →  scans the file with DuckDB, extracts every unique value
                    per mapped dimension column, with source-file tracking
    │
    ▼
validator.py    →  checks each value against EPM (mock sample set, or a
                    real EPM Cloud instance via REST API)
    │
    ▼
main.py         →  prints a pass/fail summary to the console
    │
    ▼
notifier.py     →  (optional) emails the same summary
```

---

## Files

| File | Purpose |
|---|---|
| `config.py` | All settings — data source, EPM connection, mode switches, email |
| `importStep.py` | Extracts unique dimension values from CSV using DuckDB |
| `validator.py` | Validates extracted values against EPM (mock or live mode) |
| `main.py` | Orchestrates Import → Validate → Notify |
| `notifier.py` | Sends a pass/fail email with full invalid-value detail |

---

## Requirements

- Python 3.10+
- Install dependencies:
  ```
  pip install duckdb requests urllib3
  ```
  (`duckdb` is required for the Import step; `requests`/`urllib3` are only
  needed if you switch to live EPM validation or enable email notifications)

---

## Quick Start (no EPM connection needed)

This repo ships with a **mock validation mode** so you can try the full
pipeline with zero Oracle EPM setup, using a public dataset.

1. **Download the demo dataset**
   Get [Retail Store Sales: Dirty for Data Cleaning](https://www.kaggle.com/datasets/ahmedmohamed2003/retail-store-sales-dirty-for-data-cleaning)
   from Kaggle and save `retail_store_sales.csv` into a folder on your
   machine (e.g. a `DataSet` folder next to the scripts).

2. **Point `config.py` at your data** (Section 1)
   ```python
   CSV_DIR  = r"path\to\your\DataSet"
   CSV_GLOB = "retail_store_sales.csv"

   DIMENSION_MAP = {
       "Category":       "Product_Category",
       "Item":           "SKU",
       "Payment Method": "Tender_Type",
   }

   EXCLUDE_COLUMNS = ["Total Spent", "Price Per Unit", "Quantity"]
   ```

3. **Leave `VALIDATION_MODE = "mock"`** (Section 3) — this is the default,
   and needs no EPM instance.

4. **Run it**
   ```
   python main.py
   ```
   You'll see a console summary showing valid/invalid/api_error counts per
   dimension. With the unmodified dataset, everything should come back
   valid.

---

## Testing the invalid-detection path

The dataset ships clean of *invalid* values by design — to see the
pipeline actually catch something, add a deliberately bad row yourself:

1. Copy `retail_store_sales.csv` → `retail_store_sales_test.csv`
2. Append this row:
   ```
   TXN_TEST001,CUST_TEST,Frozen Meals,Item_99_FROZEN,12.0,3.0,36.0,Bitcoin,Online,2024-01-01,False
   ```
   This breaks all three mapped dimensions at once — `Frozen Meals` isn't a
   real category, `Item_99_FROZEN` isn't a real SKU, and `Bitcoin` isn't a
   real payment method.
3. Update `CSV_GLOB` in `config.py` to `"retail_store_sales_test.csv"`
4. Re-run `python main.py`

You should see 3 invalid entries — one per dimension — each tagged with
`retail_store_sales_test.csv` as the source file. That's the pipeline's
file-provenance tracking at work: it doesn't just tell you a value is bad,
it tells you exactly which file it came from.

---

## Switching to a real Oracle EPM Cloud instance

Once you're ready to validate against your own EPM application:

1. Fill in **Section 2** of `config.py`:
   ```python
   EPM_BASE_URL    = "https://your-instance.epm.us-region-1.ocs.oraclecloud.com/HyperionPlanning/rest/v3"
   EPM_APPLICATION = "YourAppName"
   EPM_PLAN_TYPE   = "YourPlanType"
   EPM_USERNAME    = "your_service_account"
   ```

2. Set your EPM password as an environment variable — **never** hardcode it
   in `config.py`:
   ```
   # Windows (PowerShell)
   $env:EPM_PASSWORD = "your-password"

   # macOS / Linux
   export EPM_PASSWORD="your-password"
   ```
   Prefer not to use a plain password at all? See Oracle's
   [EPM Automate password encryption](https://docs.oracle.com/en/cloud/saas/enterprise-performance-management-common/cepma/epm_auto_encrypt.html)
   for an alternative.

3. Update your `DIMENSION_MAP` to match your real EPM dimension names.
   Oracle Planning applications typically include seven standard
   dimensions — Account, Entity, Scenario, Version, Period, Year, and
   Currency — plus whatever custom dimensions your application adds.

4. Set `VALIDATION_MODE = "live"` in **Section 3**.

5. Run `python main.py` again — no other code changes needed. `validator.py`
   now calls Oracle's Get Dimension Details REST API for each mapped
   dimension instead of using the built-in mock set.

---

## Email notifications (optional)

To get a pass/fail email after each run, fill in **Section 6** of
`config.py` and set `SEND_EMAIL = True`:

```python
SEND_EMAIL    = True
SMTP_HOST     = "smtp.office365.com"   # or your own company's SMTP relay
SMTP_PORT     = 587
SMTP_USERNAME = "your_email@example.com"
FROM_EMAIL    = "your_email@example.com"
TO_EMAIL      = ["team@example.com"]
```

Set the SMTP password as an environment variable, same pattern as the EPM
password:
```
$env:EPM_SMTP_PASSWORD = "your-password-or-app-password"
```

If your account has MFA enabled, you'll need an app password — a normal
login password will be rejected by SMTP AUTH.

Leave `SEND_EMAIL = False` (the default) to skip this step entirely; the
console summary from `main.py` still prints either way.

---

## Performance notes

`importStep.py` runs **one DuckDB query per dimension column** rather than
a single wide `UNPIVOT` scan. On memory-constrained hardware, a single scan
across many columns creates a much wider intermediate result that can
exceed available RAM and force heavy disk spilling — per-column queries
keep each query's working set small. `DUCKDB_MEMORY_LIMIT` and
`DUCKDB_THREADS` in `config.py` (Section 4) should be tuned to your actual
machine; increase both if you have more headroom.

For repeat runs on large files, converting to Parquet first
(`USE_PARQUET = True` after a one-time conversion) is significantly faster,
since DuckDB only reads the columns it needs.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgments

Demo dataset: [Retail Store Sales: Dirty for Data Cleaning](https://www.kaggle.com/datasets/ahmedmohamed2003/retail-store-sales-dirty-for-data-cleaning)
by Ahmed Mohamed, via Kaggle.
