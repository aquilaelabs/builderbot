# Building, testing and releasing

A project builds, tests and runs its CI on its node, never on the controller.
This doc covers `bb build`, `bb test` and `bb run`, the test registry, CI
runners and reading CI's logs, the scanner's findings, what lands in
`dist/`, and signing and publishing a release. The toolchains a build needs
are in [toolchains.md](toolchains.md).

## Building on a project's node

**Building there.** A project names its node in its settings (Nodes): one
node for everything it does off this box: containers, builds, tests, CI and
emulation, and gives its build and test commands and the output globs. It
can add other nodes it also works on (R82): its containers may live on any
of those and nowhere else, and a session start asks which node when there
is more than one. A project with no node has no default to fall to and is
told to set one.
**Nothing runs that nobody wrote down**: with a field empty, `bb build` and
`bb test` refuse and say how to fill it. The person who knows how a tree
builds is often the session that has just read it, so a session can:
`bb settings set test "./gradlew test"` (or `build`, or `outputs`), and
what happens then is the project's fourth gate, beside the three for the
notebook: auto lands it, ask holds it on the notebook for approval with the
command in full, deny refuses it with a sentence the session quotes. Only
those three fields have a verb; the node, the git policy and the gates
themselves stay the settings'. `bb build`, `bb test` and `bb run -- CMD` snapshot the working
tree here, dirty edits included, run on that node in a workspace of the job's
own, and stream the log back; what the outputs match comes back into `dist/`
by name with a provenance record beside it, which the Artifacts view shows on
the row (which job, which node, which snapshot). The Artifacts view's **Download
source** hands over the code base itself as a zip through the browser: what
git tracks and would track, under one directory named for the project, never
`.git`, `dist/` or what `.gitignore` hides. A failed build keeps its
workspace on the node for a look, and says where. The census reports each
node's cache size beside **Clear cache**, and the Library takes a node in the
Build group's header: installing a toolchain there is a job that carries `bb` and the
catalog to the node's own toolchain store.

## The test registry

**The test registry** is a project page's Tests view, under Code, and `bb tests` in a
terminal. It answers two questions that are only worth keeping together: what
each test protects, and what the suite actually spends its time on.

The first half is written by hand, in the same change as the test: what
breaks if it goes red, and what it really exercises (which fixtures, which
stubs, what is real and what is faked). The second half is not written by hand
at all: `bb tests ingest` parses a run's own output, because a self-reported
estimate is a guess that ages and reads exactly like a measurement.

```bash
BB_TEST_TIMING=1 bb dashboard test 2>&1 | tee /tmp/run.log
bb tests ingest /tmp/run.log
```

How many workers a test run may use on a node is the node's to say: **Test
workers** in the Sessions section of its page under Nodes, 0 for the
machine's cores, handed to every test job there as `BB_TEST_WORKERS` for
the project's own test command to read (`pytest -n`, `--test-concurrency`,
`--max-workers`) and read by this harness as the most suites it runs at once
(roadmap R81). Under that ceiling its workers take suites from one queue,
longest first, each taking the next only while the machine has room (1.5 GB
of memory free and a load under one and a half times its cores; the suites
run at the lowest priority, so their own load does not hold the next back),
so a node busy with the emulator or a docker build runs fewer; the run's last lines say what bounded
it, a suite that was its floor, the machine, or its reruns (R130).

Ingesting is the CLI's and deliberately not an endpoint: every body the server
takes is capped at 64kB and a run log is a couple of hundred, so an action for
it would answer "body too large" for the only input it was for. It also
belongs there: reading a runner's output is work for the machine the runner
ran on.

**Every file starts from the same world.** The harness builds its fixture
once (projects, accounts, the stub node, the store), keeps a copy, and before
each file stops the server and the stub agent, puts the copy back and starts
both again, about a second and a half per file. What one file creates (a
node, an account, a setting, a job, anything the server keeps in memory)
cannot reach the next. A file that fails in a whole run is run once more,
alone, in a world of its own: if it passes it is reported as **flaky**, by
name, above the verdict, and never folded into a pass; if it fails again it
is a failure. The registry records the first run's timings, not the
retry's.

A test is keyed on **where the runner puts it** (`<file>#<ordinal>`) rather
than on its name, so rewording one keeps its description. Ingest reconciles
the list against the roster it just read: longest common subsequence on the
names first, then position for whatever is left, so a rename in place is a
rename, a test inserted in the middle shifts nobody's entry, and what
genuinely arrived or went is the **drift report**. That report is the point of
the thing: a registry that has quietly stopped describing the code is worse
than no registry.

The view is sorted by duration, longest first, with the projected suite time
in the header. Suites roll up in a fold above it, because one file dominating
is a more useful fact than one slow test. A continuation: the names here are
prose, and the ones beginning `...` only read correctly next to what they
follow: carries that link on its own row, so sorting by duration cannot
orphan it. Status shows when it is not a pass, skipped included: a skipped
test still burns wall time.

And anything landing **just above a round boundary** (30.0s, 10.0s, 5.0s) is
flagged. A fixed wait sits on its boundary and picks up a little overhead; it
never lands below one. Those are waiting rather than working, the header
totals what they would give back, and they are the cheapest thing in a suite
to fix.

## CI runners

The **CI runner** page (Build > CI runner) lists every node's CI runner
(this container runs none), one row each with its state (listening, idle;
running a job; quiet; install failed, with when and why; installing;
removing), above the chosen node's runner section, where one is installed,
started or removed, with the `runs-on` line that pins a job to its node. A
row picks its node.

**CI runners per node, one per git host.** The runner section lists the
node's runners and adds one with its host, address and token (kept root-only on
the controller): GitHub's runner and Gitea's `act_runner` (published as gitea-runner since it moved to gitea/runner) side by side,
each registered with labels `builderbot, self-hosted, linux, <arch>, <node
name>` plus any extra, so a workflow's `runs-on` names the node it should
land on whichever host its repository is on. Each row says whether its
runner is listening or busy; Remove deregisters it first. `bb ci-labels` lists every label the registry knows
and `--write` regenerates `.github/actionlint.yaml` from them, so the lint
checks `runs-on` against runners that exist. This container runs no runner
of its own.

**A project's node does not decide where its CI runs, and nothing can make
it.** That setting governs BuilderBot's own queue: `bb build`, `bb test`,
`bb run`, `bb emu`, compose. Actions dispatch belongs to GitHub, which reads
`runs-on` and nothing else, so with runners on two nodes a label both carry
sends the job to whichever is idle: possibly the machine without the
toolchain, silently. The node's own name is already a label on its runner, so
pinning is one word:

```yaml
runs-on: [self-hosted, alpha-vm]
```

The CI runner page prints that line for each node, and `bb lint` says when
a project has a node and its workflows do not carry it: a note, not a
failure, because the workflow file is the repo's and this is advice. A
`runs-on` built from an expression is left alone: choosing the runner at
dispatch is a deliberate act, not a workflow that forgot.

## Reading CI from inside the container

A self-hosted runner streams a job's console output to GitHub and keeps none
of it, and with no git token here there is no API to ask either. So the lint
workflow archives its own output, and so does the `dashboard
tests` workflow beside it, which carries the browser suite: each check is
teed into
`ci-logs/<repo>/<run-id>-<attempt>.log` under the runner's node's data store
(the agent writes that path into the runner's `.env`, beside the node's
toolchain environment: the same one every `bb` job there gets, so CI sees
the store's node, Playwright and JDK, and a session on the node can read
what its runner archived), with a header
naming the commit, ref and event, and a `result:` line written by an
`if: always()` step so a job that died still says so. `bb ci-log` fetches the
newest from the project's node, `--list` shows the twenty kept with their
results, and a run id picks one.

The image build is the exception that proves it: it runs on a hosted runner, so
nothing it prints is reachable from in here. Its last job comes back to a
node (`runs-on: [self-hosted, bb-sandbox]`) and archives the *outcome* into
the same directory: result, trigger, version, digest, how long it took, and whether
the layer cache was used. Not the console output, which is gone; enough to
answer "did that build land, and why did the host re-pull a gigabyte?".

## CI on GitHub's runners, and CI watched

**CI on GitHub's own runners.** A job on a hosted runner keeps no log
anywhere BuilderBot reaches, and GitHub hands a run's log only to a token,
even on a public repository. So when every workflow of a project names a
hosted label rather than `self-hosted`, `bb ci-log` asks the controller
(`/api/ci-runs`, `cilogs.py`), which asks GitHub with the project's own
token or the shared PAT: `--list` is the newest runs, and a run (the newest
finished one when none is named) is its jobs, the step that failed, and the
last 400 lines of each failed job's log. The log answers with a redirect to
GitHub's storage, and the token is not sent on to it. R115.

