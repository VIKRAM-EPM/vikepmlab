"""
================================================================================
Script Name : reconcile.py
Author      : Vikram Kumar (Oracle EPM Architect)
Compiled and Tested By : Vikram Kumar
Last Tested : 2026-08-03
Version     : 1.0
================================================================================
PURPOSE
Reconciles data extracted by EPMDataExtract.py (the EPM side) against data
extracted by SourceOfTruthExtract.py (the source-of-truth side), classifies
each region/period row as MATCH / VARIANCE / MISSING within a configurable
dollar tolerance, generates an HTML report, and emails it out via SMTP.

>>> BEFORE YOU RUN THIS <<<
Set the environment variables under "EMAIL CONFIGURATION" below
(SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, RECON_TO_EMAIL) to match your
own mail provider. See the comment above send_email() for Gmail/Office365/
Yahoo specifics and for swapping in a different email provider entirely.

USAGE
Run EPMDataExtract.py and SourceOfTruthExtract.py first to produce their
respective JSON files, then run this script to reconcile and email the
result:
    python EPMDataExtract.py --dry-run --weeks 4
    python SourceOfTruthExtract.py --dry-run --weeks 4
    python reconcile.py

MONTH-END / CLOSE-WINDOW USAGE
Many organizations run month-end close over several days -- "business day
1 through 5" (BD1-BD5) or "calendar day 1 through 10" are common
conventions -- with data reloading daily as adjustments come in. Running
this whole pipeline once per business day throughout that window (rather
than only weekly) catches discrepancies while there's still time to fix
them before the books close.

Since you'll likely get one email per business day during close, set
RECON_CLOSE_DAY (below) to a short label like "BD1", "BD2", "Day 5", etc.
-- it gets appended to the subject line and report title so consecutive
days are easy to tell apart in your inbox rather than looking identical.

DISCLAIMER
This script is shared for educational purposes as a working example of a
data-reconciliation and alerting pattern. It is provided "as is," without
warranty of any kind, express or implied. Test thoroughly in a non-
production environment before relying on it for real financial or
operational decisions. The author assumes no responsibility for data loss,
missed alerts, or any other consequence of using or modifying this script.
You are responsible for securing your own credentials (never commit
passwords or API keys to source control) and for complying with your
organization's change-management and security policies.
================================================================================
"""

import os
import json
import pytz
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# =====================================
# CONFIGURATION
# =====================================
EPM_FILE      = os.environ.get("RECON_EPM_FILE", "exportdaily_normalized.json")
SOT_FILE      = os.environ.get("RECON_SOT_FILE", "sot_output.json")
OUTPUT_JSON   = "reconciliation_report.json"
OUTPUT_HTML   = "reconciliation_report.html"
TOLERANCE     = 0.01

# Optional label for month-end close windows -- e.g. "BD1", "BD3", "Day 5".
# When set, it's appended to the email subject and report title so
# consecutive daily runs during close are easy to tell apart. Leave blank
# for normal/weekly use outside of a close window.
CLOSE_DAY_LABEL = os.environ.get("RECON_CLOSE_DAY", "")

# =====================================
# EMAIL CONFIGURATION
# =====================================
# >>> UPDATE THIS <<<
# This uses Python's built-in smtplib — completely free, no API key,
# no subscription, no third-party account required. It works with
# Gmail, Outlook/Office365, Yahoo, or any SMTP server you already have
# access to (including your company's own mail server).
#
# Gmail setup: you cannot use your normal Gmail password here — create
# an "App Password" instead (Google Account > Security > 2-Step
# Verification > App Passwords) and use that as SMTP_PASSWORD.
# Outlook/Office365: smtp.office365.com, port 587.
# Yahoo: smtp.mail.yahoo.com, port 587 (also requires an app password).
#
# If you'd rather use a dedicated transactional email service instead
# of SMTP (e.g. for higher volume, better deliverability, or built-in
# analytics), swap out the body of send_email() below for that
# provider's client instead — a few common options:
#   - SendGrid   (pip install sendgrid)             — 60-day free trial, then paid
#   - AWS SES    (pip install boto3)                 — pay-per-email, no monthly minimum
#   - Mailgun    (pip install requests, uses their HTTP API) — small free tier
#   - Postmark   (pip install postmarker)            — small free tier
# Everything else in this script (the reconciliation logic and HTML
# report builders) stays exactly the same regardless of which you pick
# — only send_email() needs to change.
SMTP_SERVER   = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")   # your email address
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")   # app password, NOT your normal login password

