# epm-level0-backup-notifier

A small, dependency-free pattern for running an Oracle EPM Cloud Level0
backup — via EPM Automate, for any mix of BSO, Hybrid, or ASO cubes —
with:

- structured logging
- a machine-readable JSON status report
- an HTML email summary — sent with plain `smtplib`, no third-party email
  service or API key required

The email/notification layer (`backup_notifier.py`) is generic and
doesn't know anything about EPM specifically — it just runs a script and
emails whatever JSON status that script produces. The backup logic
itself (`epm_level0_backup.sh`) is EPM Automate-specific by design,
since that's the actual tool doing the work.

Everything environment-specific (paths, cubes, email addresses, SMTP
server) lives in `config.ini` and the CONFIGURATION block at the top of
`epm_level0_backup.sh`. You shouldn't need to edit the rest of either
file to adapt this to your own EPM environment.

## Files

| File | Purpose |
|---|---|
| `config.ini` | Every setting you'll actually touch |
| `backup_notifier.py` | Runs the backup script, parses its status, sends the email |
| `epm_level0_backup.sh` | Runs a real EPM Automate Level0 export + download for any list of cubes (BSO, Hybrid, or ASO) |

No `requirements.txt` — `configparser`, `smtplib`, and `email` are all
part of the Python standard library, so there's nothing to `pip install`.
Any Python 3 install (3.6+) already has everything this needs.

## Two ways organizations send email

If you're deploying this at work rather than testing with a personal
account, you likely won't be using a personal Gmail/Office365 login at
all. There are two common patterns:

**1. Internal relay server (most common)** — your organization runs its
own SMTP relay that Linux or Windows servers send through directly. It's
typically allow-listed by the sending server's IP address or hostname
rather than requiring a login, and often runs unencrypted on port 25
since the traffic never leaves the internal network. Ask your infra or
network team for the relay's hostname — it's often something like
`smtp-relay.yourcompany.com` or an internal IP. In `config.ini`:

```ini
[smtp]
host = smtp-relay.yourcompany.com
port = 25
use_tls = false
auth_required = false
```

With `auth_required = false`, the script skips the password check and
login step entirely — `username`, `password_env_var`, and `password`
are all ignored.

**2. Direct authenticated send** — a real account (often a dedicated
service account rather than a person's own mailbox) logs in with a
username and password, same as the Gmail/Office365 examples above.
This is what `auth_required = true` (the default) does.

If you're not sure which applies to you, ask whoever manages your mail
servers — trying to authenticate against a relay that doesn't expect it
(or vice versa) is a common source of confusing errors.

## Testing it on your own machine first

You don't need a working backup job, a server, or cron to try this out —
the `--test-email` flag exercises the whole pipeline (config parsing,
HTML report building, SMTP send) using sample data, so you can confirm
your email setup works before wiring in anything real.

1. **Check your Python version** (3.6 or newer, any OS):
   ```bash
   python3 --version
   ```

2. **Get the files into one folder** and `cd` into it:
   ```bash
   cd backup-notifier
   ```
   No `pip install` step needed — everything used is standard library.

3. **Copy the config so you keep the template clean:**
   ```bash
   cp config.ini my_config.ini
   ```
   Open `my_config.ini` and fill in `to_addresses`, `from_address`, and
   the `smtp` section for whichever provider you're using (Gmail,
   Outlook, etc — see below).