**CI watched without anybody asking.** A project's CI drifts on GitHub's
schedule, not the project's: a runner label is repointed, an action's old
major stops working when GitHub retires the Node it runs on. The controller looks at every project with
workflows once a day, and at once when one is linked (`ciwatch.py`): the
tree's workflows (`.github/workflows`, and `.gitea/workflows` and
`.forgejo/workflows` for a repository on those hosts) for a GitHub-hosted
job on a moving `-latest` label and for each action against its newest
release, and on GitHub, with the token `bb ci-log`
uses, whether the newest run on the main branch passed and what GitHub wrote
on it (its warnings about a retired Node or a label about to move). What it
finds is kept under `ciwatch/` in the state, shown as the Git view's CI
section (with Check now), printed by `bb catchup`, and, while main is red,
a bell row. It reads and never changes anything; nothing in a repository
needs setting up, so every BuilderBot and every project gets it. R117.

## Static analysis reports

The scanners that write these reports are BuilderBot's own, deployed to
each node and run on a schedule from the Scanners page
([scanners.md](scanners.md)); each node sends its SARIF up to the
controller over the agent's own API, so nothing is mounted for it.

A scanner you run on the host yourself still works for this release
(`SCANNER_REPORTS_PATH`, deprecated in 0.9.0): only its **output** is
mounted, read-only:

```
/mnt/user/appdata/scanners/reports:/reports:ro
```

That boundary is the point. The scanner binaries stay outside, so nothing in
this container can run a scan, change the rules, or edit what was reported. It
reads findings; it does not produce them. If a report looks stale, re-run the
scanner on the host; there is deliberately no way to do it from in here.

```bash
bb findings              # this project's findings
bb findings --all        # every project the report covers
bb findings x.sarif      # one file rather than all of /reports
bb findings --level error --rule DL3008 --find "quote"   # narrow it
bb findings sample       # a fake report, for a box with no scanner
bb findings sample --remove
```

The scanner is the host's and a development stack has none, so the Analysis
page, the notebook's Analysis view and the findings log have nothing to show
in a dev instance. `bb findings sample` writes one obviously-fake report,
tool `builderbot-sample`, with a finding in each of the first few projects on
the share and one on a path that places nowhere, so every shape those surfaces
draw has something to draw. It refuses to sit beside a real report, and it
refuses a read-only `/reports`, which is what a box with a real scanner has.
Run it inside the instance you want it in: it is not relayed to the
controller, because planting findings in somebody else's report directory is
not a thing a session should do.

A session reads its own project's findings and no others: not through the
Analysis page, not in the poll's counts, and `bb findings --all` is refused for
one, since the report covers the whole share and the flag means every project
in it.

A scanner pointed at a directory of repos writes one report covering all of
them, so `bb findings` filters to the project you run it from and says how many
it held back. Reports must be **SARIF**: several scanners default to their own
JSON and need asking (`--format sarif` for Trivy, `--sarif` for Semgrep);
anything that is not SARIF is skipped silently, which looks identical to a
scanner that found nothing.

For the same reason, a project missing from a report has not necessarily
passed: SARIF carries findings, not coverage. If you need to know a tree was
actually walked, keep the scanner's own stdout: `semgrep` and `trivy` both
print file counts that the report itself does not preserve.

Raw SARIF is mostly metadata: a few hundred KB of it fills a session's context
before it reaches the code the findings are about. `bb findings` groups by
severity and rule, prints each message once with the locations under it, and
rewrites the scanner's paths to be repo-relative so they can be opened
directly. Run it from the project directory; the current directory name is what
gets stripped from the recorded paths (override with `FINDINGS_PROJECT`).
The three filters are the Analysis page's bar in flag form: `--level` takes
error, warning or note (note and info are one level everywhere here), `--rule`
matches a rule id exactly, `--find` searches rules, paths and messages, so a
question answered in the browser is askable from a session in one line.

**Review the diffs.** Findings need judgment about intent: whether a `|safe`
is deliberate, whether a SHA1 is for dedup rather than security. Asking a session
to fix everything and re-scan unattended optimizes for a clean report, which is
not the same as better code, and suppressing a finding satisfies that goal too.

**The Analysis page**, under Projects on the rail, is the rendered findings
report: the SARIF your scanner drops in `/reports`, grouped by project and
rule, with severity counts and CVEs linked to NVD, under a project selector
and a filter bar (level, free text). Project groups start collapsed: the
severity pills on each are the overview, and what you open stays open across
reloads. If the scanner re-runs while the report is open, the view reloads
itself: the page watches the report files' mtime, so you never triage stale
findings. It leaves out projects with repo errors; those get fixed on the
Projects page first, and an archived one is not in that category, and the
report says how many findings that held back rather than quietly shrinking.
A project page's own Analysis view is the same report already narrowed to
that project ([notebook.md](notebook.md#analysis)). With nothing readable in
`/reports`, pressing it opens nothing and a notice says which of the three
reasons it is (no mount, nothing in it, or nothing in it that parses).

## What lands in dist/

**Dev builds do not pile up.** A build named with `bb version --file` carries
its dev version (`0.1.0-dev.17-9e09ad3`). Of each product (the name before
the version: `Shebang-DevBoard-`, `Shebang-Voice-`) `dist/` keeps every file
of its newest few builds, whatever follows the version (the project's
settings say how many, Dev builds kept: 3 unless changed, and 0 keeps
everything), and a build that has been signed keeps its signed copy alone,
since the unsigned file was only the signing's input. The rest go every few
minutes, when a node's build lands, and when the Artifacts view draws, not
only on the last. A release (no `-dev.N`) and an artifact somebody
**pinned** (the pin on its row, kept by the controller with who pinned it)
are never removed by count, and a pinned build is not one of those kept
beside it. A build named with no version cannot be judged, so its row says
so and offers Remove.

## Android signing keys

A project keeps up to two keys per named key, set by an administrator in the
**Signing** view of its page, under Ship:

- **Play upload key**, for Google Play with Play App Signing. Google holds the
  key the app is really signed with; this one only proves an upload is yours,
  and Play Console resets it when it is lost or leaks.
- **Sideload signing key**, for a build handed out directly or through another
  store. It is the app's identity for good: lose it and no update can reach an
  existing install, leak it and anybody can ship one that installs over yours.
  The row says so in red until it has been downloaded once with **Download
  backup**, a copy to keep offline. A backup goes to an administrator who has
  the project on their own list, not to every administrator who can see it.
  The project's owner puts a **backup password** on its keys before the
  first one: until there is one, no key is uploaded, generated or proposed,
  and a key from before the rule goes on signing. Every download then asks
  for it, BuilderBot's owner's included. Handing the project to another
  owner leaves it as it is, and the new owner changes it only with it; one
  nobody passed on leaves the keys' backups out of the dashboard's reach,
  which for a sideload key means a new key and a new app. It is kept as a hash,
  changed or removed only with the current one, carried in a request's body
  and never a URL, and five wrong in a row hold the downloads for fifteen
  minutes. It closes the dashboard's door, not the disk's: somebody with a
  shell on the controller can read `/config/signing/` either way.

The keystore (`.jks` or `.p12`) and its passwords are kept by the controller
under `/config/signing/PROJECT/`, owner-only, beside the git tokens and like
them outside every session's view. A key is checked before it is kept: the
`keytool` of the project's node (its jdk toolchain) has to open it with the
password given, find the alias (or the only key in it) and see a private key,
and its certificate's SHA-256 fingerprint is what the view shows.

**The controller runs no signing tool.** Everything that needs a jdk or the
build-tools is a job on the project's node: checking an upload, Generate, a
backup wrapped under the backup password, a rotation's proof and a release's
APK. The job is handed what it needs over the agent's own channel for that
job alone, works in a 0700 directory of the enrolled account that is removed
whatever happens, and hands back only the result (the alias, type and
fingerprint, the new or wrapped keystore, the proof, the signed APK); its
spec names the work and never holds a key. The node the project's settings
choose therefore needs the **jdk** and **Android SDK Build-Tools** (with
android-tools, which installs them) from its Library. When it cannot do the
work, because there is no node, it is offline or its agent is behind, or a
toolchain is missing, the Signing view and the answer say which node and
what, for instance "alpha's node bb-sandbox has no jdk: install it from its
Library". A session never
receives the key or a password, and is refused even the list of which keys
exist: it signs with `bb sign`, which runs on the project's node as a job the
session cannot look inside. Renaming the project leaves its keys where they are, with it.

**Import a backup** brings a key back from what Download backup gave, into
the same project or another: a generated key's backup is a zip of the
keystore and `password.txt`, which carries its password and alias, so nothing
is retyped and the key keeps its name; an uploaded key's backup is the
keystore alone, and asks for its password. The slot is read off the backup's
name unless one is picked. The zip has to hold exactly those two files, the
keystore has to open and match the fingerprint `password.txt` names, and a
slot already holding a different key refuses it rather than replace it.

**A signing is a job on the project's node.** It fetches the build from
`dist/` as a job input and the key over the agent's own channel, which hands
it only to that running job's node, once, and audits it; the job's spec names
which key and never holds it. Both land in a 0700 directory of the enrolled
account, never the session account: `zipalign`, `apksigner sign` and
`apksigner verify` for an `.apk`, `jarsigner` and its `-verify` for an `.aab`,
the passwords in the tools' environment only. The signed build has to carry
the kept key's certificate, arrives in `dist/` as `NAME-signed.apk` (or
`.aab`), and the directory is removed whatever happened. A node whose jobs
and sessions run as one account is refused, since a session there could read
the key while it is used.

Picking a keystore, typing its password and marking one for removal are staged
like everything else in the settings: nothing is sent until Save.

**A release's APK is signed on the project's node, never in CI.** A workflow
builds the release APK unsigned (no `signingConfig` for the release build
type) and uploads it as a workflow artifact named `bb-release-apk-TAG`, kept a
few days. The controller that made the release (Release on the version row)
looks for that artifact every few minutes for twelve hours, and once an hour
otherwise; it fetches it with the project's GitHub token and hands each APK
in it to a job on the project's node, which reads its package, is handed the
sideload key that package maps to, and signs it with its own tools (the same
steps a sign job takes: `zipalign`, `apksigner` with the proof of a rotation,
`verify`, the kept certificate checked). The controller attaches what comes
back to the release under its name less `-unsigned`, with its `.sha256` file
and a line in the notes naming the key and its certificate's SHA-256
fingerprint. So no keystore, alias or password is ever a GitHub secret, and
the key reaches only that job on that node. The Signing view's **Releases** section names which key signs each
app's releases and how the newest went, and **Look for unsigned APKs now**
signs a failed one again. What would stop a release's signing (no sideload
key, an app mapped to none of several, the project's node offline, behind, or
without the jdk or the build-tools, a project not on GitHub) is a bell row before the release, and a signing that
failed after one is a red bell row until it is signed or put away. Release's
confirm says it too, and a session's `bb version release` is refused before
the tag with the reason unless it adds `--without-apk`. A session reads the
same with `bb sign status [TAG]` and asks for the look again with `bb sign
release --why "..."`, under **Agents may: Sign a build**. GitHub only: a Gitea
or GitLab workflow's artifacts are not fetched.