FROM_EMAIL       = os.environ.get("RECON_FROM_EMAIL", SMTP_USERNAME)
TO_EMAIL         = os.environ.get("RECON_TO_EMAIL", "").split(",")  # comma-separated list, e.g. "a@x.com,b@x.com"

# =====================================
# LOAD BOTH FILES
# =====================================
def load_json(filepath):
    with open(filepath, 'r') as f:
        content = json.load(f)
    return content.get("data", [])

# =====================================
# RECONCILIATION LOGIC
# =====================================
def reconcile(epm_data, sot_data):
    epm_lookup = {(r["region"], r["period"]): r["net_sales"] for r in epm_data}
    sot_lookup      = {(r["region"], r["period"]): r["net_sales"] for r in sot_data}

    all_keys = sorted(set(epm_lookup.keys()) | set(sot_lookup.keys()))

    records = []
    for (region, period) in all_keys:
        epm_val = epm_lookup.get((region, period))
        sot_val      = sot_lookup.get((region, period))

        if epm_val is None:
            status       = "MISSING IN EPM"
            variance     = None
            variance_pct = None
        elif sot_val is None:
            status       = "MISSING IN SOURCE OF TRUTH"
            variance     = None
            variance_pct = None
        else:
            variance     = round(sot_val - epm_val, 2)
            variance_pct = round((variance / sot_val * 100), 4) if sot_val != 0 else 0.0
            status       = "MATCH" if abs(variance) <= TOLERANCE else "VARIANCE"

        records.append({
            "region"        : region,
            "period"        : period,
            "epm_value": epm_val,
            "sot_value"     : sot_val,
            "variance"      : variance,
            "variance_pct"  : variance_pct,
            "status"        : status
        })

    return records

# =====================================
# SUMMARY STATS
# =====================================
def get_summary(records):
    eastern     = pytz.timezone("America/New_York")
    now_eastern = datetime.now(eastern)
    total       = len(records)
    matched     = sum(1 for r in records if r["status"] == "MATCH")
    variances   = sum(1 for r in records if r["status"] == "VARIANCE")
    missing_epm  = sum(1 for r in records if r["status"] == "MISSING IN EPM")
    missing_sot = sum(1 for r in records if r["status"] == "MISSING IN SOURCE OF TRUTH")
    return {
        "total"      : total,
        "matched"    : matched,
        "variances"  : variances,
        "missing_epm" : missing_epm,
        "missing_sot": missing_sot,
        "run_at"     : now_eastern.strftime("%Y-%m-%d %H:%M:%S ET")
    }

# =====================================
# SAVE JSON REPORT
# =====================================
def save_json_report(records, summary):
    output = {
        "summary": summary,
        "data"   : records
    }
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"JSON report saved to: {OUTPUT_JSON}")

# =====================================
# FORMAT HELPERS
# =====================================
def fmt_val(val):
    if val is None:
        return ""
    return f"{val:,.2f}"

def fmt_pct(val):
    if val is None:
        return ""
    return f"{val:+.4f}%"

def status_style(status):
    return {
        "MATCH"              : ("", "#e6f4ea", "#2e7d32"),
        "VARIANCE"           : ("", "#fdecea", "#c62828"),
        "MISSING IN EPM": ("",  "#fff8e1", "#f57f17"),
        "MISSING IN SOURCE OF TRUTH"     : ("",  "#fff8e1", "#f57f17"),
    }.get(status, ("", "#ffffff", "#000000"))

