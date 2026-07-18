# EPM Substitution Variable Automation (5-4-4 Fiscal Calendar)

A Groovy business rule for Oracle EPM Cloud that automatically updates a
rolling window of substitution variables every week based on a 5-4-4 fiscal
calendar pattern. Designed to run on a weekly schedule (e.g. every Sunday)
via Calculation Manager.

## What are substitution variables?

Substitution variables are named placeholders (e.g. `WK1`) that stand in for
a specific member or value across forms, reports, and rules in Oracle EPM
Cloud. Instead of hardcoding a value like `P02_WK1-2026` into every report,
you reference the variable — updating the variable's value instantly
updates everywhere it's referenced.

**To view or create them in Oracle EPM Cloud:**
1. Log into your EPM Cloud environment
2. Go to **Application** → **Overview**
3. Click the **Settings** gear icon → **Substitution Variables**
   (path may vary slightly by module — Planning/FreeForm vs. Financial
   Consolidation)
4. Here you'll see existing variables, their scope (a specific cube vs.
   **All Cubes**), and current values
5. To create one manually: click **+ Add**, name it, set scope, set an
   initial value
6. Variables scoped to **All Cubes** are accessible application-wide —
   this is the scope this script targets via
   `app.setSubstitutionVariableValue()`

## What it does

- Calculates the fiscal period and week for a rolling window of the last
  14 completed weeks (~90 days / roughly one fiscal quarter)
- Updates substitution variables `WK1` through `WK14` with year-suffixed
  values (e.g. `P02_WK1-2026`)
- Maintains a parallel "clean" set, `WK1_R` through `WK14_R`, without the
  year suffix (e.g. `P02_WK1`) — useful for reports/rules that shouldn't
  break at year-end
- Logs a before/after table of every variable so changes are auditable in
  the job console
- Sends a confirmation email via EPM Automate once the update completes

## Naming convention

The prefix indicates the rolling granularity; the `_R` suffix always marks
the "clean" (no year suffix) version. This pattern generalizes beyond
weekly:

| Granularity | Full (year-suffixed) | Clean (no year) | Typical use case |
|---|---|---|---|
| Daily   | `D1`–`D30`   | `D1_R`–`D30_R`   | 30-day trailing window |
| Weekly  | `WK1`–`WK14` | `WK1_R`–`WK14_R` | ~1 quarter rolling (this script) |
| Monthly | `M1`–`M13`   | `M1_R`–`M13_R`   | Trailing-twelve-month + buffer reporting |

Only the loop count and date-increment step need to change to adapt this
script to a different granularity (`Calendar.DATE, -1` for daily,
`Calendar.MONTH, -1` for monthly, etc.) — the core fiscal-mapping and
variable-update logic stays the same.

## Why

Manually updating 28 substitution variables every week doesn't scale and is
error-prone, especially across fiscal year-end transitions. This rule
automates the whole process and only touches variables that actually
changed.

## Requirements

- Oracle EPM Cloud with Calculation Manager Groovy business rule support
- EPM Automate CLI available in the rule's execution context (for the
  email step)
- A service account with permission to send mail via EPM Automate

## Setup

1. Open the **Annual Update Section** at the top of the script and set:
   - `CFG_FY_*` — your current fiscal year's start date, label, and
     week pattern (52-week `[5,4,4,...]` or 53-week `[5,4,4,...,5,4,5]`)
   - `CFG_PRIOR_FY_*` — same, for the previous fiscal year (needed for
     year-end transitions)
2. Fill in the **Email Config** block:
   - `EMAIL_TO` — recipient address
   - `EMAIL_USER` — service account username
   - `EMAIL_PASSWORD` — service account password (consider a secrets
     manager or encrypted credential store instead of plain text in
     production)
   - `EMAIL_URL` — your Oracle EPM environment URL
3. Deploy as a Groovy business rule in Calculation Manager
4. Schedule it to run weekly (Sunday recommended, so `WK14` always
   represents the most recently completed week)

## Notes on Oracle's Groovy environment

This script deliberately avoids `.getTime()` and other standard
`java.util.Calendar`/`Date` methods that aren't reliably supported in
Oracle's Groovy runtime — see `getDaysBetween()` for the manual day-counting
workaround. If you're adapting this and are used to full Java/Groovy, don't
assume standard library methods behave the same way here; test thoroughly.

## License

MIT — see [LICENSE](LICENSE).

## Related write-up

Full breakdown of the gotchas and design decisions in this script:
