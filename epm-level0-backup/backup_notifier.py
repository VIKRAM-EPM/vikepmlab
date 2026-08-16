#!/usr/bin/env python3
# =============================================================================
# backup_notifier.py
#
# Generic backup-job wrapper:
#   1. Runs any backup script you point it at
#   2. Reads the JSON status file that script produces
#   3. Emails an HTML report via plain SMTP (no third-party email service
#      required — works with Gmail, Outlook, or any SMTP relay)
#
# Everything environment-specific lives in config.ini. You should not
# need to edit this file at all to use it in your own project.
#
# Usage:
#   python3 backup_notifier.py --config config.ini
#   python3 backup_notifier.py --config config.ini --test-email
#
# Requirements: none — configparser, smtplib, and email are all part of
# the Python standard library. No pip install needed at all.
# =============================================================================

import argparse
import configparser
import json
import os
import smtplib
import ssl
import subprocess
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ================== CONFIG LOADING ==================
def _split_list(raw):
    """Comma-separated string -> list of stripped, non-empty items."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def load_config(path):
    """
    Reads config.ini and returns a plain nested dict shaped the same way
    the rest of this script expects (mirrors the old YAML structure), so
    build_html()/send_email() don't need to know or care that the file
    is INI rather than YAML.
    """
    if not os.path.exists(path):
        print(f"[ERROR] Config file not found: {path}")
        sys.exit(1)

    parser = configparser.ConfigParser()
    parser.read(path)

    return {
        "job": {
            "name": parser.get("job", "name", fallback="Backup Job"),
            "backup_script": parser.get("job", "backup_script", fallback=""),
        },
        "email": {
            "enabled": parser.getboolean("email", "enabled", fallback=True),
            "from_address": parser.get("email", "from_address", fallback=""),
            "to_addresses": _split_list(parser.get("email", "to_addresses", fallback="")),
            "cc_addresses": _split_list(parser.get("email", "cc_addresses", fallback="")),
            "subject_prefix": parser.get("email", "subject_prefix", fallback=""),
        },
        "smtp": {
            "host": parser.get("smtp", "host", fallback=""),
            "port": parser.getint("smtp", "port", fallback=587),
            "use_tls": parser.getboolean("smtp", "use_tls", fallback=True),
            # False for an internal relay server that allow-lists by
            # source IP/hostname instead of requiring a login (common
            # for a service account on a Linux box, or a Windows box
            # relaying through Exchange). True for anything needing a
            # real username/password (Gmail, Office365 direct, etc).
            "auth_required": parser.getboolean("smtp", "auth_required", fallback=True),
            "username": parser.get("smtp", "username", fallback=""),
            "password_env_var": parser.get("smtp", "password_env_var", fallback="BACKUP_NOTIFIER_SMTP_PASSWORD"),
            # Optional — a password typed directly into the file. Only
            # meant for quick local testing; leave this blank for
            # anything you'd publish or commit. See send_email() for
            # how this is used.
            "password": parser.get("smtp", "password", fallback=""),
        },
        "retention": {
            "days": parser.getint("retention", "days", fallback=90),
        },
    }


# ================== RUN BACKUP SCRIPT ==================
def run_backup(script_path):
    print(f"[{datetime.now()}] Starting backup script: {script_path}")
    result = subprocess.run(["bash", script_path], capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    # Convention: the LAST line of stdout is the path to the JSON status file
    stdout_lines = result.stdout.strip().splitlines()
    status_file = stdout_lines[-1].strip() if stdout_lines else ""
    return status_file, result.returncode


# ================== READ JSON STATUS ==================
def read_status(status_file):
    if not status_file or not os.path.exists(status_file):
        print(f"[ERROR] Status file not found: {status_file}")
        return None
    with open(status_file, "r") as f:
        return json.load(f)


# ================== BUILD HTML EMAIL ==================
def build_html(job_name, data):
    overall = data.get("overall_status", "UNKNOWN")
    run_date = data.get("run_date", "N/A")
    hostname = data.get("hostname", "N/A")
    backup_dir = data.get("backup_dir", "N/A")
    log_file = data.get("log_file", "N/A")
    retention = data.get("retention_days", "N/A")
    purge_cnt = data.get("purge_count", 0)
    targets = data.get("targets", data.get("cubes", []))  # accept either key

    status_color = {"SUCCESS": "#2e7d32", "FAILURE": "#c62828", "WARNING": "#e65100"}.get(overall, "#333")

    rows = ""
    for t in targets:
        status = t.get("status", "")
        row_color = {"SUCCESS": "#e8f5e9", "FAILURE": "#ffebee", "WARNING": "#fff3e0"}.get(status, "#fff")
        text_color = {"SUCCESS": "#2e7d32", "FAILURE": "#c62828", "WARNING": "#e65100"}.get(status, "#333")

        rows += f"""
        <tr style="background:{row_color}">
            <td><b>{t.get('name', t.get('cube', ''))}</b></td>
            <td style="color:{text_color};font-weight:bold">{status}</td>
            <td>{t.get('started', '')}</td>
            <td>{t.get('completed', '')}</td>
            <td>{t.get('elapsed', '')}</td>
            <td>{t.get('local_file', '')}</td>
            <td>{t.get('file_size', '')}</td>
            <td>{t.get('notes', '')}</td>
        </tr>"""

    return f"""