# =====================================
# GENERATE HTML REPORT (full list)
# =====================================
def save_html_report(records, summary):
    rows_html = ""
    for r in records:
        icon, bg, color = status_style(r["status"])
        rows_html += f"""
        <tr style="background-color:{bg};">
            <td style="padding:10px 16px; text-align:left;">{r['region'].capitalize()}</td>
            <td style="padding:10px 16px; text-align:left;">{r['period']}</td>
            <td style="padding:10px 16px; text-align:right; font-family:monospace;">{fmt_val(r['epm_value'])}</td>
            <td style="padding:10px 16px; text-align:right; font-family:monospace;">{fmt_val(r['sot_value'])}</td>
            <td style="padding:10px 16px; text-align:right; font-family:monospace; color:{color}; font-weight:600;">{fmt_val(r['variance'])}</td>
            <td style="padding:10px 16px; text-align:right; font-family:monospace; color:{color}; font-weight:600;">{fmt_pct(r['variance_pct'])}</td>
            <td style="padding:10px 16px; text-align:center; color:{color}; font-weight:700;">{icon} {r['status']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>EPM vs Source of Truth Reconciliation Report</title>
</head>
<body style="margin:0; padding:20px; font-family:Arial, sans-serif; color:#000;">

  <!-- HEADER -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-bottom:3px solid #1a237e; padding:12px 0;">
    <tr>
      <td>
        <h1 style="margin:0; color:#1a237e; font-size:18px;">
          {(CLOSE_DAY_LABEL + " -- ") if CLOSE_DAY_LABEL else ""}EPM vs Source of Truth  Weekly Net Sales Reconciliation
        </h1>
        <p style="margin:6px 0 0; font-size:12px; color:#000;">
          Generated: {summary['run_at']}
        </p>
      </td>
    </tr>
  </table>

  <!-- SUMMARY CARDS -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f4f4f4; padding:16px;
                border:1px solid #e0e0e0; margin-top:16px;">
    <tr>
      <td align="center" style="padding:12px;">
        <div style="font-size:28px; font-weight:700; color:#1a237e;">
          {summary['total']}
        </div>
        <div style="font-size:12px; color:#000;">Total Rows</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#2e7d32;">
          {summary['matched']}
        </div>
        <div style="font-size:12px; color:#000;">Matched</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#c62828;">
          {summary['variances']}
        </div>
        <div style="font-size:12px; color:#000;">Variances</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#f57f17;">
          {summary['missing_epm'] + summary['missing_sot']}
        </div>
        <div style="font-size:12px; color:#000;">Missing</div>
      </td>
    </tr>
  </table>

  <!-- DATA TABLE -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-collapse:collapse; background:#fff;
                border:1px solid #e0e0e0; border-top:none;">
    <thead>
      <tr style="background:#f4f4f4; color:#000;">
        <th style="padding:10px 16px; text-align:left;   font-size:13px; border-bottom:2px solid #e0e0e0;">Region</th>
        <th style="padding:10px 16px; text-align:left;   font-size:13px; border-bottom:2px solid #e0e0e0;">Period</th>
        <th style="padding:10px 16px; text-align:right;  font-size:13px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Source of Truth Value</th>
        <th style="padding:10px 16px; text-align:right;  font-size:13px; border-bottom:2px solid #e0e0e0; font-family:monospace;">EPM Value</th>
        <th style="padding:10px 16px; text-align:right;  font-size:13px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Variance ($)</th>
        <th style="padding:10px 16px; text-align:right;  font-size:13px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Variance (%)</th>
        <th style="padding:10px 16px; text-align:center; font-size:13px; border-bottom:2px solid #e0e0e0;">Status</th>
      </tr>
    </thead>
    <tbody style="font-size:13px;">
      {rows_html}
    </tbody>
  </table>

  <!-- FOOTER -->
  <p style="text-align:center; font-size:11px; color:#999; margin-top:16px;">
    Tolerance threshold: ${TOLERANCE:.2f} | EPM vs Source of Truth Automated Reconciliation
  </p>

</body>
</html>"""

    with open(OUTPUT_HTML, 'w') as f:
        f.write(html)
    print(f"HTML report saved to: {OUTPUT_HTML}")
    return html