4. **Set your email password as an environment variable** — never put it
   in the config file itself:
   - **macOS/Linux (bash/zsh):**
     ```bash
     export BACKUP_NOTIFIER_SMTP_PASSWORD="your-app-password"
     ```
   - **Windows (PowerShell):**
     ```powershell
     $env:BACKUP_NOTIFIER_SMTP_PASSWORD = "your-app-password"
     ```
   - **Gmail:** you need an [App Password](https://myaccount.google.com/apppasswords),
     not your normal account password (requires 2FA enabled on the account).
   - **Outlook/Office365:** `smtp.office365.com`, port 587, TLS.
   - **Any other provider:** ask them for their SMTP host/port — this
     works with anything that speaks standard SMTP+STARTTLS.
   Setting it this way means the password only lives in your terminal
   session, never on disk.

5. **Run the test:**
   ```bash
   python3 backup_notifier.py --config my_config.ini --test-email
   ```
   You should see `[INFO] Email sent successfully!` and get a sample
   HTML report in your inbox within a few seconds. If something's off,
   the error printed will tell you which piece to check — see
   "Troubleshooting" below.

6. **Fill in `epm_level0_backup.sh`'s CONFIGURATION section:**
   `EPM_BIN`, `APP_URL`, `USERNAME`, `PASSWORD` (the path to an encrypted
   password file — create one with `epmautomate encrypt`, never a plain
   password), and the `CUBES` array. `CUBES` can mix BSO, Hybrid, and
   ASO cubes freely — the Level0 export command works the same way for
   all three (Oracle's docs specify `level=0` is valid for both ASO and
   BSO/Hybrid cubes; only `level=All` is BSO/Hybrid-only, and this
   script doesn't use it).

7. **Point `config.ini`'s `backup_script` at its full path, then run it:**
   - **macOS/Linux:** Bash is native.
     ```bash
     chmod +x epm_level0_backup.sh
     python3 backup_notifier.py --config my_config.ini
     ```
   - **Windows:** `backup_notifier.py` invokes the backup script with
     `bash`, so you'll need Bash available — either
     [WSL](https://learn.microsoft.com/windows/wsl/install) or Git Bash.
     Everything else (the Python side) runs natively on Windows either way.

8. **Once you're happy with it, wire it into cron / a scheduler:**
   ```
   0 2 * * * cd /path/to/backup-notifier && python3 backup_notifier.py --config my_config.ini >> /path/to/logs/cron.log 2>&1
   ```

## Why the script clears the EPM outbox before each export

`exportEssbaseData` writes its zip into the EPM Cloud application's
outbox — it doesn't get deleted automatically after you download it.
Left alone, that outbox accumulates a Level0 export zip per cube per
run, indefinitely.

That matters for more than just tidiness. The outbox is shared storage
against your EPM Cloud instance, and a growing pile of old export files
in it:
- eats into your application's storage allocation over time
- slows down anything that lists or scans the outbox (including this
  script's own `listfiles` verification step, and Inbox/Outbox Explorer
  in the UI)
- risks a stale file with the same name silently sitting there from a
  failed prior run, which can make it unclear whether a fresh export
  actually succeeded

That's why `epm_level0_backup.sh` runs a `deletefile` on each cube's
expected outbox zip *before* running that cube's export (the
`PRE-STEP` block), rather than relying on `exportEssbaseData` to
overwrite it cleanly. It's a small step, but it keeps the outbox at a
predictable, minimal footprint run over run instead of growing
unbounded — worth keeping even if you adapt this script further.

## Troubleshooting

| You see | Likely cause |
|---|---|
| `SMTP password not found` | The env var isn't set in the shell you ran the script from — check it's the same terminal session |
| `[ERROR] Email failed: ... 401/403` | Wrong password, or (for Gmail) using your real password instead of an App Password |
| `[ERROR] Email failed: ... 400` | Duplicate recipient across `to_addresses`/`cc_addresses` (some providers are case-insensitive about this too) |
| `[ERROR] Email failed: ...timed out` | A firewall on your network/host is blocking outbound SMTP — try a different network or check with your IT/hosting provider |
| `Config file not found` | Check the `--config` path is relative to where you're running the command from, not where the file lives |

## The status JSON contract

`epm_level0_backup.sh` already writes JSON in this shape, but if you
adapt the backup script further, keep the contract:
- print the **path to a JSON status file as the last line of stdout**
- write that JSON in this shape:

```json
{
  "overall_status": "SUCCESS",
  "run_date": "2026-08-15 02:00:00",
  "hostname": "myserver",
  "backup_dir": "/path/to/backups",
  "retention_days": 90,
  "log_file": "/path/to/logs/run.log",
  "purge_count": 2,
  "cubes": [
    {
      "cube": "SALRPT",
      "status": "SUCCESS",
      "started": "02:00:00",
      "completed": "02:05:00",
      "elapsed": "5.00mins",
      "local_file": "SALRPT_level0_backup.zip",
      "file_size": "120MB",
      "notes": "Backup downloaded successfully — zip retained in EPM outbox"
    }
  ]
}
```

`backup_notifier.py` reads this and renders it into the HTML report —
add or remove cubes freely in the `CUBES` array, the table just
grows/shrinks with them.

## Before you make anything public

If you're adapting a script from a real, working job (like this one was),
double-check for:

- internal hostnames or URLs
- real email addresses
- API keys, service account filenames, or project IDs
- company or product names that don't need to be there

Search-and-replace those with placeholders before publishing — it's easy
to miss one in a script that's been copy-pasted and edited a few times.

## Common gotcha: duplicate recipients

Most SMTP/email APIs reject a message where the same address appears in
both `to_addresses` and `cc_addresses` in `config.ini` (some are
case-insensitive about it too — `Jane@x.com` and `jane@x.com` count as
the same address). Keep each recipient in one list only.