<!DOCTYPE html>
<html>
<head>
<style>
  body     {{ font-family: Arial, sans-serif; font-size: 13px; color: #333; }}
  h2       {{ color: #003366; margin-bottom: 4px; }}
  table    {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
  th       {{ background: #003366; color: #fff; padding: 8px 10px; text-align: left; font-size: 12px; }}
  td       {{ padding: 7px 10px; border: 1px solid #ddd; vertical-align: top; }}
  .badge   {{ display: inline-block; padding: 4px 12px; border-radius: 4px; color: #fff; font-weight: bold; background: {status_color}; }}
  .section {{ margin-top: 22px; font-weight: bold; font-size: 14px; color: #003366; border-bottom: 2px solid #003366; padding-bottom: 3px; margin-bottom: 8px; }}
  .meta td {{ border: none; padding: 3px 10px; }}
  .footer  {{ margin-top: 20px; font-size: 11px; color: #aaa; }}
</style>
</head>
<body>

<h2>{job_name} Report</h2>
<p><span class="badge">{overall}</span></p>

<div class="section">Run Information</div>
<table class="meta">
  <tr><td><b>Run Date</b></td><td>{run_date}</td><td><b>Server</b></td><td>{hostname}</td></tr>
  <tr><td><b>Backup Directory</b></td><td>{backup_dir}</td><td><b>Retention Policy</b></td><td>{retention} days</td></tr>
  <tr><td><b>Log File</b></td><td colspan="3" style="font-size:11px">{log_file}</td></tr>
  <tr><td><b>Old Backups Purged</b></td><td>{purge_cnt}</td><td></td><td></td></tr>
</table>

<div class="section">Backup Detail</div>
<table>
  <tr><th>Target</th><th>Status</th><th>Started</th><th>Completed</th><th>Elapsed</th><th>File</th><th>Size</th><th>Notes</th></tr>
  {rows}
</table>

<div class="footer">Automated message from {job_name} on {hostname}. Do not reply.</div>

</body>
</html>"""


# ================== SEND EMAIL (plain SMTP — free, no API key) ==================
def send_email(cfg, data, html_body):
    email_cfg = cfg["email"]
    smtp_cfg = cfg["smtp"]

    if not email_cfg.get("enabled", True):
        print("[INFO] Email disabled in config — skipping send.")
        return

    auth_required = smtp_cfg.get("auth_required", True)
    password = ""

    if auth_required:
        # Prefer a password typed directly into config.ini (quick local
        # testing); fall back to the environment variable (the safer
        # option for anything real or published).
        password = smtp_cfg.get("password", "")
        if password:
            print("[WARNING] Using SMTP password from config.ini directly. "
                  "Fine for local testing — don't commit or publish this file as-is.")
        else:
            password = os.environ.get(smtp_cfg["password_env_var"], "")

        if not password:
            print(f"[ERROR] SMTP password not found. Either set smtp.password in "
                  f"config.ini, or set the environment variable: {smtp_cfg['password_env_var']}")
            return
    else:
        print("[INFO] auth_required = false — connecting to relay without a login.")

    overall = data.get("overall_status", "UNKNOWN")
    run_date = data.get("run_date", "")
    subject = f"{email_cfg.get('subject_prefix', '')} {overall} [{run_date}]".strip()

    to_addresses = email_cfg.get("to_addresses", [])
    cc_addresses = email_cfg.get("cc_addresses", []) or []

    msg = MIMEMultipart("alternative")
    msg["From"] = email_cfg["from_address"]
    msg["To"] = ", ".join(to_addresses)
    if cc_addresses:
        msg["Cc"] = ", ".join(cc_addresses)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    all_recipients = to_addresses + cc_addresses

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_cfg["host"], smtp_cfg["port"]) as server:
            if smtp_cfg.get("use_tls", True):
                server.starttls(context=context)
            if auth_required:
                server.login(smtp_cfg["username"], password)
            server.sendmail(email_cfg["from_address"], all_recipients, msg.as_string())

        print("[INFO] Email sent successfully!")
        print(f"  Subject : {subject}")
        print(f"  To      : {to_addresses}")
        print(f"  Cc      : {cc_addresses}")
    except Exception as e:
        print(f"[ERROR] Email failed: {e}")


# ================== TEST DATA (for --test-email) ==================
def sample_data():
    return {
        "overall_status": "SUCCESS",
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "local-host",
        "backup_dir": "/path/to/backups",
        "retention_days": 90,
        "log_file": "/path/to/logs/test_log.log",
        "purge_count": 0,
        "targets": [
            {
                "name": "example_target",
                "status": "SUCCESS",
                "started": "10:00:00",
                "completed": "10:05:00",
                "elapsed": "5m",
                "local_file": "example_target_backup.zip",
                "file_size": "12MB",
                "notes": "test run — no real backup performed",
            }
        ],
    }


# ================== MAIN ==================
def main():
    parser = argparse.ArgumentParser(description="Generic backup job + email notifier")
    parser.add_argument("--config", default="config.ini", help="Path to config.ini")
    parser.add_argument("--test-email", action="store_true",
                         help="Skip running the backup script — send a sample report email instead")
    args = parser.parse_args()

    cfg = load_config(args.config)
    job_name = cfg["job"]["name"]

    if args.test_email:
        data = sample_data()
        html = build_html(job_name, data)
        send_email(cfg, data, html)
        sys.exit(0)

    status_file, bash_rc = run_backup(cfg["job"]["backup_script"])
    data = read_status(status_file)

    if not data:
        data = {
            "overall_status": "FAILURE",
            "run_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "hostname": os.uname().nodename if hasattr(os, "uname") else "local-host",
            "targets": [],
        }
        html = f"<p><b>{job_name} script failed to produce a status file.</b> Check the server logs directly.</p>"
    else:
        html = build_html(job_name, data)

    send_email(cfg, data, html)
    sys.exit(bash_rc)


if __name__ == "__main__":
    main()