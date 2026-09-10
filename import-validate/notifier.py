# =============================================================================
# notifier.py — Phase 3: Email the validation results
#
# Input  : results dict from validator.validate_members()
#          { epm_dim: { "valid": {...}, "invalid": {...}, "api_error": {...} } }
#
# Sends ONE email every run — pass or fail, different subject line either way:
#   PASS  -> all dimension values found valid
#   FAIL  -> one or more invalid values found (or an api_error occurred)
#
# Uses the company SMTP relay (internal network, no login required, STARTTLS
# on port 587). See SMTP_HOST / FROM_EMAIL / TO_EMAIL in config.py.
# =============================================================================

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    FROM_EMAIL,
    TO_EMAIL,
    CC_EMAIL,
    EMAIL_SUBJECT_PASS,
    EMAIL_SUBJECT_FAIL,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point — called by main.py
# ---------------------------------------------------------------------------

def send_validation_email(results: dict) -> bool:
    """
    Build and send the pass/fail email for one validation run.

    Args:
        results: output from validator.validate_members()

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    total_invalid = sum(len(buckets["invalid"]) for buckets in results.values())
    total_errors  = sum(len(buckets["api_error"]) for buckets in results.values())

    passed = (total_invalid == 0 and total_errors == 0)

    subject = (
        EMAIL_SUBJECT_PASS
        if passed
        else EMAIL_SUBJECT_FAIL.format(invalid_count=total_invalid)
    )

    html_body = _build_html_body(results, passed, total_invalid, total_errors)

    return _send_email(subject, html_body)


# ---------------------------------------------------------------------------
# Email body — full detail (invalid values + filenames), matches main.py's
# console summary but rendered as HTML for email.
# ---------------------------------------------------------------------------

def _build_html_body(
    results: dict,
    passed: bool,
    total_invalid: int,
    total_errors: int,
) -> str:
    status_line = (
        "<p><b>Result: ALL DIMENSION VALUES VALID — safe to proceed with EPM load.</b></p>"
        if passed
        else f"<p><b>Result: {total_invalid} invalid value(s) found "
             f"across {sum(1 for b in results.values() if b['invalid'])} dimension(s) "
             f"— load would fail in EPM.</b></p>"
    )

    if total_errors:
        status_line += (
            f"<p style='color:#b00;'>Warning: {total_errors} value(s) could not be "
            f"checked due to an API error — see api_error rows below.</p>"
        )

    # Summary table
    rows = ""
    for dim, buckets in results.items():
        rows += (
            f"<tr>"
            f"<td>{dim}</td>"
            f"<td align='center'>{len(buckets['valid'])}</td>"
            f"<td align='center'>{len(buckets['invalid'])}</td>"
            f"<td align='center'>{len(buckets['api_error'])}</td>"
            f"</tr>"
        )

    summary_table = f"""
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background-color:#eee;">
            <th>Dimension</th><th>Valid</th><th>Invalid</th><th>API Error</th>
        </tr>
        {rows}
    </table>
    """

    # Detail section — invalid values + source filenames
    detail_html = ""
    for dim, buckets in results.items():
        if buckets["invalid"]:
            detail_html += f"<h4>{dim} — invalid values</h4><ul>"
            for value, files in buckets["invalid"].items():
                file_list = ", ".join(files)
                detail_html += f"<li><code>{value}</code> — found in: {file_list}</li>"
            detail_html += "</ul>"

        if buckets["api_error"]:
            detail_html += f"<h4>{dim} — could not validate (API error)</h4><ul>"
            for value, files in buckets["api_error"].items():
                file_list = ", ".join(files)
                detail_html += f"<li><code>{value}</code> — found in: {file_list}</li>"
            detail_html += "</ul>"

    return f"""
    <html>
      <body style="font-family: Arial, sans-serif; font-size: 13px;">
        {status_line}
        {summary_table}
        {detail_html}
        <p style="color:#888; font-size:11px;">Automated message from the EPM Pre-Load Validation pipeline.</p>
      </body>
    </html>
    """


# ---------------------------------------------------------------------------
# SMTP send — internal relay, no auth, STARTTLS on port 587
# ---------------------------------------------------------------------------

def _send_email(subject: str, html_body: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_EMAIL
    msg["To"]      = ", ".join(TO_EMAIL)
    if CC_EMAIL:
        msg["Cc"] = ", ".join(CC_EMAIL)

    msg.attach(MIMEText(html_body, "html"))

    recipients = TO_EMAIL + CC_EMAIL

    if not SMTP_PASSWORD:
        log.error(
            "EPM_SMTP_PASSWORD environment variable is not set — cannot authenticate. "
            "See the comment block above SMTP_HOST in config.py."
        )
        return False

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, recipients, msg.as_string())
        log.info("Email sent — subject: %s", subject)
        return True
    except Exception as exc:
        log.error("Failed to send email: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Entry point — smoke test
# Usage: python3 notifier.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sample_results = {
        "Product_Category": {
            "valid":     {"Food": ["retail_store_sales.csv"]},
            "invalid":   {"Frozen Meals": ["retail_store_sales.csv"]},
            "api_error": {},
        },
        "Tender_Type": {
            "valid":     {"Cash": ["retail_store_sales.csv"]},
            "invalid":   {},
            "api_error": {},
        },
    }

    ok = send_validation_email(sample_results)
    print("Email sent!" if ok else "Email failed — check logs above.")