**Several apps, several keys.** A project keeps as many named keys as it needs,
each with both slots; the first is **default**, which is where keys from
before there were names went. **Generate** makes one on the project's node
with its `keytool` (RSA 4096, ten thousand days) behind a random password
kept with it, so nobody types or sees one, and its backup is a zip of the
keystore and that password. Under **Apps** an app's package is mapped to a
key; a sign job reads the package from the build (`aapt2` for an `.apk`, the
bundle's manifest for an `.aab`) and the controller hands it the mapped key, or
the default for a package with no line, unless the signing named one
(`bb sign FILE --key NAME`). Sharing one key between apps is allowed, and
sensible for apps meant to trust each other; a key of their own keeps one
app's lost key from being every app's. A session reads which keys exist and
proposes a new one or a mapping (`bb sign keys`, `bb sign key new NAME --for
sideload`, `bb sign map PACKAGE KEY`) under **Agents may: Manage signing
keys**, ask by default, which puts it in front of the project's owner.

**Moving an app to another sideload key.** **Rotate to it** on a key's
sideload row (or `bb sign rotate OLD NEW`, under the same dial) makes a proof
of rotation on the project's node with its `apksigner`, signed by both
keys, and keeps it with the new one. From then on every build that would have
used the old key is signed with both and the proof, with the new key from
Android 9 on (`--rotation-min-sdk-version 28`): Android 9 and newer accept
updates signed by the new key, and older devices keep checking the old one.
The apps mapped to the old key move to the new. The old key is **retired**:
never signs alone again, and cannot be removed, since the proof and every
device before Android 9 still need it. It cannot be done without the old key,
which is the other reason a sideload key is backed up. A bundle carries no
proof, so an `.aab` is signed with the new key alone; Play upgrades its own
app signing key (which reaches Android 13 and newer), and F-Droid's own key
cannot be rotated into, since F-Droid holds it. The Artifacts row of a build
that carries a rotation says so, and which key older devices still see.

**Signing a build.** A person signs from the **Artifacts** view: an `.apk` or
`.aab` row offers **Sign** for each key the project has. A session runs
`bb sign FILE [--for play|sideload] [--why "..."]` (Play for an `.aab` and
sideload for an `.apk` unless it says), under the project's dial **Agents
may: Sign a build**: auto signs, **ask** (the default) puts the build, the
key and the reason in front of the project's owner in their bell, and deny
refuses naming the setting. Either way it is the same job, and the session
follows it to the signed file's name. A signing that could not happen (no
such key, no such build, no node) is refused before anybody is asked.

