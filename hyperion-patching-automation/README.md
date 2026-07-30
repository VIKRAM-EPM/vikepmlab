# Hyperion On-Prem Patch Automation (Java, OPatch, FMW/WebLogic, OHS)

Ansible playbooks that automate patching an on-premises Oracle Hyperion / EPM
environment — Java, OPatch (Middleware Home and OHS Home), FMW recommended
patches, the WebLogic Bundle Patch, and OHS patches — with email notification
of applied versions after each run. Target environment is selected at
run time via an Ansible Tower Survey.

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
```
hyperion-patching/
├── group_vars/
│   └── all.yml                    # shared config used by all three playbooks
├── Hyp_Java_Opatch.yml             # Java install + OPatch upgrade (Middleware Home & OHS Home)
├── Hyp_FMW_Weblogic.yml            # FMW recommended patches + WebLogic Bundle Patch
├── Hyp_OHS.yml                     # OHS patches
└── README.md
```
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

### `Hyp_Java_Opatch.yml`
1. Finds and extracts the latest Java installation zip/tarball, renames the
   discovered JDK directory to a standard `jdk` folder, syncs it to the EPM
   destination
2. Upgrades OPatch in the **Middleware Home**
3. Upgrades OPatch in the **OHS Home** — a separate Oracle Home with its own
   independent OPatch install (see Gotchas below)
4. Sends an email summarizing the Java version and both OPatch versions

### `Hyp_FMW_Weblogic.yml`
1. Clears out any stale extracted patch directories, unarchives the latest
   FMW recommended patch zips, applies each via `opatch apply`, and
   validates the install
2. Unarchives the latest WebLogic Bundle Patch, runs an `opatch napply
   -report` **simulation** asynchronously first, waits for it to complete,
   then runs the real `opatch napply` only after the simulation succeeds
3. Runs `opatch util Obfuscate` against the Middleware Home
4. Emails a summary of applied FMW and WLS Bundle Patch versions

### `Hyp_OHS.yml`
1. Clears stale extracted directories, unarchives the latest OHS patch
   zips, applies each via `opatch apply`, and validates the install
2. Runs `opatch util Obfuscate` against the OHS Home
3. Emails a summary of applied OHS patch versions
   

## Why Obfuscate runs after every patch

Both `Hyp_FMW_Weblogic.yml` and `Hyp_OHS.yml` run `opatch util Obfuscate`
after applying patches. This isn't cleanup — OPatch keeps backup copies of
every file it replaces in `.patch_storage` inside the Oracle Home, and
security vulnerability scanners sometimes can't distinguish those old
backup files from the live, in-use files. A scanner matching against known
vulnerable file signatures can flag a fully patched server as unpatched,
purely because of a stale backup copy sitting in storage.

`opatch util Obfuscate` scrambles the contents of those backup files so
scanners stop matching against them. Oracle introduced it specifically to
cut down false positives from tools scanning for things like log4j. On a
monthly CSPU cadence, avoiding false positives on every scan cycle isn't
optional — it's part of what makes the cadence sustainable rather than a
source of recurring noise.

## Selecting the target environment (Ansible Tower Survey)

All three playbooks target `hosts: "{{ target_env }}"` — a variable
supplied at run time rather than hardcoded per playbook. In Ansible Tower/
AWX, this is set up as a Job Template Survey:

1. Job Template → **Survey** tab → **Add**
2. **Question:** "Which environment do you want to patch?"
3. **Answer variable name:** `target_env`
4. **Answer type:** Multiple Choice (single select)
5. **Answer choices:** must exactly match your real inventory group names
   (e.g. `DEVHYP`, `DEVOHS`)

Running from the CLI instead of Tower works the same way, via `-e`:

ansible-playbook -i inventory.ini Hyp_Java_Opatch.yml -e target_env=DEVHYP

**Important:** the Survey's answer choices must be the literal inventory
group names — see the Gotchas section below for why an indirection/lookup
table (mapping a survey label to a group name) does not work here.

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
- Inventory host groups matching your environment names (e.g. `DEVHYP`,
  `DEVOHS`) with SSH access and sufficient privileges to run OPatch
- Patch files pre-staged under the paths defined in `group_vars/all.yml`
  (`java/`, `opatch/`, `FMW/`, `WLS/`, `OHS/` subfolders under `patchpath`)
- SMTP relay access for the email notification steps

## Setup

1. Update `group_vars/all.yml` with your actual environment paths and SMTP
   details
2. Confirm your inventory host group names match what you'll use as
   Survey answer choices (or `-e target_env=...` values)
3. Fill in the placeholder OPatch install commands where noted in
   `Hyp_Java_Opatch.yml`
4. Run in dependency order:

ansible-playbook -i inventory.ini Hyp_Java_Opatch.yml -e target_env=DEVHYP
ansible-playbook -i inventory.ini Hyp_FMW_Weblogic.yml -e target_env=DEVHYP
ansible-playbook -i inventory.ini Hyp_OHS.yml -e target_env=DEVOHS

(Or as separate Job Templates in Tower/AWX, each with its own Survey,
   chained in a Workflow Template in this order.)

## Testing before running against real hosts

Every playbook can be validated safely before pointing it at a real
environment:

1. **Syntax check** — catches YAML/Jinja errors:
ansible-playbook Hyp_Java_Opatch.yml --syntax-check

2. **Host resolution check** — confirms `target_env` correctly targets the
   intended group, without running anything:
   ansible-playbook -i inventory.ini Hyp_Java_Opatch.yml -e target_env=DEVHYP --list-hosts
   
4. **Dry logic test** — point `patchpath` at a folder of harmless staged
   fake zip files (via `-e patchpath=/tmp/patchtest/`) and run against a
   `localhost`-mapped test inventory to confirm file discovery, sorting,
   and extraction logic before ever touching real `opatch`/`java`
   commands against a live Oracle Home.

All three playbooks in this repo were validated this way — syntax-checked,
host-resolution-checked, and run end-to-end against staged fake patch files
with zero failures, including a second run to confirm idempotency.

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
- **`group_vars` cannot drive a play's `hosts:` line — not even a fully
  static value with zero templating.** Only true global-scope sources
  (extra-vars, i.e. a Tower Survey answer, or `-e` on the CLI) are
  available early enough to resolve which hosts a play targets. An
  indirection layer — a lookup table in `group_vars` mapping a survey
  label to a real group name — will silently fail with "variable is
  undefined," even though that same variable works fine everywhere else
  in the playbook. The fix: reference the Survey extra-var directly in
  `hosts:`, and make the Survey's answer choices match your real
  inventory group names exactly.

## License

MIT — see [LICENSE](LICENSE).

## Related write-up

Full breakdown of the business context, architecture decisions, and
patching gotchas: https://www.vikepmlab.com/automating-hyperion-on-prem-patching-for-oracles-new-monthly-cspu-cadence/
   