def build_variance_email_body(records, summary):
    variance_records = [
        r for r in records
        if r["status"] in ("VARIANCE", "MISSING IN EPM", "MISSING IN SOURCE OF TRUTH")
    ]

    rows_html = ""
    for r in variance_records:
        icon, bg, color = status_style(r["status"])
        rows_html += f"""
        <tr style="background-color:{bg};">
            <td style="padding:8px 10px; text-align:left; border-bottom:0.5px solid #e0e0e0;">{r['region'].capitalize()}</td>
            <td style="padding:8px 10px; text-align:left; border-bottom:0.5px solid #e0e0e0;">{r['period']}</td>
            <td style="padding:8px 10px; text-align:right; font-family:monospace; border-bottom:0.5px solid #e0e0e0;">{fmt_val(r['sot_value'])}</td>
            <td style="padding:8px 10px; text-align:right; font-family:monospace; border-bottom:0.5px solid #e0e0e0;">{fmt_val(r['epm_value'])}</td>
            <td style="padding:8px 10px; text-align:right; font-family:monospace; color:{color}; font-weight:600; border-bottom:0.5px solid #e0e0e0;">{fmt_val(r['variance'])}</td>
            <td style="padding:8px 10px; text-align:right; font-family:monospace; color:{color}; font-weight:600; border-bottom:0.5px solid #e0e0e0;">{fmt_pct(r['variance_pct'])}</td>
            <td style="padding:8px 10px; text-align:center; border-bottom:0.5px solid #e0e0e0;">
              <span style="background:{bg}; color:{color}; font-size:11px;
                           padding:2px 8px; border-radius:4px; font-weight:500;">
                {r['status']}
              </span>
            </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/></head>
<body style="margin:0; padding:20px; font-family:Arial, sans-serif; color:#000;">

  <!-- HEADER -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-bottom:3px solid #c62828; padding:12px 0;">
    <tr>
      <td>
        <h1 style="margin:0; color:#c62828; font-size:18px;">
          {(CLOSE_DAY_LABEL + " -- ") if CLOSE_DAY_LABEL else ""}EPM vs Source of Truth  variances detected
        </h1>
        <p style="margin:6px 0 0; font-size:12px; color:#000;">
          Generated: {summary['run_at']}
        </p>
      </td>
    </tr>
  </table>

  <!-- SUMMARY CARDS -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f4f4f4; padding:16px;
                border:1px solid #e0e0e0; margin-top:16px;">
    <tr>
      <td align="center" style="padding:12px;">
        <div style="font-size:28px; font-weight:700; color:#1a237e;">
          {summary['total']}
        </div>
        <div style="font-size:12px; color:#000;">Total Rows</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#2e7d32;">
          {summary['matched']}
        </div>
        <div style="font-size:12px; color:#000;">Matched</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#c62828;">
          {summary['variances']}
        </div>
        <div style="font-size:12px; color:#000;">Variances</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#f57f17;">
          {summary['missing_epm'] + summary['missing_sot']}
        </div>
        <div style="font-size:12px; color:#000;">Missing</div>
      </td>
    </tr>
  </table>

  <!-- VARIANCE ROWS ONLY -->
  <p style="margin:16px 0 8px; font-weight:500; color:#c62828; font-size:13px;">
    Rows requiring attention ({len(variance_records)} found):
  </p>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-collapse:collapse; border:1px solid #e0e0e0;">
    <thead>
      <tr style="background:#f4f4f4; color:#000;">
        <th style="padding:8px 10px; text-align:left;   font-size:12px; border-bottom:2px solid #e0e0e0;">Region</th>
        <th style="padding:8px 10px; text-align:left;   font-size:12px; border-bottom:2px solid #e0e0e0;">Period</th>
        <th style="padding:8px 10px; text-align:right;  font-size:12px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Source of Truth Value</th>
        <th style="padding:8px 10px; text-align:right;  font-size:12px; border-bottom:2px solid #e0e0e0; font-family:monospace;">EPM Value</th>
        <th style="padding:8px 10px; text-align:right;  font-size:12px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Variance ($)</th>
        <th style="padding:8px 10px; text-align:right;  font-size:12px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Variance (%)</th>
        <th style="padding:8px 10px; text-align:center; font-size:12px; border-bottom:2px solid #e0e0e0;">Status</th>
      </tr>
    </thead>
    <tbody style="font-size:12px;">
      {rows_html}
    </tbody>
  </table>

  <p style="font-size:12px; color:#666; margin-top:12px;">
    Full reconciliation report with all rows is attached.
  </p>
  <p style="text-align:center; font-size:11px; color:#999; margin-top:16px;
            border-top:0.5px solid #e0e0e0; padding-top:12px;">
    Tolerance threshold: ${TOLERANCE:.2f} | EPM vs Source of Truth Automated Reconciliation
  </p>
</body>
</html>"""