**A release from a session.** `bb version release --why "..."` tags the
commit and publishes the release the way **Release** on the Artifacts view
does, on the controller and with the project's own credentials, which the
session never holds (R138). It is its own dial, **Agents may: Tag and
publish a release**, named apart from signing, which makes a build rather
than a release: auto releases at once, **ask** (the default) puts the tag
and the commit it would mark in front of the project's owner in their bell
and the app, and deny refuses naming the setting. A release that could not
happen (no version, a tag already there, uncommitted changes) is refused
before anybody is asked. From a branch other than the one builds ship
from, a session's release is the dev build's (`--dev`, a pre-release on
the dev channel) unless `--stable` says otherwise, and its first line
names the channel it lands on (R190).

**Rehearsing one.** `bb version rehearse` runs every build a release's tag
runs (the controller bundle packed, the OS image built and booted, the
Android app, the companion and the VS Code extension built) on the pushed
branch, publishing nothing, its summary listing the files the release would
carry; a release is then tagged once. GitHub starts it only once the
repository's default branch carries `.github/workflows/release-rehearsal.yml`.

**The files a release carries.** `.release-files` at the tree's root lists
them, one a line with `@VER@` for the version. The controller checks each
release it made against the list at its own tag once CI has had three
hours, and a release short of a file is a red row on the bell naming the
file and why (an unsigned APK, a file CI did not attach).

**The forge's release.** Once the tag is pushed, Release makes the forge's
own release beside it: titled with the version, the changelog's section for
it as the notes, and the released commit's builds attached (the signed ones
when there are any). On GitHub with the project's token or the shared PAT;
on Gitea, Forgejo and Codeberg with the token the project's link stored,
asked at the address that token was stored for, plain http on a port for a
Gitea on a LAN; on GitLab the same, with each build put in the project's
generic package registry under the version and linked from the release,
since a GitLab release holds links rather than files (R124). A forge that
says no leaves the tag as the release and the Artifacts row says why, and a
host with no release API (Bitbucket, plain git) says that instead.

**Editing a published release.** `bb version release --edit --why "..."`
changes the release of the version this tree is on (or `--tag TAG`): the
notes replaced whole with `--notes FILE`, and files attached with
`--attach FILE`, each a build in dist/ or a file the project's history
has, so what a page shows can be found again; one of the same name is
replaced rather than doubled. `(asset:NAME)` in the notes becomes the
address of the file of that name on the release, which is how a
screenshot attached by the same edit is shown. It is under the release's
own dial, and on ask every edit is its own ask: the project's owner reads
the notes whole and each file by its name and size before Allow. Nothing
here moves a tag (R139).

A file comes off a release with `bb version release --remove NAME --why
"..."` (once for each name), and only that way: its own ask under the same
dial, never part of an edit, since it is the one change that takes
something away from the people downloading. The names are checked against
the forge's own list of the release's files before anybody is asked, so
the ask names files that are there, with their sizes, and the bell shows it
in the destructive color. On GitLab the release's link to the file goes;
the file itself stays in the package registry.

A release made by mistake is taken back with `bb version release --withdraw
TAG --why "..."`: the forge's release and its tag deleted together, and the
tag taken out of the controller's copy, so the number can be cut again from
a fixed commit (R190). It is always the project owner's answer on the bell,
whatever the dial (deny refuses), since nothing undoes it; a tag whose
release is already gone is withdrawn alone.

**What is signed says so.** The node reports what `apksigner verify` (or
`jarsigner -verify` for a bundle) found: the certificate's SHA-256 and the
signature schemes that verified. The controller keeps that in the file's
provenance, and its Artifacts row wears a *signed* tag, says which key and
from which build, and gives the whole fingerprint with **Copy for F-Droid**,
which copies it the way F-Droid's `AllowedAPKSigningKeys` takes it (lowercase,
no colons). A signed file is not offered Sign again.
