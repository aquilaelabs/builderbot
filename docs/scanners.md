# Setting up the static analysis stack

BuilderBot does not scan code itself. A scanner run on the host reads every
project on the share and writes its findings as SARIF into a reports folder;
the controller reads that folder, read-only, at `/reports`, and shows what is
there on the Analysis page, in each project's Analysis view and to a session
through `bb findings` ([building.md](building.md#static-analysis-reports)).
This page sets up the three scanners BuilderBot's own stack runs, and a
script that runs them.

| Scanner | What it finds |
|---|---|
| Semgrep | bugs and risky patterns in the code, from the registry's curated rules |
| Trivy | vulnerable dependencies in lock files, secrets committed to a tree, misconfigured Dockerfiles and compose files |
| mobsfscan | the Android and iOS source Semgrep's general rules miss |

## What it needs

Docker on a machine that sees the share BuilderBot's `/workspace` is, and a
folder for the reports. Nothing else: the script is plain `docker run`, so it
runs as it is on Unraid (no Compose plugin, no checkout of BuilderBot) and on
any Linux host with Docker. Each scanner's container lives only while it
runs.

## Set it up

1. Point BuilderBot at the reports folder: `SCANNER_REPORTS_PATH` in its
   env file (or the Unraid template's *Scanner reports* path) names the
   folder on the host, mounted read-only at `/reports`
   ([reference.md](reference.md)). The default is
   `/mnt/user/appdata/scanners/reports`. Restart the container after a change.
2. Put `tools/scan.sh` on the host. On Unraid: the User Scripts plugin, Add
   New Script, and paste the file's contents in. Set the three paths at its
   top if the shares differ from Unraid's defaults: `SCANNER_SOURCE_PATH`,
   the share the projects are on, which the scanners read and never write;
   `SCANNER_REPORTS_PATH`, the same folder as step 1; and
   `SCANNER_CACHE_PATH`, where the scanners keep their rules and
   vulnerability database between runs. Each can come from the environment
   instead.
3. Run it once by hand (Run Script, or `sh scan.sh`). Each scanner runs in
   turn, a few minutes each on a large share and Trivy longest on its first
   run while it fetches its database, and says where it wrote its report.
   The Analysis page shows the findings on its next look.
4. Run it weekly: the Schedules page beside Jobs carries it as a built-in
   schedule ([machines.md](machines.md#schedules)), off until you turn it on
   with the node it runs on and its two paths, then Sundays at 4:00. The User
   Scripts plugin's Custom schedule (`0 4 * * 0`) or a cron line elsewhere do
   the same off BuilderBot. Every run replaces the reports, and `bb findings
   history` says what changed between them.

`scan.sh semgrep` runs one of them; a scanner that fails leaves its last
report where it was and the script exits non-zero, naming it.

## Answering a finding

A finding that is not a problem is answered in the code, beside it, with
the reason: `# nosemgrep: RULE-ID (why this is safe)` on the flagged line
for Semgrep. The stack never runs Semgrep with its suppressions turned off,
and BuilderBot drops a finding the code marks this way, so the reason lives
with the line it is about and the Analysis page keeps to what is open. A
finding that is a problem goes on the project's bug tracker like any other.

## The versions

`tools/scan.sh` pins each scanner's image or package version at its top
(`SEMGREP_VERSION`, `TRIVY_VERSION`, `MOBSFSCAN_VERSION`, each overridable
from the environment). Move them on purpose: a new Semgrep can add rules, and a
report that grows overnight should be because the code changed, not the
scanner.