def build_allclear_email_body(summary, records):
    matched_rows_html = ""
    for r in records:
        matched_rows_html += f"""
        <tr style="background:#f6fff6;">
            <td style="padding:8px 10px; border-bottom:0.5px solid #e0e0e0;">{r['region'].capitalize()}</td>
            <td style="padding:8px 10px; border-bottom:0.5px solid #e0e0e0;">{r['period']}</td>
            <td style="padding:8px 10px; text-align:right; font-family:monospace; border-bottom:0.5px solid #e0e0e0;">{fmt_val(r['sot_value'])}</td>
            <td style="padding:8px 10px; text-align:right; font-family:monospace; border-bottom:0.5px solid #e0e0e0;">{fmt_val(r['epm_value'])}</td>
            <td style="padding:8px 10px; text-align:right; font-family:monospace; color:#2e7d32; border-bottom:0.5px solid #e0e0e0;">0.00</td>
            <td style="padding:8px 10px; text-align:right; font-family:monospace; color:#2e7d32; border-bottom:0.5px solid #e0e0e0;">+0.0000%</td>
            <td style="padding:8px 10px; text-align:center; border-bottom:0.5px solid #e0e0e0;">
              <span style="background:#e6f4ea; color:#2e7d32; font-size:11px;
                           padding:2px 8px; border-radius:4px;">Match</span>
            </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/></head>
<body style="margin:0; padding:20px; font-family:Arial, sans-serif; color:#000;">

  <!-- HEADER -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-bottom:3px solid #2e7d32; padding:12px 0;">
    <tr>
      <td>
        <h1 style="margin:0; color:#2e7d32; font-size:18px;">
          {(CLOSE_DAY_LABEL + " -- ") if CLOSE_DAY_LABEL else ""}EPM vs Source of Truth  all data matched
        </h1>
        <p style="margin:6px 0 0; font-size:12px; color:#000;">
          Generated: {summary['run_at']}
        </p>
      </td>
    </tr>
  </table>

  <!-- SUMMARY CARDS -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#f4f4f4; padding:16px;
                border:1px solid #e0e0e0; margin-top:16px;">
    <tr>
      <td align="center" style="padding:12px;">
        <div style="font-size:28px; font-weight:700; color:#1a237e;">
          {summary['total']}
        </div>
        <div style="font-size:12px; color:#000;">Total Rows</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#2e7d32;">
          {summary['matched']}
        </div>
        <div style="font-size:12px; color:#000;">Matched</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#c62828;">0</div>
        <div style="font-size:12px; color:#000;">Variances</div>
      </td>
      <td align="center" style="padding:12px; border-left:1px solid #e0e0e0;">
        <div style="font-size:28px; font-weight:700; color:#f57f17;">0</div>
        <div style="font-size:12px; color:#000;">Missing</div>
      </td>
    </tr>
  </table>

  <!-- ALL CLEAR MESSAGE -->
  <div style="text-align:center; padding:20px; background:#f6fff6;
              border-radius:8px; margin:16px 0;">
    <p style="font-size:14px; font-weight:500; color:#2e7d32; margin:0 0 6px;">
      All {summary['total']} rows matched within tolerance of ${TOLERANCE:.2f}
    </p>
    <span style="font-size:12px; color:#666;">
      Full reconciliation report with all rows is attached.
    </span>
  </div>

  <!-- ALL MATCHED ROWS TABLE -->
  <p style="font-size:13px; font-weight:500; color:#2e7d32; margin:16px 0 8px;">
    All matched rows:
  </p>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-collapse:collapse; border:1px solid #e0e0e0;">
    <thead>
      <tr style="background:#f4f4f4; color:#000;">
        <th style="padding:8px 10px; text-align:left;   font-size:12px; border-bottom:2px solid #e0e0e0;">Region</th>
        <th style="padding:8px 10px; text-align:left;   font-size:12px; border-bottom:2px solid #e0e0e0;">Period</th>
        <th style="padding:8px 10px; text-align:right;  font-size:12px; border-bottom:2px solid #e0e0e0; font-family:monospace;">EPM Value</th>
        <th style="padding:8px 10px; text-align:right;  font-size:12px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Source of Truth Value</th>
        <th style="padding:8px 10px; text-align:right;  font-size:12px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Variance ($)</th>
        <th style="padding:8px 10px; text-align:right;  font-size:12px; border-bottom:2px solid #e0e0e0; font-family:monospace;">Variance (%)</th>
        <th style="padding:8px 10px; text-align:center; font-size:12px; border-bottom:2px solid #e0e0e0;">Status</th>
      </tr>
    </thead>
    <tbody style="font-size:12px;">
      {matched_rows_html}
    </tbody>
  </table>

  <!-- FOOTER -->
  <p style="text-align:center; font-size:11px; color:#999; margin-top:16px;
            border-top:0.5px solid #e0e0e0; padding-top:12px;">
    Tolerance threshold: ${TOLERANCE:.2f} | EPM vs Source of Truth Automated Reconciliation
  </p>

</body>
</html>"""

