# Hyperion On-Prem Patch Automation (Java, OPatch, FMW/WebLogic, OHS)

Ansible playbooks that automate patching an on-premises Oracle Hyperion / EPM
environment — Java, OPatch (Middleware Home and OHS Home), FMW recommended
patches, the WebLogic Bundle Patch, and OHS patches — with email notification
of applied versions after each run.

## Why this exists

Oracle recently moved from a purely quarterly Critical Patch Update (CPU)
cadence to also include monthly Critical Security Patch Updates (CSPUs),
starting May 28, 2026, landing on the third Tuesday of each month going
forward. CSPUs deliver focused critical fixes between the existing quarterly
CPUs, which remain cumulative.

This only affects customer-managed environments — Oracle-managed cloud
services get these automatically. For anyone running on-prem Hyperion, a
patch cadence that used to happen four times a year now happens up to twelve
times a year. A manual patching process that "just barely worked" on a
quarterly cycle doesn't scale to monthly. This automation exists to make
that shift sustainable.

Full announcement: [Oracle Security Blog — Monthly CSPUs Begin May 28, 2026](https://blogs.oracle.com/security/update-monthly-critical-security-patch-updates-cspus-begin-may-28-2026)

## Structure
hyperion-patching/
├── group_vars/
│   └── all.yml              # shared config used by all three playbooks
├── java_opatch.yml           # Java install + OPatch upgrade (Middleware Home & OHS Home)
├── fmw_weblogic.yml          # FMW recommended patches + WebLogic Bundle Patch
├── ohs.yml                   # OHS patches
└── README.md

## Why three separate playbooks instead of one

Ansible plays run sequentially and stop on the first failure by default.
Bundling Java, OPatch, FMW, WebLogic, and OHS into a single playbook means
one failure partway through makes it hard to tell which layer actually
broke. These playbooks are also **dependency-ordered** — FMW, WebLogic, and
OHS patches all assume the latest OPatch version is already in place, so
Java/OPatch runs first, and the rest can be triggered independently once
that's confirmed successful. This also makes it possible to re-run just the
failed layer instead of re-running everything.

## What each playbook does

### `java_opatch.yml`
1. Finds and extracts the latest Java installation zip/tarball, renames the
   discovered JDK directory to a standard `jdk` folder, syncs it to the EPM
   destination
2. Upgrades OPatch in the **Middleware Home**
3. Upgrades OPatch in the **OHS Home** — a separate Oracle Home with its own
   independent OPatch install (see Gotchas below)
4. Sends an email summarizing the Java version and both OPatch versions

### `fmw_weblogic.yml`
1. Clears out any stale extracted patch directories, unarchives the latest
   FMW recommended patch zips, applies each via `opatch apply`, and
   validates the install
2. Unarchives the latest WebLogic Bundle Patch, runs an `opatch napply
   -report` **simulation** asynchronously first, waits for it to complete,
   then runs the real `opatch napply` only after the simulation succeeds
3. Runs `opatch util Obfuscate` against the Middleware Home
4. Emails a summary of applied FMW and WLS Bundle Patch versions

### `ohs.yml`
1. Clears stale extracted directories, unarchives the latest OHS patch
   zips, applies each via `opatch apply`, and validates the install
2. Runs `opatch util Obfuscate` against the OHS Home
3. Emails a summary of applied OHS patch versions

## Shared configuration (`group_vars/all.yml`)

All three playbooks read from a single shared vars file instead of
repeating paths in each one. Update paths once here; every playbook picks
them up automatically.

```yaml
patchpath: "/path/to/patches/"
jdkepmdest: "/path/to/epm/jdk/dest/"
opatchdest: "/path/to/middleware/home/"
ohsopatchdest: "/path/to/ohs/home/"
opatchhome: "/path/to/opatch/"
wlspatches: "/path/to/wls/bundle/patch/staging/"
middlewarehome: "/path/to/middleware/home/"
ohshome: "/path/to/ohs/home/"
ohspatchbp: "/path/to/ohs/patch/staging/"
smtp_host: "<smtp_hostname>"
smtp_port: 25
email_from: "<sender email id>"
email_to: "<distribution list>"
patch_log_dir: "/tmp/"
```

### Ansible Tower / AWX note

Ansible auto-loads `group_vars/all.yml` for every host, but **only when
it's placed inside the Project** (the repo Tower checks out and runs
`ansible-playbook` from) — not inside an SCM-sourced Inventory folder,
where group_vars loading is known to be unreliable in AWX/Tower. Keep
`group_vars/` at the root of this repo, alongside the playbooks, for it to
load correctly when run as a Tower Job Template.

## Requirements

- Ansible with access to target Hyperion/EPM on-prem hosts
- A host group (`DEV_HYP` in these playbooks — rename to match your
  inventory) with SSH/WinRM access and sufficient privileges to run OPatch
- Patch files pre-staged under the paths defined in `group_vars/all.yml`
  (`java/`, `opatch/`, `FMW/`, `WLS/`, `OHS/` subfolders under `patchpath`)
- SMTP relay access for the email notification steps

## Setup

1. Update `group_vars/all.yml` with your actual environment paths and SMTP
   details
2. Update `hosts: DEV_HYP` in each playbook to match your actual inventory
   group name
3. Fill in the placeholder OPatch install commands where noted in
   `java_opatch.yml`
4. Run in dependency order:
   ansible-playbook -i inventory.ini java_opatch.yml
   ansible-playbook -i inventory.ini fmw_weblogic.yml
   ansible-playbook -i inventory.ini ohs.yml

   (Or as separate Job Templates in Tower/AWX, chained in a Workflow
   Template in this order.)

## Gotchas learned building this

- **`find` returns files in arbitrary order.** Grabbing `files[0]` without
  sorting risks picking the wrong file when multiple matches exist in a
  staging folder. Fixed throughout with
  `sort(attribute='mtime', reverse=true)`.
- **`copy` with inline `content:` overwrites the whole destination file,
  it doesn't append.** Building up a log incrementally needs `lineinfile`
  with `insertafter: EOF` instead.
- **A local `vars:` block silently shadows `group_vars`.** Declaring the
  same variable name (even empty) in a play's own `vars:` overrides the
  shared config value — easy to miss even with a comment nearby saying
  "vars come from group_vars."
- **A missing `register:` fails silently, then breaks a later task.** The
  task itself runs fine; the error only surfaces when a downstream task
  references a variable that was never actually created.
- **`>` vs `>>` in shell redirects.** Using `>` where you meant to append
  wipes out everything written earlier in the same file — a common way to
  lose the date/hostname header you wrote in an earlier task.
- **`regex_replace('/n', ...)` is not a newline.** `/n` is a literal
  forward-slash-n; the correct escape is `'\\n'`. Silent no-op if you get
  this wrong — no error, just a regex that never matches.
- **Two Oracle Homes means two separate OPatch installs.** Middleware Home
  and OHS Home each need OPatch installed independently — it's not one
  install that covers the whole environment, and it's easy to assume
  otherwise until version-checking two homes reveals it.
- **Ansible Tower/AWX loads `group_vars` differently than plain CLI
  Ansible.** Place it in the Project repo root, not inside an
  SCM-sourced Inventory folder, or it may not load at all.

## License

MIT — see [LICENSE](LICENSE).

## Related write-up

Full breakdown of the business context, architecture decisions, and
patching gotchas: 
