# The scanners

BuilderBot runs its own static analysis stack on each node that holds
projects, from the **Scanners** page in the Containers group beside nginx.
Nothing is scanned on the controller and nothing of the controller's is
mounted on a node: each node runs the scanners over the projects whose node
it is and sends what they found up to the controller over the agent's own
API, where the Analysis page, each project's Analysis view and `bb findings`
read it ([building.md](building.md#static-analysis-reports)).

| Scanner | What it finds |
|---|---|
| Semgrep | bugs and risky patterns in the code, from the registry's curated rules |
| Trivy | vulnerable dependencies in lock files, secrets committed to a tree, misconfigured Dockerfiles and compose files |
| mobsfscan | the Android and iOS source Semgrep's general rules miss |

## What it needs

Docker on the node, which every node that runs builds has. Each scanner is
a one-shot container that lives only while it runs; the images and their
rule and vulnerability caches stay on the node between runs.

## Set it up

1. **Deploy.** The page lists every node. Press **Deploy** on a node that
   holds projects, or the bar's **Deploy on N nodes** for all of them at
   once: the controller writes the compose project to the node (the three
   scanners as services, their versions pinned to the newest known) and the
   node pulls the images, a job on the Jobs page. A node that hosts
   containers only holds no project and is not offered.
2. **Schedule.** One timetable runs every node's scanners: daily, weekly
   (Sundays at 4:00, the default) or monthly at 4:00, or a cron line of your
   own under Custom. **Turn on** starts it; **Run now on every node** runs
   it once, and each node's section has **Run now** for that node alone. A
   run is one job per node, one at a time there; one missed while the
   controller was down runs once when it is back, said as late.
3. **Read what they found.** Each run writes one SARIF per scanner on the
   node and sends it up as it finishes; the Analysis page shows it on its
   next look, grouped by project, and `bb findings history` says what
   changed between runs. A run that fails is on the bell with its log.

A project is scanned on its node, never on its extra nodes, so nothing is
scanned twice; a project moved to another node is scanned there next run.
The page's last section, **Not covered**, lists each project no scanner
reaches, with why: no node, a node that hosts containers only, or a node
with no scanners deployed.

## Keeping them current

The versions a node runs are pinned when it is deployed. The controller
reads Docker Hub and PyPI once a week for newer releases (**Check versions**
reads them now); a node behind says so in its section and on the bell, and
**Update** pins the newer versions there and pulls them. **Remove** takes
the scanners off a node, with their images and caches, and forgets the
reports it sent.

## Answering a finding

A finding that is not a problem is answered in the code, beside it, with
the reason: `# nosemgrep: RULE-ID (why this is safe)` on the flagged line
for Semgrep. The stack never runs Semgrep with its suppressions turned off,
and BuilderBot drops a finding the code marks this way, so the reason lives
with the line it is about and the Analysis page keeps to what is open.

## A scanner of your own, on the host

A scanner you run yourself can still hand BuilderBot its SARIF this
release: `SCANNER_REPORTS_PATH` (deprecated in 0.9.0 and removed in the
release after) names a folder on the host, mounted read-only at `/reports`
and read beside what the nodes send up. Reports must be SARIF 2.1.0, their
paths naming each project's directory.