# =====================================
# SEND EMAIL VIA SMTP (free — no API key required)
# =====================================
# >>> UPDATE THIS <<<
# To switch to a different provider (SendGrid, SES, Mailgun, Postmark),
# replace everything from "Build email" down to the end of this
# function with that provider's send call instead. The subject/body
# construction above this point (has_variance, subject, html_body)
# stays the same no matter which provider you use.
def send_email(summary, records):
    """
    Sends the reconciliation report by email using SMTP — works with
    Gmail, Outlook, Yahoo, or any SMTP server, at no cost.
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("ERROR: Set SMTP_USERNAME and SMTP_PASSWORD environment variables before running.")
        return
    if not TO_EMAIL or TO_EMAIL == ['']:
        print("ERROR: Set RECON_TO_EMAIL (comma-separated) before running.")
        return

    has_variance = (
        summary['variances'] > 0 or
        summary['missing_epm'] > 0 or
        summary['missing_sot'] > 0
    )

    close_day_tag = f"[{CLOSE_DAY_LABEL}] " if CLOSE_DAY_LABEL else ""

    # Build subject line
    if has_variance:
        subject = (
            f" {close_day_tag}EPM vs Source of Truth Recon  "
            f"{summary['variances']} Variance(s), "
            f"{summary['missing_epm'] + summary['missing_sot']} Missing "
            f"[{summary['run_at']}]"
        )
        html_body = build_variance_email_body(records, summary)
    else:
        subject   = f" {close_day_tag}EPM vs Source of Truth Recon  All Clear [{summary['run_at']}]"
        html_body = build_allclear_email_body(summary, records)

    # Build email
    msg = MIMEMultipart()
    msg["From"] = FROM_EMAIL
    msg["To"] = ", ".join(TO_EMAIL)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    # Attach the HTML report
    with open(OUTPUT_HTML, 'rb') as f:
        attachment = MIMEBase("application", "octet-stream")
        attachment.set_payload(f.read())
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition", f"attachment; filename={OUTPUT_HTML}"
    )
    msg.attach(attachment)

    # Send
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())
        print(f"Email sent successfully!")
        print(f"  Subject     : {subject}")
        print(f"  To          : {TO_EMAIL}")
        print(f"  Attachment  : {OUTPUT_HTML}")
    except Exception as e:
        print(f"Email failed: {e}")

# =====================================
# MAIN
# =====================================
def main():
    print("Loading EPM data...")
    epm_data = load_json(EPM_FILE)
    print(f"   {len(epm_data)} records loaded")

    print("Loading Source of Truth data...")
    sot_data = load_json(SOT_FILE)
    print(f"   {len(sot_data)} records loaded")

    print("Running reconciliation...")
    records = reconcile(epm_data, sot_data)

    summary = get_summary(records)
    print(f"\n{'='*40}")
    print(f"  Total Rows        : {summary['total']}")
    print(f"   Matched        : {summary['matched']}")
    print(f"   Variances      : {summary['variances']}")
    print(f"    Missing EPM    : {summary['missing_epm']}")
    print(f"    Missing SoT    : {summary['missing_sot']}")
    print(f"{'='*40}\n")

    save_json_report(records, summary)
    save_html_report(records, summary)

    print("Sending email...")
    send_email(summary, records)
    print("\nDone!")

if __name__ == "__main__":
    main()