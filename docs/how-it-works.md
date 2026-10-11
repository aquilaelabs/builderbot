# How BuilderBot works

The design decisions behind what is described here, with their dates and reasons, are in [decisions.md](decisions.md); the setup steps are in [install.md](install.md).

## What's in the image

| | |
|---|---|
| **Claude Code** | Not in the image: a session runs on a node, and the node installs it |
| **Node** | 22.x (NodeSource) + npm, corepack (yarn/pnpm shims) |
| **Python** | 3.12, `uv`, `pipx`, venv |
| **Playwright** | CLI + the system deps; the browsers themselves install to the [toolchain store](#the-toolchain-store-lives-outside-the-image) and appear at `/opt/pw-browsers` |
| **Android, Java, Flutter, .NET…** | Not in the image. A node's, from its toolchain store: the JDK, the SDK and the emulator are recipes on the Toolchains tab, installed with the node picked, and the system images the emulator boots are on the Emulator tab |
| **Git** | git, git-lfs, `gh` CLI |
| **Docker** | CLI + compose/buildx plugins (needs the opt-in socket mount) |
| **Search** | ripgrep, fd, fzf, jq, yq |
| **Build** | build-essential, cmake, pkg-config |
| **Lint** | shellcheck, hadolint, actionlint, ruff, node --check: `bb lint` runs the right ones over a repo |
| **Media** | ffmpeg, imagemagick |
| **Runner** | latest `actions/runner`, ephemeral by default |
| **Versioning** | `mise` for per-project tool pinning (gradle, go, rust, on demand) |

Slimmer builds: `--build-arg INSTALL_PLAYWRIGHT=false`, `INSTALL_ANDROID=false`.
The heavyweight toolchains (Flutter, .NET, Swift, extra Android packages)
are never in the image at all; `bb toolchains install` puts them on a share that an
update cannot touch. See [the toolchain store lives outside the image](#the-toolchain-store-lives-outside-the-image).

## Security model, in short

- **Repo mounts** expose only those trees; writes land as `nobody:users`.
- **No Docker socket by default**, with it absent, reaching the host
  requires a kernel exploit.
- **Secrets shielding**: PAT scrubbed from session env + root-only sudo
  helper for runner tokens, whose store is a named volume of the daemon's
  rather than a directory under `/config`, so it stays root-owned even
  when appdata is a squashed NFS share; SSH keys usable via root-owned
  agent but not readable; logs redacted (patterns + literal values).
- **No passwords, no general sudo**: `root` and `builder` are locked
  accounts; brute-forcing has no target. Builder may sudo exactly one
  command (`mint-runner-token`), which only emits 1-hour tokens.
- **Your root door** is host-side: `docker exec -it -u 0 BuilderBot bash`.
- Don't attach the runner to public repos; treat container-produced commits
  and packages with normal review.

Full discussion: [unraid.md](unraid.md#notes-and-gotchas).

## Startup hooks

The entrypoint runs as root: stash/scrub secrets, remap `builder` to
`PUID:PGID`, seed the home volume (never overwriting), start the ssh-agent,
then executes hooks and drops privileges:

| Hook | Does |
|---|---|
| `30-git-and-auth.sh` | git identity, GitHub host keys, `gh` auth (unshielded mode only) |
| `35-publishing.sh` | npm publish auth, ghcr docker login (socket + PAT present) |
| `40-projects.sh` | project report, optional per-project bootstrap |

Your own hooks go in `config/startup.d/` on the share: `*.root.sh` runs as
root, `*.disabled.sh` is skipped, filename order. All hooks are idempotent:
they check state before installing.

The dashboard starts early in the boot, before any project's own `setup.sh`
and the SDK/Playwright hooks, so the web UI is reachable in seconds rather
than after the whole start-up. For a few of those seconds it knows less than
it will: the toolchain store is listed as a project until the hook that marks
it runs, and git columns are blank. All of that corrects itself on the next
poll. `bb logs` now times each
hook and prints how far into the boot it started, so "what is the wait" is a
question the log answers.

## Behind the `bb` helper

`bb tests keep` holds the dashboard's test fixture up after the harness's
set-up, so `bb dashboard test SUITE` and `bb tests probe FILE.mjs` attach
to it: half the time of a fresh run, and the world a suite just left is
still there for a probe to look at. A probe is a scratch Playwright script
(importing `./lib.mjs`) that asks the page a question, which is how a
session finds out what a tab really fetches or what a variable holds. The
kept world is not put back between runs, and a change to the dashboard's
python needs a fresh keep; `bb tests keep stop` ends it. Both are R75's
second step.

`bb dashboard trace [SECONDS]` prints what the dashboard was asked over
that window, by endpoint and by who asked, from a ring the server keeps in
memory: the command that shows a poll that should not be there or a tab
that asks twice, which nothing counted before. The design suite holds the
matching invariant: an idle page issues only its two polls, and opening a
tab asks each endpoint once. R75's fourth step; the fifth puts the
running build into every session's briefing, so no session argues from a
build it assumed.

`bb tests coverage [SUITE...]` is a covered run: the copy the harness runs
from gets a counter at the head of every function the map knows, the
server counts the functions it enters, and the counts are merged into
`.bb-map/coverage.json`. `bb map covered NAME` then names the suites that
ran a function, `bb map uncovered [FILE]` what no suite reaches, and `bb
map unused` what nothing calls or passes by name. R76: a refactor knows
its regression net before it starts.

`bb tests preflight` is what a session runs before a push: the files the
branch changed, the python unit tier first (under a second), the suites
that reach them, and the lint and voice checks, run together, with the
design check when a file carrying style changed; `--dry` prints the plan.
The suites are shared across the node's workers by the seconds each took
there last, longest first. With a covered run on
record the suites are the ones that reached the functions the changed
lines fall in, and the ones naming an id or class those lines draw
(`bb map affected`), which is why a change to one handler is a
five-minute gate and not the whole suite; a changed function no covered
run has seen falls back to what the code map says of the file (a page
function a suite calls bare, an id or class it names, an API path a
changed python module answers through the server's route table, a file
named outright), and in `server.py` to every suite. A whole run refreshes
the covered run. R75's third step, so the suites are never picked by hand.
`tools/no-net-growth.sh` is a measurement beside it, not a gate: the four
largest files against the ceilings in `tools/ratchet.txt`, which a change
that shrinks one lowers with `--tighten` (roadmap R77).

`bb map` is the code map a session asks instead of grepping (roadmap R75):
one index over the tree it is in, python, the dashboard's scripts (the
inline script in `index.html` included), `bb`'s own shell and the test
suites. It knows where every function is defined, every call by name with
the function it is made from, every element id and class a function's
markup draws, and which suite names each of those, so `who-calls
loadDocker` or `draws .dmtab` is one call rather than a hunt. Built with
nothing installed (python's own parser, a small scanner for the scripts),
into `.bb-map/` beside the tree, rebuilt by itself when a source is newer.
Every build keeps `.bb-map/` out of git through the repository's own
exclude file, never the project's `.gitignore`, so a project's commits
never carry the index. It is rough on purpose, braces not scope, and says
so where it guesses.

`bb capture shot` is the container's camera: one URL with an optional output file
keeps the simple shape, several URLs share one browser and land in a
directory named from their paths (`/` → `index.png`). For README-quality
captures it takes `--full` (whole page, not just the viewport), `--scale 2`
(2x pixels, crisp in GitHub's column), `--wait MS` (pages whose async
fetches settle after networkidle), and `--resize W` (imagemagick downscale,
in place, so full-size originals never land in a repo). `--auth user:pass`
falls back to `BB_TOKEN` or a `DASHBOARD_AUTH` you pass for the command. The intended split for a project's docs
screenshots: the project keeps a script that boots its app into a
photogenic state (staged data, ready-wait) and ends with one `bb capture shot`
line; the Playwright plumbing lives here, once.

`bb tool graphics favicon LOGO.svg [DIR]` is the same idea for a web app's icon: the
project supplies its mark as one SVG, and out come `favicon.ico` holding
every small size in one file (the bare `/favicon.ico` request browsers make
cannot ask for a particular one), `apple-touch-icon.png` at 180 for iOS
(`--bg COLOR` flattens it: iOS composites transparency onto black), and
the SVG copied alongside for browsers that prefer vector. Chromium
rasterizes (the image's ImageMagick has no SVG delegate; a browser engine
renders exactly what a tab will show) and ImageMagick packs the `.ico`.
The dashboard's own tab icon is this command's output, from
`scripts/dashboard/static/favicon.svg`.

**Dev builds do not pile up.** A build named with `bb version --file` carries
its dev version (`0.1.0-dev.17-9e09ad3`). Of each product (the name before
the version: `Shebang-DevBoard-`, `Shebang-Voice-`) `dist/` keeps every file
of its newest few builds, whatever follows the version (the project's
settings say how many, Dev builds kept: 3 unless changed, and 0 keeps
everything), and a build that has been signed keeps its signed copy alone,
since the unsigned file was only the signing's input. The rest go every few
minutes, when a node's build lands, and when the Artifacts tab draws, not
only on the last. A release (no `-dev.N`) and an artifact somebody
**pinned** (the pin on its row, kept by the controller with who pinned it)
are never removed by count, and a pinned build is not one of those kept
beside it. A build named with no version cannot be judged, so its row says
so and offers Remove. One day of a session building a keyboard left seven
debug APKs, 133 MB, before the first of this; counting by name rather than
by build left Shebang's renamed first builds for good, and unsigned twins
were 350 MB of its 811 (6 Oct).

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
major stops working when GitHub retires the Node it runs on. Shebang-DevBoard
failed for weeks that way. The controller looks at every project with
workflows once a day, and at once when one is linked (`ciwatch.py`): the
tree's workflows for a hosted job on a moving `-latest` label and for each
action against its newest release, and on GitHub, with the token `bb ci-log`
uses, whether the newest run on the main branch passed and what GitHub wrote
on it (its warnings about a retired Node or a label about to move). What it
finds is kept under `ciwatch/` in the state, shown as the Git view's CI
section (with Look now), printed by `bb catchup`, and, while main is red,
a bell row. It reads and never changes anything; nothing in a repository
needs setting up, so every BuilderBot and every project gets it. R117.

**Sound effects a session can make.** `bb tool sound make PRESET [--seed N]`
is a port of sfxr's synthesizer (stdlib python, nothing to install): blip,
pickup, jump, laser, hit, powerup, explosion and bloop, each a family a seed
picks one from, so the same seed makes the same sound again. `bb tool sound
tone HZ [--ms N] [--to HZ]` is a plain beep or sweep. Each lands in
`dist/sound/` as OGG, made by the ffmpeg toolchain, with a waveform and a
spectrogram beside it, since a session cannot listen to what it made; with no
ffmpeg on the node it is a WAV and no pictures, and says so. It is a verb of
bb's rather than a toolchain of its own because there is nothing to fetch.
Speech is the **audio** toolchain's, which is a download (about 800 MB):
`bb tool sound say "TEXT"` is piper with one English voice, a WAV ready for
an app's microphone, and `bb tool sound hear FILE` is faster-whisper's
base.en on the CPU, the words with their times, for a session to check what
an app said. hear puts half a second of silence before the recording, since
speech starting on the first sample lost its first word without it. R107.

**Documents a session can read.** `bb tool docs read FILE...` prints a PDF,
a Word document, a slide deck or a spreadsheet as Markdown, through
markitdown; `bb tool docs pages FILE [--pages N-M] [--dpi N]` draws its pages
as PNGs in `dist/docs/NAME/` through PyMuPDF, the first twenty when no range
is given, for the layout, a chart or a scan that text alone loses. A file
that is not a PDF is made one first by LibreOffice, headless, which is also
`bb tool office convert FILE... --to pdf|docx|xlsx|pptx|odt` on its own.
Two toolchains carry them: **documents** (markitdown and PyMuPDF in a Python
of uv's own inside the toolchain's directory, so nothing depends on the
node's Python, and pandoc; about 650 MB) and **office** (LibreOffice's
AppImage unpacked; about 750 MB). The Python environment holds absolute
paths, so a store mounted at another path on another node needs the
toolchain installed from that node. The documents toolchain also puts a
`pdftoppm` and a `pdfinfo` on the node's PATH, drawn with PyMuPDF
(`scripts/lib/poppler.py`): they are what Claude Code's own PDF reader asks
for, and no node carries poppler, so without them a session could not read
a PDF it had fetched.

**Is the machine quiet enough to measure on?** A session times things (a
decoder's latency, a build, a suite) on a machine it shares, and its view
holds only its own processes: the load average it can read says the machine
is busy and never why. `bb node busy` asks the controller, which joins the
node agent's last heartbeat (CPU over the last 25 s, the load against its
cores, memory, the card's load and memory and how many compute on it, and
what runs there by kind: emulators, Gradle, other Java, compilers,
browsers, media, docker builds, Claude) with the jobs active on the node and
the Claude sessions working there, and answers quiet, busy, saturated or
unknown, with the reasons. Another project's work is counted and never
named. The load right now is read in the session as well, since a heartbeat
is up to 25 s old. `bb node wait-quiet` waits for two quiet readings ten
seconds apart and exits 1, saying how busy, when the time runs out. A test
run's log ends with the load it ran under, and `bb tests ingest` keeps it on
the run, so a busy run's seconds are not read as a quiet one's.

`bb` re-execs as `builder` automatically: `docker exec` lands as root, which
would break file ownership. A bare `docker exec -it BuilderBot bash` is still
root; use `bb shell` for the normal user.

## The toolchain store lives outside the image

The image carries no toolchain beyond node, python and the Playwright
module. Everything a build needs: the JDK, the Android SDK, the emulator,
Flutter, .NET: is a recipe installed into a **node's toolchain store**, from
the Toolchains tab with that node picked; the tab lists nodes and nothing else,
and with none enrolled it says so. The controller's own store: the SDK
share, mapped at `/sdk` (Unraid default `/mnt/user/sdk`): holds
only what its boot keeps for `bb capture shot`, the Playwright browsers; nothing is
installed on the controller from the dashboard. A node enrolled with the same
share is recognized as sharing it, and installs are arbitrated across both.

**One store, scoped by platform.** A machine's toolchains live under
`<store>/<os>-<arch>`: `linux-x86_64` for this container and the sandbox,
`darwin-arm64` for a Mac, so one share can serve every node whatever it
runs, and a Linux box's binaries never land on top of a Mac's. The Android
system images, the same bytes on every host and tens of gigabytes, live once
under `<store>/shared/android/system-images` with each platform's
`android/system-images` a link to them, and `bb toolchains root` names the scoped
directory.

```bash
bb toolchains                     # what is installed, where, and how much room is left
bb toolchains install flutter     # or: playwright · dotnet · swift · go · rust · zig · android:<pkg>
bb toolchains install android:ndk        # or cmake · emulator · platform-tools · platforms · build-tools
bb toolchains list                # every toolchain the catalog offers
bb toolchains plan swift          # what installing it would fetch and run, exactly
bb toolchains versions            # what is installed, asking nobody
bb toolchains check               # ...and whether anything newer exists
bb toolchains update flutter      # each the way its own tooling expects
bb toolchains remove flutter
bb toolchains env                 # the PATH lines; new shells get them automatically
```

The NDK, CMake, the SDK platform and build-tools are versioned rows: each
is a family of packages side by side, so the check asks whether the newest
the repository offers is on the store, and Update installs it beside the
older ones rather than in their place. The platform row's newest is the
newest level's base (`platforms;android-37.0`, what `compileSdk = 37`
names), not a quarterly minor or an extension level. A session cannot
write the store, so the Android Gradle plugin cannot fetch a missing
platform itself: a project wanting a level the store lacks names it, and
the operator ticks the row. Before these two rows, a platform arrived only
with an emulator image of its level, and platform 37 never arrived at all.

**The NVIDIA driver is the machine's, not the store's.** On a node whose
census names an NVIDIA card, the Toolchains tab shows the driver as a row of
its own above the store's. It behaves as the other rows do: a tick box, so
it goes into Install selected with whatever else is ticked (last, since it
ends at a restart), a bin to remove it, and **Check for updates** reads
apt's lists again on the node, so the row says when a newer version of the
installed branch is there to tick. It is not a recipe, though: the kernel
module is built for that machine's kernel and the libraries must match it,
so it is installed as root on that node alone, through `bb-sandbox
gpu-driver`, and it takes the card only when the machine restarts, since
nouveau holds it until then. The row's pulldown lists the branches apt
offers there, the one recommended for the card first, then newer ones and
the open-kernel variants; a beta appears in it when the distribution or a
source the machine has publishes one, since apt has no separate label for
it. The pulldown is live only while no driver is installed: one branch at a
time, so another version means removing this one first. The row reads where
the driver stands from the census (not installed, installed and waiting for
a restart, running the card, removed but still loaded). A guest machine's
driver is its owner's, so there the row says so and offers nothing. Nothing
else installs the driver: not enrolling a node, and not the emulator's GPU
display, which needs the driver and says so until it is there. The install
also writes a boot unit that makes the card's device nodes,
`/dev/nvidia-uvm` among them, as root: a session runs with
no-new-privileges, so CUDA's setuid helper cannot make them on a program's
first use. `bb toolchains` names where the driver stands too.

**The NVIDIA container toolkit is the row under it**, shown where the node
has the card and Docker: what lets a container there reserve the card. It
is the machine's as well, and it needs the driver, so ticked alone on a
machine with no driver it is refused by name, and ticked with the driver
the two are one job, the driver first; removed together, the toolkit comes
off first. Neither Ubuntu nor Debian carries it, so installing it adds
NVIDIA's own package source and its signing key to the machine
(`bb-sandbox gpu-container install`), which the press asks about first,
and tells Docker about the runtime; Docker reloads its configuration for
it, so running containers keep running (a restart, which leaves a container
with no restart policy down, is the fallback only where a reload did not
take). Removing it takes the package, the
runtime's entry and the package source away again. The row reads installed,
newer on offer (Check for updates reads NVIDIA's list with apt's), and
whether Docker lists the runtime, which is the thing a container needs. A
compose file asks for the card the way compose always has
(`deploy.resources.reservations.devices` with `driver: nvidia`, or
`runtime: nvidia`, or `gpus:`), and one that asks is checked before it
starts: where the node has no card, no running driver or no toolkit, or the
node's switch or the project's *The node's GPU* setting says the card is
not for it, the Docker tab's row says the compose cannot start as written
and why, and an Up or a Rebuild asked anyway (a session's `bb devapp
rebuild` included) is refused in the same words, rather than failing after
the build with Docker's "could not select device driver".

**What the card is used for** is three settings and a queue, none of which
moves work onto it: a program uses a GPU only if it was written to, through
CUDA or the video encoder. A node with a card has a **GPU** section on the
Nodes tab with two switches and one Apply: *render the Android emulator on
the card*, which starts or stops the headless X server the emulator needs,
and *let sessions and jobs compute on it*, on by default. A project has its
own setting in its dialog, *The node's GPU*, for running as if the machine
had none. Where either says no, a session started from then on has
`CUDA_VISIBLE_DEVICES` empty and the unified-memory device CUDA cannot start
without covered in its view, so a program finds no card and takes its CPU
path; the card's other device files stay, because the emulator's rendering
opens those from inside the session and is its own switch. `bb gpu` says
what the card is, how much of its memory is free, who is computing on it and
whether this session may, and `bb status` carries the same in a line. The
card's memory is one pool for every session on the node, so a heavy job is
started as `bb gpu run [--mem MB] -- CMD`, which takes a lease (one at a
time per node), waits for its turn and for that much free memory, and lets
go when the command ends. The briefing tells a session all of this only
where its project's node reports a card.

The Android system images live on the same store without being toolchains
(one exists at every API level at once), so they have verbs of their own:

```bash
bb emu images                     # the system images on this machine's store, with sizes
bb emu images --available         # ...and every one that could be added
bb emu flavors                    # google_apis · +playstore · tv · wear, and which to pick
bb emu image add tv               # the newest of a flavor, or a full id:
bb emu image add "system-images;android-35;google_apis;x86_64"
bb emu image remove "system-images;android-35;google_apis;x86_64"
```

**The recipes are a file, not code.**
[`config/toolchains.json`](../config/toolchains.json) holds everything the container
needs in order to offer, fetch and install a toolchain: the URL, the branch, the
installer's arguments, the environment it wants, how many directory levels to
strip out of the archive, what to run afterwards to prove it worked. Both the
dashboard and `bb toolchains` read it, so adding a toolchain is one edit: as long as
it fits one of five shapes:

| kind | what it does |
|---|---|
| `tarball` | resolve a version, fetch the archive, unpack it |
| `script` | fetch a vendor installer and run it with the given arguments |
| `git` | shallow-clone a branch, for a tool that then updates itself |
| `command` | run something already in the image, pointed at the directory |
| `sdkmanager` | an Android package, or an image flavor by kind |

The shapes stay in `bb` because they are genuinely different jobs, and a
table that could express all five would be a programming language. **`bb toolchains
plan <toolchain>`** prints what a recipe resolves to: version, URL, the exact
commands, without downloading anything, which is how a catalog edit gets
checked before it is trusted.

**No size is written down anywhere.** A size typed into a file is wrong the
next time upstream ships. A row shows the footprint once the toolchain is
installed (measured, and remembered after it is removed) and before that
what an install would *download*, which is a different number and is labeled
as one: Swift arrives as a gigabyte and unpacks to three.

Upstream is asked for that download figure rather than guessed at, three ways,
all of them catalog entries. Where the catalog's URL is the payload, its
`Content-Length` is the answer. Where it is not, a `download` block names a
dry run to execute and a pattern to match URLs out of; that is how
Playwright's five bundles and the .NET archive get counted. And the Android
packages come from `sdkmanager`'s own repository index, looked up by the exact
package id an install would resolve to: the index's newest Play Store image is
an `android-CANARY` build nobody installs, and the emulator appears twice,
once stable and once on the dev channel.

None of this is a scrape. Every document these resolvers read is one the
vendor's own installer reads: `sdkmanager`'s package index, `rustup`'s
channel manifest, Zig's release index, Go's version file, and the two GitHub
lookups deliberately use the `releases/latest` redirect rather than the API,
which is what rate-limits anonymous callers by IP. Requests carry a
`builderbot-sdk` User-Agent, there are no retries and no parallel fetching,
and a check runs at most a few times a day. What it costs is about 1.8MB,
cached for fifteen minutes in `/tmp` so that the thirteen separate processes
of one check share the four hundred kilobytes of package index that three of
them need.

Rust answers a fourth way: its channel manifest names an archive per
component, and the three a minimal profile installs add up to what `rustup` is
about to fetch. Only Flutter cannot be asked at all: a git clone has no
content length, so it carries the one approximation in the catalog, marked
with a `~` everywhere it appears and replaced by a measurement the moment the
toolchain has been installed here once.

**Nothing installs, updates or removes itself, and no session can do it for
you.** `bb toolchains install|update|remove` refuses to run when `CLAUDECODE` is in
the environment; that variable is in everything a Claude session runs, and
the dashboard drops it at startup precisely so that this page is never
mistaken for one, and tells the session to ask instead. It is a guardrail
rather than a boundary (a session has a shell, and could call `sdkmanager`
directly), and it says how the human at the keyboard overrides it:
`env -u CLAUDECODE bb toolchains install …`.

**A removal sticks.** The Playwright browsers are fetched on the first boot
of a fresh share, because a container that comes up "ready" with `bb capture shot`
broken is worse than a slow first start. A share somebody has just cleared looks
identical to a fresh one from a startup hook, so `bb toolchains remove` leaves a
marker under `.removed/` on the share and the hooks respect it; installing
the toolchain again clears it. Without that, an uninstall lasted until the next
restart, which is not an uninstall.

In the tab, one button does it: **Install selected** installs what is not
there and updates what is, so there is no second verb to choose between. A
toolchain that is installed and current has a **dead checkbox**; there is
nothing to do to it, and gets its tick back the moment a check finds an
update, with the version it would move to in amber beside the installed one.
Uninstalling is a **bin icon on the row itself**, with a confirmation,
because it is about one toolchain and a bulk Remove button beside a bulk
Install was one mis-click from being expensive.

**A job can be stopped.** **Abort** empties the queue and interrupts the
toolchain being worked on: the whole process group, so the download it is
waiting on goes too, and `bb` removes the half-installed directory on its way
out, the same cleanup a failed install gets. Everything already installed
stays; the abort is for the rest of the queue, not for undoing what worked.

**Two different questions, two different costs.** What version is installed
is local knowledge (a directory name, or `flutter --version`), but asking
every toolchain to say its own name is a few seconds, so the answer is kept on
the state volume rather than only in memory. That is what makes the tab open
at once after a container restart instead of sitting on "loading…" while the
same unchanged answer is worked out again. It is keyed by what it is an answer
*about*: the set of installed paths, so installing or removing something drops
it, and a digest of `config/toolchains.json`, so editing a recipe does too.

**The size is an estimate until it is a measurement.** Every row carries one:
the catalog's `~3 GB` before installation, which is what the download costs,
and the real `du` figure afterwards, which is not the same number and grows
(a pub cache, a .NET workload, an NDK that unpacks bigger than it ships).
Hover a size to see which one you are reading. Measuring walks the tree, so
it happens on a worker rather than in the request: the first draw after an
install carries the estimate and the real number arrives a moment later.

Android needs no PATH help on the machine that has it: a node's agent points
`ANDROID_HOME` at its store's `android/` directory for every job and session,
so Gradle and `sdkmanager` install and find things in one place. (The
controller has no Android SDK at all since it stopped building; see
[CI runs on a node](nodes.md#18-the-controller-runs-nothing).) The other toolchains land in their
own directory under the
share and are put on `PATH` by a generated `env.sh` that every shell sources;
`bb toolchains remove` is `rm -rf` of one directory, because nothing was installed
anywhere else.

| Toolchain | Size | What it gets you |
|---|---|---|
| `go` | ~250MB | Windows, macOS, Linux and ARM binaries from here: `GOOS=windows go build`, no target to install |
| `rust` | ~700MB | rustup, cargo and the stable toolchain in one directory |
| `zig` | ~300MB | A C/C++ cross-compiler: `zig cc -target x86_64-windows-gnu` makes this box a Windows toolchain |
| Android packages | 800MB emulator, 3GB NDK | Platforms, build-tools, emulator, NDK, CMake |
| Android system images | 1–2GB each | One per API level per flavor; see [below](#the-toolchain-store-lives-outside-the-image) |
| `playwright` | ~1.3GB | Chromium, Firefox and WebKit: fetched on a fresh share, since `bb capture shot` and the dashboard's tests need them; removing it stays removed |
| `flutter` | ~1.3GB | Flutter + the bundled Dart SDK; builds Android APKs here |
| `dotnet` | ~4GB | .NET SDK plus the `maui-android` workload |
| `swift` | ~3GB | The Swift toolchain, for shared logic and server-side code |
| `tizen` | manual | Samsung TVs, signage and appliances. No headless installer exists, so `bb toolchains install tizen` prints the steps and is not in the dashboard's list; everything there installs |

**From the dashboard.** The sidebar's **Tools** card holds **Toolchains…**,
which opens as a **tab** the way the findings report does: a list of
everything above with a checkbox each, the size it will take, and, once
installed, the path it actually landed on. Tick several and install or remove
them in one go. If one fails, its row says why: the sentence, not the
several hundred lines of progress frames that came with it.

System images sit below in a section of their own, because they are not
toolchains: a picker for the API level and flavor with the download size on
each option, and the ones already on disk listed under it with what they take
and a bin each. Each one also says **which AVDs are built on it**, which is
what "can this go?" actually means: an AVD names one image exactly and will
not boot without it, and two flavors at the same API level are not
interchangeable. An image no AVD names says so, and is the one that is spare. A tab rather than a dialog because an install runs for
minutes; it can sit on the strip, be pinned to a pane, or be minimized while
you work, and the work itself is a background job on the container, so the
list keeps reporting progress instead of hanging on a request that would take
four minutes to answer. The page only ever posts names the server offered it,
the same rule the command buttons follow.

**Building for Windows, from here.** Three of those cross-compile without a
Windows machine anywhere: Go does it with `GOOS=windows GOARCH=amd64 go
build`, Zig with `zig cc -target x86_64-windows-gnu` (a C and C++
cross-compiler that happens to ship with a language), and .NET with `dotnet
publish -r win-x64 --self-contained`. All three were verified on this box:
`file` says *PE32+ executable, for MS Windows*. Rust needs one more piece: a
linker, either `gcc-mingw-w64` on the node or `cargo-zigbuild` on top
of Zig. What none of them give you is a Windows *GUI* toolchain: WPF, WinUI
and MSIX packaging need Windows itself.

**Tizen is Samsung's, and where it runs decides whether you care.** TVs,
signage and appliances still run it and Samsung still ships it; that is the
reason to install it. Watches are not: Galaxy Watch moved to Wear OS with the
Watch 4 in 2021, so a watch app is `bb emu image add wear`. Phones ended
in 2017. There is no headless installer, so it is a CLI pointer rather than a
row in the dashboard's list, where everything installs.

**Android, and which vendor you are targeting.** One SDK covers all of them:
Samsung, Pixel, Oppo, OnePlus, Xiaomi. There is no per-vendor SDK to install
and no vendor emulator image to download: Samsung's Galaxy skins are
cosmetic, and the vendor libraries (Samsung IAP or Health, Oppo/Xiaomi push)
are Gradle dependencies a project declares, not toolchains a container holds.
What genuinely differs is the *system image* you emulate against, which is
why those are not toolchains. A toolchain is one thing at one version; a system
image exists at **every API level at once**, so the question is which level
and which flavor, never whether. The four flavors, and why you would pick one:

| Flavor | What it is |
|---|---|
| **Google APIs** | Play *services* (Maps, sign-in, push), but no Play Store app. Rootable: `adb root` works. The default, and what `bb emu create` fetches |
| **Google APIs + Play Store** | The same plus the Play Store app itself, for anything that signs in to Play, checks a license or takes an in-app payment. A Play-certified build, so **not** rootable |
| **Android TV** | Leanback layout, remote-control navigation |
| **Wear OS** | What modern Galaxy and Pixel watches run |

The first two are separate downloads from Google, not one image with a switch,
which is why the Play Store one has to be fetched on its own even when a
plain image for the same API level is already here. The trade is deliberate on
Google's side: an image that ships the Play Store is certified, and a
certified build does not give you root.

Which means the two at one API level are **not** redundant with each other,
even though they cost 2GB each and look almost identical. Take the Play Store
one if something has to talk to Play; take the plain one if you want
`adb root`, a writable system, or the level your existing AVDs were made
against. Rarely both, and the image list says which AVDs are built on each,
so the one that is actually spare is visible rather than guessed at.

The Emulator tab offers a level and a flavor and adds it to the picked node;
`bb emu images --available` is the same list on the command line, sizes and all. Real Samsung
or Oppo hardware is an `adb connect` away over the network, and Samsung's
Remote Test Lab rents you real devices, but neither is something to install
here.

**iOS is not on this list and cannot be.** Xcode and the iOS SDK are macOS-only
and licensed to Apple hardware; no Linux container can host them. For web and
PWA work the answer is already installed: Playwright's WebKit is Safari's
engine, with iPhone device profiles. For a native iOS build you need a Mac.

**CI's toolchains are not these.** A workflow that runs `actions/setup-node`
downloads its own copy into its runner's tool cache on the node, versioned by
whatever that workflow asked for. The toolchain store is the other thing entirely:
what you installed, versioned by when you installed it. They are kept apart on
purpose: a workflow bumping a version must not move the ground under a Claude
session.

**The first boot after an update is not free.** A container whose share is
empty installs the Playwright browsers (~1.3GB) on first start. That happens
once per share; from then on updates cost nothing.

## Multiple Android versions

Nothing Android is in the image: the SDK, the emulator and the system images
are a node's, in its toolchain store. An API level exists where that store
holds a system image for it: add one on the Emulator tab with the node picked,
or let `bb emu create <api>` fetch it on demand. Each is given an AVD named
`builderbot-<api>`:

```bash
bb emu list          # levels with an image here, and which AVDs exist
bb emu start 37      # boot Android 17
bb emu start         # the newest level with an image
bb emu stop
bb emu log -p        # the previous boot's log: the post-mortem after a death
```

As of 2026 the supported range is **34–37** (Android 14 through 17). API 33 and
below stopped receiving security patches in March 2026.

**Where the space goes.** Nothing Android lives in the image at all: the SDK,
the platforms, the build-tools, the emulator and the system images are
installed into the node's [toolchain store](#the-toolchain-store-lives-outside-the-image), so
each is downloaded **once** and a weekly `:latest` rebuild re-fetches none of
them. Budget roughly **2 GB per API level**. If that is tight, pick the plain
**AOSP** flavor in the image picker instead of Google APIs: smaller, at the
price of Play services.

Two practical limits: an Android 17 phone AVD wants **4 GB of RAM minimum**, and
`bb emu` runs one emulator at a time; this is for testing across versions in
sequence, not a device farm.

**Rendering is software, and it fails in ways that look like your bug.** Under
`swiftshader_indirect` the guest has no DRM render node, so HWUI's default
Vulkan backend cannot start and every frame comes out blank while the app draws
perfectly: the view hierarchy is complete and the pixels are empty, with one
`E/MESA: Failed to open rendernode` in logcat as the only hint. `bb emu start`
sets `debug.hwui.renderer=skiagl` at boot to head that off; a shell `setprop`
does the same but does not survive a reboot, which is what made it look
intermittent. Two related failures are worth knowing: a window can stop
updating part-way through a long session (restart the app: the host log says
`Failed to find EmulatedEglImage`), and the emulator can exit silently under
load, after which `bb emu log -p` is the account of why. The log rotates on
each start rather than being overwritten, so a death survives the restart that
follows it.

**Using the GPU takes an X server, and not just any X server.** `-gpu host`
needs GLES from the host driver, and NVIDIA's EGL will not hand out a display
without an X server carrying its own GLX module, with none, the emulator
finds the card for Vulkan and then fails at `Failed to get EGL display` and
falls back. Xvfb does not fix it and is the obvious wrong turn: it has no
NVIDIA GLX, so EGL falls through to Mesa, which has no driver for an NVIDIA
card and lands on llvmpipe: software by a slower road than the emulator's own
SwiftShader.

So the card needs a real `Xorg` on the NVIDIA driver, started by the
machine, because a session runs unprivileged with no capabilities and cannot
become DRM master. **Set up GPU display** on the node's row (Nodes tab,
Health) is that: `bb-sandbox gpu` starts a headless Xorg on the card as a
unit of the machine's own, on the driver the Toolchains tab's row installed
(it installs none itself, and the row's line opens that tab until the driver
is there), which writes
what it found to `/run/builderbot-gpu-display` and restarts a dead server
three times before saying so. The driver takes the card only after a reboot,
which the row says and Reboot under Advanced does; bb-session binds the
server's socket into each session's own `/tmp`, so `bb emu start` inside a
session finds `:0`. `bb emu start` **tests** for
the hardware path rather than trusting it: EGL has to answer on an X server
with a vendor driver, and Mesa answering counts as failure for exactly the
reason above, and it falls back to software when it does not. `bb emu gpu`
says which you have and why, in one line.

## Static analysis reports

If you run a scanner on the host, only its **output** is mounted, read-only,
from `SCANNER_REPORTS_PATH`:

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
tab, the card's counts and the findings log have nothing to show in a dev
instance. `bb findings sample` writes one obviously-fake report, tool
`builderbot-sample`, with a finding in each of the first few projects on the
share and one on a path that places nowhere, so every shape those surfaces
draw has something to draw. It refuses to sit beside a real report, and it
refuses a read-only `/reports`, which is what a box with a real scanner has.
Run it inside the instance you want it in: it is not relayed to the
controller, because planting findings in somebody else's report directory is
not a thing a session should do.

A session reads its own project's findings and no others: not through the
Analysis tab, not in the poll's counts, and `bb findings --all` is refused for
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
The three filters are the Analysis tab's bar in flag form: `--level` takes
error, warning or note (note and info are one level everywhere here), `--rule`
matches a rule id exactly, `--find` searches rules, paths and messages, so a
question answered in the browser is askable from a session in one line.

**Review the diffs.** Findings need judgment about intent: whether a `|safe`
is deliberate, whether a SHA1 is for dedup rather than security. Asking Claude
to fix everything and re-scan unattended optimizes for a clean report, which is
not the same as better code, and suppressing a finding satisfies that goal too.

## Web dashboard

It serves everything on `7680`: the page, the API, and the browser
terminals, which are proxied under `/term` so one
sign-in covers them all. Signing in is a login page that sets a 30-day
cookie (a real form, so password managers work) not the browser's own
credentials dialog, and there is no second prompt for the terminal port
because there is no second port. The sign-out button beside ↻ and ▤ in the header ends the session (`/logout` does the same).

**The bell** in the header is where messages go to stay. A toast says a thing
once, for four seconds, to whoever happened to be looking: the right deal for
*saved*, and the wrong one for anything that failed while you were in another
tab. So every message the page shows lands behind the bell as well and stays
until you clear it, errors marked as errors. It is bare rather than boxed
because it is a state light first and a control second: a red dot means
something unread, an **amber** one means a session is blocked on an answer.
That second case is the reason it exists: a request to reach the phone shows
up there with **Approve** and **Deny** on it, for the account that connected
that phone and nobody else, so answering does not depend on the Nodes tab
being open. Clearing empties the page's own log and never an ask: a
question somebody is still waiting on is not this button's to dismiss. The log
is this tab's, so a reload draws a line under it; the asks are the server's and
are read live, which is why they leave the list the moment they are answered or
time out.

Pinned above that log, and not the Clear button's to dismiss, is what is waiting on you or stopping work: a session's phone request with Approve and Deny beside it, a notebook holding a session's changes for approval, a node whose agent has an update available, and (in red) a node whose agent is from another compatibility window, naming the projects that cannot build there until it is updated. Those rows come from the state on every poll and leave the moment they stop being true; nothing is stored to dismiss.

The **About** control beside it is the version, and where the header is too
narrow for a version string it becomes a **?** rather than a truncated number
that answers nothing: either way the popup behind it carries the whole stamp,
and behind one switch, a **getting-started guide** (a user's, or an
administrator's with the machinery added) and BuilderBot's **changelog**. The
panel opens itself twice in an account's life: on the guide the first time
the account signs in, and on the changelog once after every image update,
with a line under what is new since that account last looked. Closing it is
the acknowledgement.

The changelog there is **what is unreleased plus the current minor's own
releases**, each release under the categories it was filed into, and a line
saying how many earlier releases it is not showing. The question it answers is
"what changed in the build in front of me"; the file it reads keeps every
release forever and is where the rest of them are. Cutting a new minor takes
the previous one off that page in the same gesture, with nothing pruned. Every sidebar card collapses to its header with a click
on that header, and dragging a header reorders the cards; both are remembered
in `/config/cards.json`, so the phone and the desktop agree about the
arrangement and it survives restarts and image updates. The **▤** button in
the top bar opens the appearance menu, whose first item puts it all back:
default order (Doctor on top) with every card expanded.

**Under it, twelve color schemes**, all dark, because this page is read in a
dim room beside a terminal and a light one would be a different design rather
than a recolor of this one. A scheme is nine custom properties: every rule in
the stylesheet draws from them, and the button and accent families are mixed
from the scheme's own panel and accent (`color-mix`, with flat fallbacks), so
a recolor reaches the tabs, the primaries and the active states rather than
stopping at the background. Each swatch is defined for `.sw[data-theme=…]` as
well as for the page, which means the preview *is* the palette rather than a
second copy of it that can drift.

**Nostromo** is the one that is more than a recolor: amber phosphor on a
green-black hull, with a hazard decal along the header's bottom edge, a stencil
tick on each card title, faint scanlines on the panels and a vignette on the
page. All of it drawn: gradients and one pseudo-element, no image files. That
is the persistence rule rather than taste: an image would be a binary in the
repository, re-shipped in a weekly rebuild, for something two gradients say.
Nothing in it moves the layout, so switching schemes never nudges the page.

The choice is kept in the browser (`localStorage`, `bb.theme`) rather than on
the server beside the card order; that describes the work and should follow
you between machines; which colors are comfortable is about the room you are
sitting in, and a phone in the dark may reasonably differ from a desktop at
noon. It is also applied from a block in `<head>`, before the first paint,
which a value fetched from the server could not be without a flash. The sidebar is what the *box* is doing; the command lists and
the session list are about the shell in front of you, and hang off the
terminal instead; see below. On a touch screen, hold a header for half a second to pick
the card up; a finger that moves sooner is scrolling, and the sidebar scrolls
under it as if the header were not there: a fast flick that happens to land
on a header is never a misfire. The
headers hold nothing but the title and a chevron: every control a card has
lives in its body. The cards:

- container uptime, **and which build of the image is serving it**: the short
  commit beside the uptime, with the whole one and the time it was built on
  hover. The two are different questions: an Unraid container keeps running
  whatever it last pulled, so "up two hours" says nothing about whether a fix
  merged an hour ago is in there, and inferring one from the other is a good
  way to spend an afternoon debugging a bug that was already fixed. `unstamped`
  means the image was built outside CI. `bb status` prints the same line first,
  and `bb drift` is the other half: what a checkout has changed that the
  running container is not serving. Also runner state: registered, listening, **running a job**
  (with the job's name and how long it has been going), **waiting for GitHub
  to release the last session**, or **failing to connect**. The middle one is
  amber rather than red on purpose: GitHub holds a runner's session for a
  minute or two after the process that had it goes away, so every container
  restart and every finished job on an ephemeral runner spends a moment being
  refused its own name. It clears itself, and a self-clearing state wearing
  the same red as an outage sends you hunting for a fault that is the design
  working. That last one matters: a runner retries a rejected connection
  forever without exiting, so the process being up is not evidence that it is
  reachable. (Progress within a job is as far as it goes: a runner long-polls
  for one job at a time and is never told what else is queued, and how far
  through its own work a job is (tests passed, steps left) is known only to
  the tool inside the step.)
- every project under `/workspace` with its branch, and one-click **Claude**
  and **Shell** per project. Anything with a problem is folded away behind
  **Show projects with errors**, in red, a directory the container user
  cannot read/write/enter (with the `chown` that fixes it) or one holding no
  valid git repository. Only errors are folded away: a **warning stays in the
  list**, in amber, because it is asking for something. This is what
  makes one mapping for the whole folder workable: a directory that is not a
  project says so instead of quietly not appearing. Hidden directories are
  skipped outright, and empty directories are never listed either: a mount point waiting for
  content is not a fault to report.
  A directory holding a **`.bbignore`** file is not a project and is not
  listed: the container writes one into any path of its own that lands in
  the projects share (the toolchain store, if you map it inside the projects
  folder rather than beside it), and you can create one by hand for anything else
  you would rather not see. It *hides*; the padlock **blocks**, which is a
  different promise.
  At the foot of the card, **New project** creates one. A fresh local repo
  (`git init`) asks for a name and a free-text *Brief*: what you want
  built. The brief is not the project's `CLAUDE.md`, which every session
  reads as standing instructions and which would go on asserting the first
  day's decisions after the project moved past them. It is kept in the tree
  as `BUILDERBOT-BRIEF.md`, out of git through the repository's own exclude
  file, for the first Claude session: pressing Claude on the project opens
  it in a dialog, editable, beside the model and effort that session starts
  on. **Build it** starts the session with the brief as its first prompt;
  **Start without it** starts one that was not given it. Either way the
  brief leaves the tree then, and the notebook's Briefing view keeps it,
  as `bb brief` prints it. When nodes are
  enrolled it also asks which node the project runs on (the only one is
  picked for you; *none* is an option), the same setting the project's
  settings dialog changes later, so a new project can build and start a
  session without a second dialog. It asks the same way what a session
  may enter into the notebook (add to the roadmap, file bugs, add rules,
  fill in build and test), auto unless you say otherwise, so that is a
  choice made rather than a default found later. It can
  also start from an archive you already have: zip, or tar with gzip, bzip2
  or xz, unpacked into the new directory before `git init`. However it
  arrived, the code map a session asks before grepping (`bb map`) is built
  for it in the background the moment the tree is there: the dialog closes
  as usual, the row says *mapping the code* for the seconds it takes, and
  a Claude session on that project waits for it, so its first question
  about the tree is answered from an index rather than by building one. A single
  top-level folder inside is dropped (the project directory *is* that
  folder), desktop junk like `__MACOSX` is skipped, and no brief is asked
  for: an archive is where that project starts, so the field goes when one
  is picked, and a request carrying both is refused.
  Nothing is committed; the first session, or you, decides what the first
  commit is. Paths that would land outside the directory are refused whole. A clone
  of a GitHub repository asks for nothing but the URL: it is fetched with the
  container's own access (a deploy key or PAT that can already reach it).
  The directory takes the repository's name. A repo that carries a
  `CLAUDE.md` keeps its own, untouched, and one that does not gets none:
  the briefing a session reads is assembled by the controller, and an
  untracked draft in somebody's checkout was not worth the mystery.
  For a private repo with its own deploy key, a **Deploy key** picker lists
  what the shielded agent holds (public halves only, via `ssh-add -L`) and
  shows the selected key for copying into the repo's GitHub deploy-key page.
  Picking one makes the server handle the container side: it writes the
  `.pub` selector and an `IdentitiesOnly` ssh alias
  (`bb-<key>`, in a namespace of its own so hand-maintained config is never
  touched) and clones through the alias, which the remote then keeps, so
  later pushes offer the right key too. Only the matched agent key's own
  public line is ever written; nothing from the request is. With a PAT
  configured (a per-project token, or `gh auth login`) the key is optional even for
  private repos: gh answers for plain https remotes.
  Every repo wears a chain icon beside its eye, and it is the **remote**
  whichever state the project is in: for one with **no remote at all** it is
  **link**, and for one that already has a remote it opens that project's
  remote settings: the access token, which credential git reaches for, the
  repository's address, and **Unlink**, all described under
  [An access token for one project](#an-access-token-for-one-project),
  [A new address for the same repository](#a-new-address-for-the-same-repository) and
  [Unlinking](#unlinking).
  Linking asks **which host**: GitHub, Gitea, Forgejo, Codeberg, GitLab,
  Bitbucket, or another git host, because a hostname does not say what is
  running on it, and only the person who set the server up knows. A public
  one names itself; a self-hosted one asks for its address, and the answer is
  remembered against that host, so the second project on the same server is
  not asked again.
  Then it asks for the URL and how the push authenticates: a **deploy key**
  the agent holds, or an **access token** for this project alone, checked
  with the host where the host has an API to ask, stored under `/config` and
  read by git's helper. It sets `origin`, records the project as able to
  push, and pushes the current branch, but **only into an empty repository**:
  `git ls-remote` must come back with no refs first, so linking can never
  write over existing work. A repository that does not exist at all is
  created for you, always private, and only after the host itself has
  answered "not found": through the host's own API on GitHub, Gitea,
  Forgejo, Codeberg and GitLab, and through `gh repo create` on the GitHub
  path that uses the container's PAT. On a host with no API (Bitbucket,
  anything else) the repository has to exist already, and the refusal says so.
  The name is one path segment and the URL must be an https or ssh address
  with an owner and a repository in it: `git clone` accepts transports a web
  form should never reach, so anything else is refused server-side rather than
  passed along. A path deeper than `owner/repo` is refused too, except on
  GitLab, where subgroups make it a real part of an address.
  **A clone and a first push run in the background**, like an SDK install
  does: everything checkable is checked while the dialog is still up (the
  name, the URL, the key, whether the directory is free, whether the repo
  already has a remote), and then the dialog closes and the work carries on
  server-side. The job appears as its own row in this card, saying what it is
  doing: an ellipsis, not a percentage; git's progress is a
  carriage-return animation on stderr and parsing it back into a bar is a
  fight not worth having, with an **Abort** that stops it and removes a
  half-cloned directory. Close the page, sleep the phone, come back later:
  the job belongs to the server, and a reload picks it up mid-flight. If it
  fails, the message stays on the card until you dismiss it rather than
  passing through a toast you may not have been there to see. `git init` is
  the exception and stays synchronous; it is done before a spinner would
  render, and a row that flashes up for one frame is worse than none
- **Tools**: **Toolchains**, which opens the installer as a tab:
  every toolchain on the [toolchain store](#the-toolchain-store-lives-outside-the-image) with its
  size, its installed version, its path, and an amber line when a check finds
  a newer one. Ticks are for things there is something to do to; uninstalling
  is a bin on the row. A recipe that gives a session commands says under
  which name: they live under `bb tool NAME` (`bb tool graphics`, `bb tool
  diagrams`), one name per recipe, so the row says what installing it adds,
  two toolchains may both have a `render`, and none can shadow a verb of
  bb's own; the suite holds the catalog to the script. Each row also names the system packages its tool puts
  on the picked machine, in that machine's package manager's names, and for
  one already installed which of them are missing there. They install with
  the tool and only then; uninstalling a tool leaves them, since another may
  use the same library. Each list is written per package manager (apt, dnf,
  pacman, zypper, apk) and may name alternatives for a library renamed
  between releases; `tools/check-sysdeps.py` checks every name against the
  real package indexes of Ubuntu 22.04 to 26.04, Debian 12 and 13, Rocky 9
  and 10, Fedora, Arch, openSUSE and Alpine. A recipe's system libraries are each machine's own
  while the store is shared, so when a node lacks some for a toolchain the
  store already holds (a node enrolled after dotnet went in, with no
  libicu), a node BuilderBot manages installs them by itself the next time it
  reports in, once per missing set, and never while its system changes are
  locked to its console. Anywhere it cannot (a guest node, a locked one, an
  install that failed) the tab says which and **Install system packages**
  puts them on that node without reinstalling the toolchain, and the row
  that lacks them carries **Install them now**, which does it for that row
  alone; the node's row says the same, before a build fails on it. A
  toolchain another one needs (the JDK that PlantUML runs on, the Node that
  Playwright's module needs) is installed with it, and a row whose needed
  toolchain is not on the picked node says which and offers that row's own
  install. A toolchain that puts something on
  PATH reaches a session when the session starts, so its row says how many
  sessions open on that node started before it was installed, and to reopen
  them. Beside it, **Docker manager…**, **Emulator** (a node's Android
  system images: which it has, which AVDs are built on each, and ticking
  the ones to add as on Toolchains; ghosted until some node has the
  command-line tools and the emulator, with the reason in red under the
  card's buttons), **Analysis** (the scanner reports) and **Nodes**, each a
  tab of its own
- a **checklist** per project, carrying how much is still to hand over here,
  the same number the panel shows, refreshed with every poll and again the
  moment you open it. It opens
  the [notebook](#the-notebook): the one surface here that
  both you and a session write, with what Claude remembers folded away
  beneath it.
  Claude Code keeps memories in `~/.claude/projects/<slug>/memory/`:
  one markdown file per fact, plus a `MEMORY.md` index that is loaded into
  every session started there. Everything else a session is told is
  reviewable (`CLAUDE.md` through a pull request, the transcript on screen),
  but a memory writes itself and is never read back, so a wrong one steers
  every later session invisibly. The fold opens them: each memory folded to
  the summary line Claude wrote for itself (name, type, when), unfolding to
  the whole file in an editor, with **Forget this** to delete one, which
  takes its line out of the index too, since a pointer to a file that is gone
  is worse than no pointer. The index is not shown as a document of its own:
  it is one line per memory, so it is edited as **title** and **hook** fields
  on the memory that line names, and written back whole when you save. That
  is also the difference worth knowing: the index is the only part always in
  context, and the files themselves are read only when recall reaches for
  one. Drift between the index and the files is called
  out in amber both ways: a line naming a file that is not there, and a file
  no line names; saving clears the first and fills in the second.
  **+ write a memory** puts one there by hand: title, file name (slugged
  from the title until you type in it), kind, the one-line hook, and the
  memory itself: written with the frontmatter Claude uses and given its
  index line in the same act, never one without the other. Mostly Claude
  writes these itself; this is for the standing instruction you would
  otherwise repeat once a session and hope stuck.
  It sits on the project row rather than in a Claude tab on
  purpose, since *why did it do that?* is usually asked after the tab is closed,
  and it is folded shut, because a handful of files nobody edits does not
  earn the top of a panel. Editing one arms the panel's single **Save**, the
  same button the roadmap uses.
  **Edits land for the next session**: the index is read at startup, and a running session is holding what it read
  then, which is what Save tells it, in the one line it spends
- **(node: name)** after every project's name, on the card and on the
  Projects tab: the node its work runs on, or *none*. A project with none
  says nothing more; its Claude button is ghosted with where to pick one
- a **padlock** per project, which locks it: no Claude session starts there
  and its notebook goes read-only; see below. A locked row keeps every
  control, with its Claude button ghosted rather than removed and a closed
  padlock after the name; a row with a repo *error* carries no Claude button at
  all, because a session cannot start there. **Shell** stays either way, since
  that is often how you would fix it
- a **thumbtack** per project, which decides whether your sidebar shows it at
  all. The pins are each person's own: unpinning takes a project off your card
  and nobody else's, and nothing else: it keeps every control on the **All
  projects** tab at the foot of the card, which lists everything under
  `/workspace` with the same buttons on each row. Pins live per account in
  `/config/pinned-projects.json`. An account made since 7 Oct starts with
  nothing pinned and pins what it wants from **All projects**; one made
  before that with no set yet still sees everything pinned. The card and the
  tab both list projects by name, case aside
- a **bin**, which moves a project to `/workspace/.trash/<name>` with every
  file kept: a second delete of the same name is numbered rather than
  overwriting the first, and `/config` is not touched, so putting one back is
  a `mv`. It is on the **All projects** tab's rows (behind the row's fold on a
  phone) and as **Delete project…** at the foot of every project's settings
  dialog, the gear, on the card and the tab alike. Deliberately not a bare
  button on the sidebar card
- a **gear** per project, which is that project's own settings: its name, its
  node and the build and test commands that run there, what Claude starts on,
  what a session may enter into the notebook, and how much of the tree it may
  change without asking. GitHub is not in it; that is the chain, on the same
  row, so a credential has one home whether or not the project has a remote
  yet. Renaming changes the name it is shown under and nothing else (R154):
  a project has a permanent id and a directory that is never handed out again,
  and everything (the notebook, the containers, the sessions, Claude's own
  transcripts and memories) is keyed by the directory, so a rename moves
  nothing and needs nothing closed first. A name follows GitHub's rules for a
  repository's: letters, digits, `-`, `_` and `.` only, each run of anything
  else one `-`, so "Turing Lens" is shown as Turing-Lens, and the dialogs say
  so as it is typed. Two live projects are never shown under one name: a
  second gets Name-2, whether it was created, cloned or put back from the
  trash. A name ever used gives a new project the next free
  directory (Name-2), so it never inherits an old project's notebook or
  containers, and a project put back from the trash always fits where it was.
  Only BuilderBot makes a project (create, clone, or start from an imported
  archive): a folder made by hand on the share is not listed, and the folders
  already there when this arrived were recorded once, as they were
- a **padlock** per project, which locks it: the row stays whole and every
  control you use stays live (notebook, artifacts, dev instance, shell) and
  the only thing that goes is Claude starting a session there. For a project
  you keep in `/workspace` to deploy and run rather than to develop
The **Tools** card carries **Docker manager…**, which is where a project's
containers are built, started, stopped and given their env. A project can have
several: the Artifacts tab's dev row is one button now, **Send to Docker
manager…**, which names a container and takes you there; every container of a
project is built from that project's codebase, and rebuilding takes whatever
that codebase says at the time. It opens on the project's own name while the
project has no container and on `<project>-2`, `-3` after, so another one is
the same press, and a Claude session sends its project the same way with `bb
devapp new`, under the project's **Run its container** setting.

**The daemon is a node.** The sandbox VM is added on the Nodes tab: its
address, with `ssh://` and the `bb` account filled in, and what this
container's paths are called over there is set on the node's row, because
the daemon resolves a compose file's bind sources on its own filesystem. The
manager tab says which node it is on (*"on a sandbox VM at ssh://…"*) and
`bb doctor` prints the same line from the same function, so the two cannot
disagree about which daemon is live. (`DOCKER_HOST` and `DOCKER_HOST_PATHS`
named that machine in earlier releases; both are gone, with the `ssh` node
kind they belonged to.)

**A daemon has to say it is the sandbox before anything is driven on it.**
`nodes/provision-linux.sh` writes a `builderbot.sandbox` label into the VM's
`/etc/docker/daemon.json`; the dashboard reads it back with `docker info` over
the ssh connection it already has, and a daemon without it is refused exactly
like an unreachable one: named as the reason, with the command to fix it. An
ssh address only proves somebody typed one, and every one-shot container the
manager runs is root on the far side: what makes that reasonable is the far
side being a box built to be wrecked, which is a thing only the provisioner
can vouch for. A VM set up before this shipped has no stamp; re-running
`provision-linux.sh` adds it and changes nothing else.

**Point it at a different sandbox and that one becomes the source of truth.**
A build records the daemon's own id as well as its address, because two VMs can
wear one address: a rebuilt sandbox, a second machine given the old one's IP.
When the id changes, records claiming a build on the machine no longer in play
are cleared rather than left quoting a version this daemon has never seen; the
instances stay, since their compose file and env are this side's.

**With no daemon reachable, the controls that would drive one are disabled**,
each carrying the reason as its tooltip, and the manager tab says the same
thing in words at the top: a tooltip is not reachable on a phone, and *"why is
everything grayed out"* should be answered by looking. That is the node
unset, or a sandbox VM this container
cannot reach; `available()` in `devapp.py` already distinguishes them, and the
answer rides the status poll memoised, because asking it properly is a
subprocess and the poll is the page's heartbeat.

Three things deliberately stay live. **Refresh** is the retry; it drops the
memo, so a daemon wired up a moment ago is noticed by pressing it rather than
by waiting. **Edit** and **Env** open a compose file, which is a file whatever
can run it. And the manager tab still opens, because disabling the way to
*read* a diagnosis is how a dashboard goes quiet for no visible cause.

**The rows are still there, and they stop claiming anything.** What an
instance *is*: its name, its project, what it was last built from, what its
env still wants: lives on this side of the wire and needs no daemon; only
whether it is *running* is the daemon's to know. So a manager opened against a
VM that is off lists everything on record, grayed, each row saying **state
unknown** rather than reporting one nobody asked for: an unreachable daemon is
not evidence that anything stopped. It is also fast, because a daemon known to
be off is asked nothing: `docker ps` over ssh to a machine that is not there
sits until its timeout, and that used to be the whole cost of finding out.

**With more than one docker host, the manager grows a node picker.** Nodes
with the `docker-host` capability are listed online or not; picking one
switches the whole view to that node's daemon: one tab, re-rendered, never a
tab per node. Each node's last-known container list is kept, so switching to
an offline node paints instantly in the grayed state above rather than
spinning at a machine that will not answer, and the reason is that node's
own. **New container** and **Send to Docker manager** gain the same select,
defaulting to the project's own node from its settings dialog (a per-project
binding, `auto` unless chosen); an instance stays bound to the node it was
created on, and everything that acts on it: Up, Down, Rebuild, the data
directory's one-shot containers: addresses that node's daemon.

### The Nodes tab

**Tools → Nodes** is the registry (docs/nodes.md): every machine work can run
on. This container is not among them; it runs no work, takes no toolchains,
and has nothing any section here configures, so with nothing enrolled the tab
says so and offers the one thing there is to do. (It does keep a node record
of its own, which is how a share it mounts is recognized as the same store a
node mounts and installs are arbitrated across the pair; that is plumbing, not
a row.) The tab shows one node, picked at the
top: a header with its state, and where it dials in from, which is the address of its
last hello, so a node whose address moves is followed within a minute, its
terminals rebound onto the new address by its agent and the session-ports
rule on the node rewritten if the controller's own address is what moved,
and its agent (with
**Update agent** when this container ships a newer one, busy until the node
comes back on it), then **sections**, each a fold with its status on the
heading so a phone reads the headings and opens one: Health (the meters:
cpu, memory, the card's load and its own memory where an NVIDIA driver
answers, and each store's room; the toolchains its census found, which is what a project bound to it can
build), Sessions (whether it runs them, and which are open), CI runner,
Storage (mounts and stores), Network, and Advanced, which holds the node's
**name** (Rename changes what it is called everywhere here: the pickers,
the project rows and the label a runner installed from then on registers
with; a runner already installed keeps the label it registered with until
it is reinstalled), the path
mapping and the rarely pressed verbs: **Drain** (finish what is running,
accept nothing new: what makes a node safe to reboot), **Clear cache**,
**Revoke**, **Disable** (the operator, 11 Oct: kept and configured, its agent
dialing in, but off every picker, refused to a project's set and handed no
work or session until **Enable**), and **Un-enroll**, which on a node
provisioned as a sandbox that is dialing in uninstalls BuilderBot from the
machine and then removes the node here (retire: off every list, row kept as
history, and an id is never reused), and on any other removes the node here
only, saying BuilderBot's pieces stay on the machine. Neither Disable nor
Un-enroll goes through while a Claude session or a container is running on
the node: the refusal counts them and says where to end them (the Sessions
card, Down on the Docker tab). Un-enroll opens a dialog, since what goes is
in rings (the operator, 11 Oct). Always: the runners deregistered on their
forges, then the agent and its unit, the sessions' firewall rules and their
own networks (nothing of the isolation outlives the agent), the `bb` and
`builder` accounts with their homes, `/etc/builderbot` with the tunnel to
the controller, and bb-sandbox itself. Three boxes to tick: the stores on
the machine's own disk (toolchains, caches, artifacts, dev instance data, the
synced project copies, `/var/lib/builderbot`); what was configured from the
dashboard after enrolling (the mounts and their fstab lines, the runners'
units, the GPU display); and, ticked for a hosting node, what it was given
as a host (cloudflared with its token, Tailscale's login, the port 22 rule,
the nginx container). Unticked, those stay, so the machine can be enrolled
again, here or on another controller, with its stores and mounts as they
were. What the provisioner installed for the machine itself (docker, the
packages, the empty mountpoints, everything on the shares) is never touched.
The row is retired when the job is done. The same removal is `sudo
bb-sandbox uninstall [--stores] [--configured] [--doors]` on the machine, or
`provision-linux.sh --remove`; both say what will go and ask, and neither
deregisters a runner, which only the row can do while the agent can still
ask for the tokens. **Test** probes the channel end to end. **Enroll node** mints a one-time token; the machine
runs `nodes/provision-linux.sh --controller URL --token bbe_…` and dials in. That is
the only way in; there is no second enrollment, this container holds no key
that logs in anywhere, and a node reached by token alone takes every kind of
job, docker included. The **ssh node kind is retired** (roadmap #18): it
existed because compose used to run from this container over ssh, which meant
a node needed a key on top of its token and a token-only node: the cloud
case: could do everything except docker. The kind itself is gone now, and
`Add ssh node` with it: the endpoint answers with the way in rather than a
404. A node's **path mapping**: what this container's paths are called on
that machine, which its daemon needs to resolve a compose file's bind
sources: is on its row, and is where the old `DOCKER_HOST_PATHS` setting
lives. Every change writes an audit row. **Check**, beside the mapping,
proves the two machines mean the same directory by the projects share: a
marker is made under it here and looked for through the node's daemon, and
the row says plainly whether it was found: the one pair nothing else
verifies, and one that fails silently when it is wrong.

**A node does everything for the projects bound to it.** There is nothing to
pick per node: no "this one builds, that one deploys". A project names one
node in its settings dialog and its containers, builds, tests, CI and
emulation all go there, so three projects on three VMs stay apart and three
projects on one VM share it. **Its Claude sessions too** (roadmap #24,
docs/nodes.md §19): a node provisioned with a session account keeps two
ttyds up beside the agent, running bb-tty from the bb the controller ships,
so a session on a project bound to it works *on* that machine, with its
toolchains, in the copy of the project its agent keeps at `/workspace` in
step with this container's (a synced copy, the one way a node holds its
projects: nothing mounts the projects share on a node). The row's census
says whether that half is up (`session`: ports, account, which Claude the
account has) and how far each copy is; `bb roadmap`, `bb bug`, `bb version` and the other verbs
whose state is this container's are relayed back here over the API with the
session's own token. The terminal proxy sends a bound project's session to
that node when its row says the half is up and the project's copy is there, and
refuses with the reason (on the row's button and in the terminal) when
the node cannot take one, rather than starting it on the wrong machine. A
project with **no** node has no Claude session at all: this container carries
no Claude Code, so the button says so and names what to do. Its shell still
opens here, on the same share (a tree to read, the linters, git) because
what moved to a node is Claude and not the terminal. A node's sessions ride its
heartbeat onto the Sessions card with an "on <node>" pill, and ending one
there reaches the node's agent within a poll. What a project can actually do on its node is
what is **installed** there: the row lists the toolchains its census found,
and the Toolchains tab's node picker is where more are added. (Underneath, the
node still refuses a job asking for something it did not enrol with: the
enforcement of docs/nodes.md §15 door 7, but every node now enrols with the
full set, so it is a mechanism rather than a setting.)

**Create sandbox VM** is the step before all of this when there is no
machine yet. **Pick what runs it**: Unraid, Proxmox VE, libvirt/KVM, QEMU on
its own, VMware, Hyper-V or VirtualBox, and it writes that machine: the same
cores, memory, disk and installer everywhere, in whatever that manager reads
(a domain XML, a `qm create`, a `virt-install`, a `.vmx`, a PowerShell
script), with an identity of its own and the steps from that manager's own
"new VM" to an enrolled node. The identity is the part worth having written
for you: a uuid, the firmware variables named after it where the manager
keeps them that way, and **a MAC in the range that manager accepts**:
VMware refuses a static address outside `00:50:56:00-3F`, Hyper-V uses
`00:15:5D`, VirtualBox `08:00:27`, and QEMU and everything on top of it
`52:54:00`, so a hand-copied address is how two machines end up on one.
Paste the manager's own uuid and MAC into the two fields when the VM already
exists. `docs/sandbox-vm.md` is the long version.

**Enroll node** is the other way in, and the one the design is built around:
it makes a pending row and mints a one-time token (`bbe_…`, good for a day),
shown once inside the command to run on the machine,
`sudo bash provision-linux.sh --controller URL --token bbe_…`, or the two-line
version that fetches `builderbot-agent` by hand. The provisioner downloads
the agent from the controller itself (checking it against the digest the
controller sends), enrolls, and leaves it running under systemd. From then
on the node **dials out**: no port is opened on it, the controller holds no
key that logs in anywhere, and the credential the node keeps
(`/etc/builderbot/node.json`, 0600) opens its own row and nothing else.
Revoke on the row ends it; the agent says so in its journal and the row goes
quiet, keeping its history. The one-day life belongs to the *enrollment*
token only: the credential the node keeps afterwards does not expire, so an
enrolled node needs nothing renewed.

**Updating the agent is a button, never automatic.** The row says *update
available* when the node's agent is not the file this controller ships, and
**Update agent** hands it over as a job: the agent checks the download
against the digest, swaps itself in place and re-execs, so nothing on the
node restarts and no running job is interrupted. The agent will not swap
itself in under a running job, so while the update is queued the controller
hands that node nothing new and hands it the update once what was running
has finished, the row saying how many it waits for; a node that does not go
quiet within ten minutes fails the update with what kept it busy, and works
on. Re-running `provision-linux.sh` on an enrolled node does the same thing
from the console, with the node's own token. Nothing updates an agent
unasked.

**Until it is updated, that node takes nothing else.** The controller is
where the agent file comes from, so it is always the newer of the two, and a
job it queues may name something the older agent does not know: a job type,
a field in the spec, which an older agent meets with a shrug rather than an
error. So while *update available* is showing, Apply storage, Apply network,
Install runner, Clear cache and installing a toolchain onto that node are all
refused, with the reason on the button; the self-update itself is the one
thing that still goes through. Nodes running the shipped agent are unaffected.

**A store cannot be pointed at a share that is not mounted.** This is the
one storage mistake that looks like success: a share in fstab but not
mounted leaves its mountpoint an ordinary empty directory, the store gets
made inside it, and everything lands on the node's own disk while the row
reports a healthy store with plenty of room. Apply refuses it instead,
naming the share and what would have happened: fix the mount, or take it
out of the node's mounts if that path is meant to be local. At the console
`bb-sandbox` holds the same line from the other end: `remove` will not
unmount a share a store is inside without `--force`, `list` marks a mount
that holds stores, and a share that fails to mount says which store is
stranded in it.

**Repointing a store moves what is in it.** The contents are copied to the
new path before the switch, and the tab asks first, because a toolchain store
is tens of gigabytes and the job waits for the copy. Nothing is deleted: the
old copy stays where it was for you to remove once you are satisfied, so a
move that fails half way leaves the node still able to work. `cache` is the
exception; it is rebuildable, so it is left behind and the log says so.

**Saved is not applied.** The settings on a node's page are a record of what
it *should* be; **Apply** is what makes the machine match. The state line
under them says which of the two you are looking at: how many changes are
waiting and what they are, or that the node already matches, and Apply is
off when there is nothing to do. `dhcp` is the one thing it cannot answer:
the census reports the addresses a node has, not how it got them, so a node
set to `dhcp` keeps Apply network live and says so.

An agent node's row is *live* when a poll has arrived within the last 75
seconds, and the poll carries the numbers: CPU, memory, jobs running and
free space per store (`data`, `toolchains`, `cache`), so the row shows them
and `bb nodes` marks liveness (`●` live, `○` quiet). Test runs
`uname` there through the channel and shows the answer. Jobs run as the
account the node enrolled (`bb`, the docker account), never as root, and a
job needing a capability the node was not enrolled with is refused **on the
node** (exit 77), whatever the row says. Over plain http the node token
travels in the clear, as the dashboard's own credential does; enrollment says
so, and with TLS in front of the dashboard the agent pins the certificate on
first use and refuses a different one after.

Two nodes may point `toolchains` at the same NFS export deliberately, and then
they are one store, and what is installed on either is installed for both: a
node's toolchains are read from the store at every census, so its neighbor's
install shows up within the census interval. What that arrangement needs is a
lock, and it has one: an install is refused while a toolchain job is running on
any node sharing that store, naming which, and the Toolchains tab says the store
is shared before you press. Sharing is recognized by the mount's source, not
by the path, since every node's default path is the same string.

**Four stores per node**, each a directory of its own: `data` (job
workspaces and AVDs), `toolchains` (the toolchains installed there: what a
project bound to that node can build), `cache` (build caches, per project)
and `artifacts` (that node's copy of what its projects built, per project).
The artifacts store is what makes a node off the LAN reasonable: an emulator
or a container there starts from a copy beside it, and a second run of an
unchanged build copies nothing. A store path may not be a system directory:
`/etc`, anything under `/usr`, or a bare `/mnt`, because the agent creates,
fills and empties these; the refusal is made on the dashboard and again on
the node.

**Storage & network, from the row.** A node that enrolled as a sandbox (it
carries `bb-sandbox`) folds open an editor for what it should mount (NFS or
virtiofs, read-only or not), where the agent keeps its data, toolchain and
cache stores, and how it is addressed (DHCP, or a static address with gateway
and resolvers). **Save** keeps that on the node's record; **Apply storage**
and **Apply network** each queue a `system` job the agent runs as root
through the same `bb-sandbox` verbs the console uses, so the two can never
disagree about what the machine is configured to be. Every desired mount says
what the node reports for it: mounted, not mounted, not applied yet, or
mounted from somewhere else. A network change is the one that can cut the
cord it arrives on, so it is applied with a three-minute dial-back: the node
re-addresses itself and must reach the controller from the new address, or it
puts the previous config back on its own and says so when it reconnects.
The job names the address and never the tool: the agent detects what owns
the node's network: netplan, NetworkManager, systemd-networkd, wicked,
`/etc/network/interfaces` or dhcpcd, and writes it through that one, and
refuses, saying so, on a node with none of them. **Static routes** ride the
same apply, in dhcp mode or static, one a line as `10.20.0.0/24 via
192.168.1.1` (the operator, 7 Oct): each backend writes them its own way
(netplan's routes, NetworkManager's ipv4.routes, a `[Route]` section,
`up ip route add` lines, wicked's ifroute), dhcpcd, which has no setting
for one, refuses them by name, and the node reports the routes it has so
the row says which are still to apply. A network with no prefix, the
default route (the gateway is that) and a router that is not an address are
refused at Save. **Lock system changes**,
under the node's Advanced section, keeps all of that at the machine's own
console: while it is on, Apply storage, Apply network and a root command
are refused here with the reason, the desired configuration stays on the
record beside what the node reports, and the runner and a funnel, which
are BuilderBot's own footprint: are unaffected. For a node whose fstab and
address are managed by hand, or by something else. Nothing here is
offered to an ssh node or to local.

**Building there.** A project names its node in its settings dialog: one
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
themselves stay the dialog's. `bb build`, `bb test` and `bb run -- CMD` snapshot the working
tree here, dirty edits included, run on that node in a workspace of the job's
own, and stream the log back; what the outputs match comes back into `dist/`
by name with a provenance record beside it, which the Artifacts tab shows on
the row (which job, which node, which snapshot). The tab's **Download
source** hands over the code base itself as a zip through the browser: what
git tracks and would track, under one directory named for the project, never
`.git`, `dist/` or what `.gitignore` hides. A failed build keeps its
workspace on the node for a look, and says where. The census reports each
node's cache size beside **Clear cache**, and the Toolchains tab gains a node
picker: installing a toolchain there is a job that carries `bb` and the
catalog to the node's own toolchain store.

**Reads.** Under the nodes, a project's settings name the other projects a
session on it may read: their trees, bound read-only at `/workspace/NAME`
into the session's view on a node, and their notebooks, which `bb roadmap`,
`bb bug`, `bb rules`, `bb design` and the rest answer for with `bb -p NAME`
in front. Their running containers answer the session too, on its own
project's nodes, so a page of theirs can be opened and photographed with
`bb capture`; a read project's node the reading project is not on stays
out until the operator adds it. Every write is refused by name, on the API
and on the relayed verbs alike, and a session's Claude gets the same wall:
Read allowed, Edit denied. The briefing names the projects a session reads,
and the shipped "stay in project" rule carries the exception. Set by the
operator in the dialog, never by a session.

**Also sees.** Beside them, a project's settings name the places on its
node a session is shown: a share or a disk mounted there that the project
works with, by its path (`/mnt/media`). A session's view holds no other
(see the session's view, below), so this is how a project is given one. Set
by whoever may set the project's node, never by a session; a path that is
the system's own, the projects share, a home or the agent's is refused, and
a session started after the save sees the place. A path one of the
project's nodes does not have is passed over there.

**Compose runs on the node, not from here.** A dev instance's Up, Down,
Rebuild and Remove are executed by the agent with the node's own docker: the
dashboard sends the plan and the compose file, the node runs it. So an
enrolled node needs nothing but the token it enrolled with: no ssh key, no
open daemon port, nothing dialling in. (A node added as a plain `ssh` docker
host, the arrangement from before the agent, still runs compose from here
over ssh.)

**CI runners per node, one per git host.** The same fold lists the node's
runners and adds one with its host, address and token (kept root-only on
the controller): GitHub's runner and Gitea's `act_runner` (published as gitea-runner since it moved to gitea/runner) side by side,
each registered with labels `builderbot, self-hosted, linux, <arch>, <node
name>` plus any extra, so a workflow's `runs-on` names the node it should
land on whichever host its repository is on. Each row says whether its
runner is listening or busy; Remove deregisters it first. `bb ci-labels` lists every label the registry knows
and `--write` regenerates `.github/actionlint.yaml` from them, so the lint
checks `runs-on` against runners that exist. The container's own runner
stays until a node runner has taken a real job.

**A toolchain that needs another says so, and the missing one is installed
first.** `android-tools` drives `sdkmanager`, which is a Java program:
without a JDK it failed inside sdkmanager with a message naming neither Java
nor the toolchain that supplies it. The catalog carries `requires` now, the
install pulls in what is missing (never what is already there) and the tab
says what it added. Node.js is a toolchain like any other for the same reason:
it is not needed to *be* a node (the agent is Python, and the provisioner
installs that), but a project built with npm needs it, and so does anything
driving a browser through Playwright, which declares it.

**Two machines may share one toolchain store, and BuilderBot recognizes the
pair.** An NFS export mounted by the controller and by a node is one
directory, and two machines unpacking one toolchain into it at once is a
broken install nobody can debug, so a job waits for one on a machine that
shares the store only when both touch the same toolchain (the Android SDK,
one tree that sdkmanager keeps, counting as one), in both directions; two
different toolchains install on two machines side by side, and a check, the
NVIDIA driver, the container toolkit and system packages, which write no
store, wait for nothing there. One machine still runs one toolchain job at a
time. What identifies the pair is a marker file
inside the store itself, not the mount: this container reaches the toolchain store
through Unraid's FUSE layer while a node reaches the same bytes over NFS,
and neither mount string can be derived from the other. Nothing
machine-specific is written into a shared store: the generated
`sdk-env.sh`, whose every line is an absolute path, lives on the home volume
for that reason. Two architectures may share one: each machine installs under
its own `<os>-<arch>` scope in the store (R19), so an arm64 machine never
runs an x86-64 binary another put there.

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

The CI runner tab prints that line for each node, and `bb lint` says when
a project has a node and its workflows do not carry it: a note, not a
failure, because the workflow file is the repo's and this is advice. A
`runs-on` built from an expression is left alone: choosing the runner at
dispatch is a deliberate act, not a workflow that forgot.

**How an instance is reached.** Each running instance on the Docker manager
carries its route: the URL, a picker for the mode, and Apply, which is what
writes the pick: a pick alone changes nothing. **lan** is the
published port at the node's own address, what the manager always linked.
**funnel** is Tailscale Funnel on the node: a public https URL at the node's
MagicDNS name with no DNS, certificate or firewall change: applied by the
agent, so it is offered only on an agent node that has tailscale logged in;
the row says *asked for* until the node reports the funnel is up, and
switching back to lan closes it. **public**, a reverse proxy with a wildcard
record, is named in the picker as not built so the third mode is visible for
what it is (docs/nodes.md §7).

### The notebook's Git view

The seventh view of a project's notebook reads the repository out: what is
changed and not committed, each file a fold with its diff; the last hundred
commits across every branch as a graph, a node per commit and a curve to
each parent, with the branch and tag names on their rows; one commit's
message, author, files and diff when you pick it; and the branches, marked
with the one the tree is on and whose session's worktree sits on which
(`claude/<account>`), with how far each stands from `main` and from its
upstream, in plain words: "3 commits not yet in main", "same as main",
"in step with GitHub" (the host by its name, from the remote's address). The
branches are grouped by what there is to do with them: the one the tree is
on and `main` first, then work not yet in `main`, then branches already in
`main` with one **Delete** for all of them, then, folded, branches only the
remote has; a remote row that mirrors a local branch is not repeated. A
branch with work not yet in `main` opens to its commits and the diff `main`
would take, which is what a pull request page shows, so that page is not
needed to read work before accepting it. It
reads on open and again when the tree's history moves, never on the poll,
and every question is git plumbing on the controller against the project on
the share: a sha or a path from the address is checked against what the
repository itself reports before it reaches a command.

The view acts too, each button one fixed git command with checked arguments,
run under your author and the project's own credentials: **Fetch**, **Pull**
(fast-forward only, refused with uncommitted changes) and **Push** (through
the same path `bb git push` takes, offered only to a project with push
rights) on the bar under the head row; **Commit all** with a message at the
top of Changes and **Discard** on each file; **New branch** at the top of
Branches, **Merge into main** on a branch (from any branch, the way a pull
request's button merges: it lands in a temporary worktree on `main`, so the
tree does not move and the owner's session need not end; a clash is
abandoned whole and Send to Claude is what finishes it; nothing touches the
remote), **Merge main into here** on the `main` row when the tree is
elsewhere (in place, so refused while the owner's Claude session stands in
the directory, and a conflict is left standing for the Changes section to
hand to Claude), **Switch** (refused under a session likewise, or with
uncommitted changes) and **Delete**, which refuses a branch holding commits
no other branch has until you say so twice, and says which of the two kinds
it is: a branch whose commits change nothing `main` lacks is history going,
not work. Merge into main waits while the copy of `main` here is behind the
host, and names the pull, because merging into it is how that copy ends up
both ahead and behind. The **only on `<host>`** fold says of each branch
whether `main` already has every commit on it, and offers **Delete on
`<host>`** for the ones where it does, which is the only case where removing
a branch there can lose nothing. **Revert** and **Branch here**
on a picked commit. A session's token
has none of these (it has `bb git`) and a locked project takes no action.
Send to Claude and the per-project git policy are roadmap R36's last step.
On a phone the notebook's strip wraps into rows so all seven views stay on
screen.

### The Jobs tab

**Tools → Jobs** is the queue (docs/nodes.md §2, phase 4): everything the
controller has taken: a compose action on a dev instance, an exec on a node,
an agent self-update, with where it was placed, what it is doing now, how it
ended and its log. A job is placed on a node named outright or on whichever
node fits a selector (capability, labels, pool, OS, architecture), and the
choice is frozen on the row when the job is taken; a selector nothing fits is
refused when it is queued, naming the selector. Each node runs as many jobs at
once as its row allows; the rest wait in order. **Cancel** on a row stops one
where it is: a queued job never starts, a running one is killed and the row
moves when the runner reports that it did, and nothing edits a job after the
fact. The checkbox in the bar narrows the list to what is running or waiting.
`bb jobs` prints the same list read-only, so a session can see what became of
the work it asked for, and `bb jobs j_1a2b3c4d` prints one job's log. **Both
are the whole queue, not one project's.** That is deliberate and worth
knowing: the tab and the API scope a job to projects the account may see, and
these read the store directly, so a session can be asked to look at why
something failed on another project, which is the situation somebody is in
when they ask for help. The log is the only copy: a node buffers it and posts
it here, and keeps nothing. `/api/v1/healthz` answers without a credential with
the queue's counts, and `/metrics` answers with one in Prometheus text.

### The Settings tab

The gear in the header keeps what belongs to this **browser**: theme and
layout, and one entry, **Profile**, opening the signed-in account's own
tab: their account name, their name and email, the name and email their
commits carry (blank means the ones above), and a password change that asks
for the current one first. Neither a Claude session nor a shell starts for an account with no
name and email for commits, and `bb git` refuses for it: every project is a
repository, and a shell is where git is typed, and the row's buttons say so
until the Profile has them. Blank git fields fall back to the name and email
above and to nothing else; no address is ever made up. **Conversation logs**
on the same tab lists the account's own conversations with Claude, newest
first with the first thing typed, and each downloads as a text file: what
was said on both sides, every command Claude ran and what the command
answered, `bb roadmap` and its reply included, from the transcript Claude
Code writes as the session goes (transcripts.py reads the account's
`~/.claude/projects` directory, the one on the share). Each line is
stamped in the browser's own zone, the one the page shows times in, so the
log and the page agree; a line headed System is what BuilderBot or Claude
Code put in front of Claude. Claude's private reasoning is not conversation
and is left out, and another account's file is simply not found. A session
reads the same: `bb transcripts` lists the account's own conversations on
its project and `bb transcripts show ID` prints one, and with `bb -p NAME`
the same on a project its own reads, whose transcript files of the account's
are in the session's view read-only as well; nobody else's are anywhere. The commit identity is per account rather than per project, and
reaches every session and shell that account opens as git's environment,
which outranks whatever a repository has configured, so two people on one
project are two authors. The **Administration** card on the sidebar, shown
only to administrators, holds **Controller settings**, opening the Settings
tab, and **Users**. The Settings tab is what the
**controller** owns and can apply live. The session-log policy lives there,
and the idle rule for Claude sessions: end one after N minutes with nothing
typed or written, here and on every node, where the node itself enforces it
so the rule holds while this container is down; its **Storage** section,
where each kind of thing that grows (project snapshots, job snapshots, the
git relay's repositories, the Git view's working area, the logs) is kept,
moved to a new empty path on Apply and switched once all of it is there,
while the records, the database, the signing keys and the git credentials
stay in the state directory (`paths.py`); its **Public hostname** group,
where the controller runs the home tunnel itself (R176, `tunnel.py`): the
hostname a node off the LAN dials, the tunnel's token from Zero Trust
(a secret, said to be set and never shown back), and an optional Cloudflare
API token with which the hostname's record and the tunnel's two rules (the
agent's API to the controller, everything else 404) are written on Apply
rather than clicked; the group's line says whether cloudflared is in the
image, running and registered; and the tab says
plainly what still comes from the environment and why (the placement rule and
the unhardwiring are docs/nodes.md §13 and §11). One switch in its
Debugging dialog, *Offer dev features* (Debug mode on, then Debug settings),
decides which product this dashboard is: alpha is what has been run for
real (GitHub and Gitea among git hosts, Unraid among the VM sandbox
methods, Debian's and RHEL's families for the provisioner), dev is the rest,
written to each product's documented shape and never run. Off, only alpha
is in the pickers and a dev entry asked for by name is refused with the
sentence that names the switch; on, dev appears tagged *(dev)* and the
header says *dev*, so the two dashboards are never confused. Each catalog
entry carries the evidence that vetted it (`forges.py`, `vmtemplate.py`,
the provisioner's family list), and an entry crosses over when a lab suite
or a real run proves it. At its foot, **Reset BuilderBot** starts the
controller over at *Create the owner*: accounts, node enrolments, project
settings, git tokens, the notebook, memories and logs are moved into a dated
`.reset-…` directory under `/config`, never deleted, and project files are
not touched; it asks for the word `reset` typed, and the dashboard
re-executes itself. Projects are trashed from the Projects tab, one at a
time, the way they always were. Its **Debugging** group is
one switch, *Debug mode*, and a *Debug settings* button beside it that is
live only while the switch is saved on: behind the button are the settings
a developer of BuilderBot reaches for and nobody else should meet (offering
the untested git hosts, hypervisors and node systems).

Each row folds open to show what that container publishes and what it mounts,
read only when you open it: parsing a compose file is the one thing the page
deliberately does not do for every row at once. Lines wrap rather than scroll:
a host path is long, and a row that scrolls sideways on a phone hides the half
you were reading.

**A long build says what it is doing, and can be stopped.** The command's
output is streamed into the row as it arrives rather than handed over when it
exits, so a `compose build` spending four minutes pulling layers is not four
minutes of a spinner. The phase word above it still says *building* or
*starting*; the tail below says what the phase is spending its time on. It is
raw and deliberately not parsed into a bar: docker rewrites a line per layer
per tick, and turning that into a percentage is the thing the Toolchains tab
already gave up on.

**Abort** sits beside it while a job runs, and asks nothing first. Stopping a
build is not destructive: what is already built is kept, exactly as a failed
build's work is, and the signal goes to the process *group*, because a compose
CLI waiting on a pull leaves the download running if only the CLI is asked to
stop. The row then says how the job ended rather than silently reverting to
whatever state it was in.

**New container** on that tab runs something with no project behind it, and
takes the **project** it belongs to (Send to Docker manager takes the same,
with the project it is built from picked by default): a
name, a compose file and an environment, which is the shape Portainer's stacks
and Dockge use. Labels are not a fourth box, in compose they belong in the
YAML. The compose file is checked by compose itself before it is saved, and
kept in `/config/containers/<name>/` where no project scan can see it; its
relative bind sources resolve against its own data directory under `/devdata`,
which is a path the daemon has; this container too where the share is
mounted here, and only the sandbox where it is not. Removing one takes its files
with it, because its compose file *is* the thing.

It lists what has been sent to it, not every project that could be sent: a
project with a compose file does not appear there until you send one, and
**Remove** takes a container down and drops it from the list again. Removing
keeps its env file and its data directory, so sending it again under the same
name finds them, and the project's Artifacts tab is untouched either way,
which is where it comes back from.

The same tab lists every container on the picked node's daemon, not only the ones this
dashboard started. A port taken by something else is exactly what you open a
list like this to find out about, so the others are shown and marked *not ours*
rather than hidden, and an administrator can start, stop and restart one by
name and read its log.

**Every row belongs to a project or to none**, and the tab is grouped that way:
each project's containers together under its name, the projects in
alphabetical order, and what belongs to none last. A container built from a
project belongs to it until its row says otherwise, one written here belongs
to the project picked when it was made, and one somebody else started belongs
to none until an administrator picks a project on its row; that choice is kept
by name on its node, so the same container recreated keeps it. The project it
belongs to lists it in its notebook's Docker view, and that project's Claude
sessions are the only ones that can see it: `bb devapp ls` lists them and `bb
devapp log NAME` reads one, while rebuilding, changing the env, starting and
stopping follow that project's *Claude may: Run its container*. An account
that is not an administrator sees what belongs to its projects.

- a rendered **findings report**: the SARIF your scanner drops in `/reports`,
  grouped by project and rule, with severity counts and CVEs linked to NVD.
  Project groups start collapsed: the severity pills on each are the overview,
  and what you open stays open across reloads. If the scanner re-runs while
  the report is open, the view reloads itself: the page watches the report
  files' mtime, so you never triage stale findings. The sidebar card carries
  the headline: one row per project with its counts by severity, so "whose
  code, how bad" is answered without opening the report. Both leave out
  projects with repo errors; those get fixed in the Projects card first, and
  a *locked* one is not in that category, and the report says how many
  findings that held back
  rather than quietly shrinking
- a **Stop / Start** toggle for the runner, showing whichever one applies.
  Stopping waits for GitHub to release the runner's session rather than
  reporting success and leaving a listener behind
- every `bb` command as a button, pinnable, typed into the terminal you are
  looking at, and a second card for **your own** command lists. Every such
  button grays out while the tab on screen is a Claude session or a document:
  commands only ever go to a plain shell, never quietly to some other tab
- live list of tmux sessions, named exactly as their tabs are, with the same
  hover text the tabs carry. **Click the name** to go to its tab, reopening
  it first if it was minimized. The button beside it does the other thing:
  **Open** when the tab is minimized; when the tab is on the bar it turns
  green and reads **Minimize** for a shell, or **Close** for a Claude session,
  which asks first, because that ends the conversation. An **attached** pill
  marks the sessions on screen right now, with ◧/◨ saying which pane when
  the view is split.
  Every Claude session (in this list and on its tab) carries a **state dot**:
  blue and pulsing while it works, amber when it is waiting on you (input, a
  permission decision, or a finished turn), with the task it reported
  alongside. That is the phone-glance question answered without opening the
  terminal: is it still going, or does it need me? The state comes from the
  terminal title Claude Code itself maintains, read through tmux: no polling
  of the conversation, no extra process
- a **Doctor** card: `bb doctor`'s checks, run by the server in the background
  every 30 minutes and
  re-run on demand with its ↻. Its status row wears the verdict as a dot,
  green, amber or red, beside an "all n ok" button that unfolds the detail:
  failures and warnings as full lines, with the fix hint from `bb doctor`'s
  own output in the tooltip, and passing checks collapsed into green chips.
  A verdict getting worse unfolds that detail by itself; healing folds it
  back. Only the detail: collapsing the whole card is your setting, and the
  verdict never overrides it. A plain user's card carries only the lines
  that are theirs to act on (whether a node can run their session); the
  runner tokens, ssh keys and the docker daemon are an administrator's

### Tabs and panes

**A terminal tab closes itself when its session ends.** `bb-tty` execs claude,
so the pane's process *is* the conversation. Exit it with Ctrl+C twice, `/exit`,
Ctrl+D, or a crash, and the tmux session goes with it, and the tab closes rather
than holding a dead terminal until somebody presses ✕. Shells too: one you
typed `exit` in is just as dead.

Nothing is lost by closing it. The transcript is on disk and the project's
Claude button offers to resume it, which is a better way back than a corpse in
a tab: the row knows the transcript id and the dead tab does not.

The rule is *seen alive, then gone*, and the transition is load-bearing: "has
no session" is also true of every tab restored from a saved layout before
anything has started, and of all of them for a moment if a poll ever comes back
empty. Reaping on absence would wipe the strip at every boot.

The page starts with one tab (**workspace**, a shell at `/workspace`) and
everything you open gets its own tab above the terminal. Every tab, the
workspace one included, can be minimized or closed; an empty strip just shows
a placeholder, and **+** starts over. On a desktop a terminal tab can also be
popped out into its own window (the ⧉ on the tab): the tab stays in the strip
as a blank pane with **Reattach**, in a split view as in a single one, and
closing the window brings it back on its own. The window is the terminal's
own address, so closing the dashboard leaves it working.

- **Claude** on a project opens *one* session per project. If it is already
  running the button is green and takes you to its tab. If it is not but the
  project has a previous conversation, you are asked whether to **resume** it
  or start a **new** one: the tmux session dies with a container restart, the
  transcript does not.
- **Shell** opens *another* terminal at the project path every time you click
  it, so you can have several side by side. **+**, at the left of the tab
  strip, does the same for `/workspace`.
- **Static analysis** on the Tools card opens the **Analysis** tab: the
  whole report, a project selector, and a filter bar (level, free text): a
  *document* tab, not a terminal. It is a report to read; putting it through a
  PTY would only make it harder to. The notebook's own Analysis view is the
  same report already narrowed to that project. With nothing readable in
  `/reports` the button is **ghosted** and says which of the three reasons it
  is (no mount, nothing in it, or nothing in it that parses) and a tab
  restored from a saved layout is closed once, on the load that finds out,
  rather than left open to say "nothing here"
- **`&mdash;` on a tab minimizes it**, and asks nothing. The terminal keeps running
  and is listed under Sessions, where **Open** brings it back; a **Claude** tab
  is the same, the conversation carries on without a tab. Nothing is lost, so
  nothing is asked. **Middle-clicking** a terminal tab is the stronger thing,
  the way it is in a browser: it ends the session, after the same question
  the Sessions ✕ asks, and closes the tab with it.
- **✕ appears on document tabs**, the notebook and Analysis, because a document
  has no session to keep. The notebook asks first if anything in it is unsaved;
  nothing else does.
### Reporting a problem with BuilderBot

A problem with BuilderBot itself goes to the **diagnostics**, where whoever
looks after this BuilderBot reads it (`bb diag reports`). It is a log, not a
conversation: nothing goes back to whoever sent it, and **Clear reports**
empties it. A session sends one with `bb report "what happened"`, under the
project's **Claude may: Report BuilderBot bugs**. A person sends one from a
project's row: the bug button opens **Report a bug**, with a category to
pick, what happened and how to make it happen, and **Send** puts it in the
diagnostics under that project with its node and the build it was seen on,
marked as from the dashboard. A person's report is heard whatever that
project's Claude dial says, from a project they are on: an administrator
shown every project but not on this one cannot start a session there, so
the row has no bug button for them and the server refuses one. A
project's report can carry the reporter's latest conversation on it,
ticked in the dialog: its last 400 KB, redacted, kept as a file of its own
beside the report. The diagnostics name that file, the download beside the
logs is a zip of `diagnostics.json` with a `conversations/` folder holding
each one, and `bb report conversation N` prints it for a session. The bug in
the header is the same dialog about no project in particular, for anybody
signed in, and the diagnostics list it as general.

### The notebook

Every project has one, reachable from the **Notebook** button on its row: a tab
of its own, one per project, and as many open at once as you have projects;
each is its own instance, so what is half-typed in one survives working in
another, and the button lights green while that project's is open. Its tab
strip: **Briefing** (the rules, and what Claude remembers here), **Design**
(what the project looks like, in two folds: the pages, laid out as
labeled blocks on a phone or desktop frame, each named for what it is for
and the platform it is built for, a web app or an Android, iOS, Linux,
macOS or Windows app, since one project can be several; and the themes,
each a named set of colors, dark or light, that a preset fills and you add
to or cut, the app starting on the first, and each carrying the design
language of its own: type and the exact families, shape, space, motion,
and its rules. The first theme is the default, and its choices and rules
are the design's: said bare, as the design's own, in the briefing and the
file; another theme's are said under it where they differ, and its rules
reach a session named under the theme, `nostromo/hull`. What the language
governs sits at the top of the themes. A page carries rules of its own as
well, for what holds for that page alone, named under the page. Every
rules list reads as the Briefing's does, a folded row a rule, inside the
entry it holds for: a theme's under its choices, a page's under its
board. A new theme starts blank, from a preset or as a copy of a theme
here, choices and rules included, and a new page from a template or as a
copy of a page here. The pages and the themes show one at a time, chosen
on a pulldown; a frame is
one screen and a page may be longer than one, up to 240 rows, which
scrolls, and a page keeps where its blocks sit on each frame it has been
laid out for, which `bb design show` and the file say after the frame it is
on; blocks may overlap, and the blocks' order is the drawing order, a
later one over an earlier one, which a layers list beside the board shows
top first, a row selecting a block another covers and its arrows moving it
up or down the stack; a block may be set inside another (a card in a list,
a form in a card), which it then stays within as either is moved or sized,
on every frame, and the board takes the width the tab gives it, with
Pages, Design language and Themes folded on a new tab and Add page inside
Pages; a page may have a short key of its own, which its rules are addressed under
(`now/live`) in place of its whole name; each of the language's four
choices may be left not chosen, or be custom, which hands it to the
design's rules and can name the one that says it, whose text a session
then reads in the choice's place; the words a session reads
are the record's own and nothing is added to them; a new project's
design is empty, no theme and no page, and a project built that way is
built as a session sees fit, the session then putting the look it arrived
at into the design so the next one finds it; a project designed before it
is built is built to the design: its briefing says the notebook holds one,
what is in it, that on a tree with no code yet the design, the rules
and the roadmap are the specification, and that what the design leaves
open goes back into it, under the project's dial; every edit is
staged behind Save, nothing on the view is a prompt and nothing on it
reaches into a session: a session meets the design by itself and piece by
piece, through the rules its briefing names and `bb design show`, which
prints the language, one page, one theme or one rule; a session asked to put a design into
the notebook writes the same record with `bb design save`, which keeps a
record as it was sent or refuses it whole with everything wrong with it
listed, never moving a block to fit or dropping a layout; and Write the
file puts `docs/design-language.md` into the tree for every session to
read), **Wiki** (the project's wiki, described below), the
**Roadmap** (the shared list of design work and ordered plans), **Bugs**,
**Git**, **Artifacts**, **Docker** (every container that belongs to this
project, with the manager's rows and controls, so a dev radarr for a media
project is found beside that project rather than among every project's on
the Docker tab),
**Tests**, and **Analysis** (the scanner's findings for this project alone).

The **Wiki** is the project's wiki, for whoever uses or works on it: pages
of Markdown that a person writes on the view or a session writes with
`bb wiki save`, under the project's dial Claude may: Write the wiki (auto
lands a page, ask holds it on the notebook for approval with its text, deny
refuses it, and hidden keeps the wiki from sessions altogether, reading
included, for notes that are the people's alone). It reads like an encyclopedia: one article at a time, its title over a
rule, a Contents box for a page with three or more sections, the prose in a
serif at a reading width, and the pages listed beside it (the wiki's own
`_Sidebar` when it has one, a picker above the article on a phone), with
`[[Another page]]` opening that page in place. Read and Edit are tabs over
the article, Save writes it through, and a page somebody changed since it
was opened is refused rather than overwritten. The controller keeps it as a git
repository of its own (`/config/wiki/PROJECT`) in the shape a forge's wiki
has, one `Page-Name.md` per page with `Home`, `_Sidebar` and `_Footer` as
GitHub reads them, so every change has a history and the wiki is never in
the project's tree, where a session could rewrite what the controller then
pushes. **Export** is a zip of the pages, which works for any project, with
a remote or without. A project with push rights on GitHub, Gitea or GitLab
gets **Push**, which sends the wiki to the repository's own `.wiki.git`
with the project's credentials, and **Pull**, which takes in what was
changed there (a page changed on both sides is named and nothing is taken
until one side matches). A forge makes a wiki's repository only when its
first page is saved on the web, so a first push to a repository with no
wiki says to make one page there; that page (GitHub calls it Home) is then
the forge's own, and Push offers to replace the forge's wiki with this one,
which is what a first push wants, or Pull to merge the two. GitHub's fine-grained tokens cannot write
a wiki; a classic token with the repo scope can. Pushing and pulling are a
person's: they reach outside BuilderBot.

**Unsaved work does not cross those views.** Leaving a view asks, and answering
yes throws the change away rather than carrying it to the next tab.

**A History, and the changelog, open over the panel rather than in place of
it**: a large box on a desktop, the whole screen on a phone. They are things
you *read*, so the list you are reading them against stays behind them, and
**Close**, Escape or a click outside puts the log back where it came from.
What goes into the sheet is the real element,
moved, so the filter bar keeps every handler it had and there is no second
copy of it to drift.

**It opens on the first tab of the strip**: Memory today, and whatever is
first if the strip is ever reordered, since the default is read off the strip
rather than marked on one of the buttons. After that it stays where you left
it: the notebook is one instance per project, parked and reused, so going off
to a terminal and coming back finds the view you were on. Closing the tab ends
that instance, so the next open starts at the first tab again, which is the
same rule that makes closing it drop whatever was staged in it.

**The roadmap** is `bb roadmap` in a terminal. Saving does not close it; the
Save buttons simply go dead until there is something to save again, and the
button beside them is **Revert**, which throws away what has not been saved
and is dead whenever there is nothing to throw. It fills the pane rather than
sitting in it, and the pane is the only thing that scrolls. Closing the tab
asks first if anything is unsaved. It is the one surface here that
**both sides write**:
you add "make the picker wrap properly", a session adds "a project can be
created in one click and only deleted from a shell", and either of you can tick
something off.

**Every change to a list is kept.** Both sides write these, and the list
itself only ever shows the present tense, so *was that step always worded
like that?* and *who dropped the third one?* had no answer at all.
**History**, at the top of the view where the other three tabs keep theirs, is
the answer: one line per change, newest
first, each with its date and time and whether you or a session made it. A
reword shows both wordings, the old one struck through. `bb roadmap history`
prints the same log in a terminal.

That log is also what makes deleting safe, because the list now holds nothing
but outstanding work. **A ticked-off item comes off it**: a list is read to
find out what is left, and a thing that is finished is not left. `bb roadmap
done N` moves it into the log under *done*, where `rm N` would have put it
under *dropped*; both leave, and the log says which happened. Only a session
ticks things off, because only the session that did the work knows.

**The strike icon is only ever an undo.** It appears on a line that *has* been
sent, to put it back so it can go again; there is no crossing one off by
hand, because "I crossed that off" is not the same claim as "that is done". A
line you handled yourself gets dropped, and its words stay in the log to be
retyped if you were wrong.

**Nothing the panel does reaches the list until you press Save.** Type three
steps, reword one, drop another, shuffle the order; it is all held on the
page until then, so a plan can be looked at whole before it is committed to.
Close asks, names how many changes would go, and puts the list back exactly as
it was. The one exception is the send arrow: it types into a live session,
which no Save button can take back, so it flushes whatever is staged first and
then goes.

**Each project has its own emulator.** A virtual phone's AVDs lived in the
account's home, so every project's session of one account booted the same
phone, with whatever another project had installed and signed into on it:
BuilderBot's own companion app, signed in to the dev instance, turned up on
Shebang-DevBoard's home screen (B511). `bb emu` keeps each project's AVDs in
a folder of its own (`~/.android/avd-projects/PROJECT`), and a project's
first `bb emu start` makes its phone. With nothing making projects take
turns, `bb emu start` decides whether the node has room for another: not
while the node is saturated, and only with the phone's memory, the
emulator's own and 2 GB for builds free, waiting up to five minutes for
room and then refusing with the numbers; a card short of a few hundred MB
free renders that phone in software. The phones from before are one
project's to keep (`bb emu adopt`, or automatically for the project named
in the old folder's `.heir`), and a `bb-scrub.txt` beside an adopted phone
names packages another project left there, removed on its first boot.

**Each section saves its own.** A notebook section that stages anything (the
roadmap's list, the Memories, Your rules, each Version, the Design's Themes
and Pages) carries its own Save and Revert at its foot, which write or throw
away that section's changes and nothing else's; there is no notebook-wide
Save, since one at the bottom was a long scroll on a phone from the change it
saved. A view opens on its first section; on a phone one is open at a
time, opening one closing the others, and on a desktop several may stand
open (the operator, 7 Oct).

While a session has a batch open, **the roadmap's Save is held**, and only
that Save. You can still type, edit, drop and revert; what waits is writing
back, because what is on your screen was read before the session started and
saving over a list that has moved underneath is how two writers lose each
other's work. The block is one-way: nothing in the panel ever makes a session
wait. When the batch commits the notebook says so and offers to reload, since
what it is holding is now out of date.

**That hold is the panel's own, and it is not a lock.** Nothing here
serializes writers: `bb` and a second session write straight through an open
batch, and two browsers can have the same notebook open. What stops the loss
is per write, below.

**One batch covers the whole notebook**, not just the roadmap. Bugs filed,
noted or closed while one is open are staged the same way, and `bb bug begin`,
`commit` and `revert` are the same three commands reached from the other tab's
name: `notebook.py` sequences the two halves so that half a batch is a state
the front door cannot reach. A plan usually moves *because* of what the tracker
now says, and committing one while reverting the other would leave a roadmap
describing work against a tracker that never recorded why, with nothing
afterwards able to notice. The memories are outside it: a session writes those
as files with its own tools, so there is no write to intercept and `revert`
will not put one back.

A session gets the same idea in a different shape: `bb roadmap begin`, then work,
then `bb roadmap commit`: the changes land on the list as they are made, because
that is how you can see what a session is doing, but the *record* is written
once at commit. Rewording the same step four times is one history entry rather
than four. `bb roadmap revert` puts the list back and writes nothing, and refuses
if you have touched the list yourself since the batch opened.

**Dropping something asks why.** The bin opens a box under the row with an
optional reason field, and the reason is kept with the entry and is
searchable, because nothing here can be undone, and that note is the only
thing between a dropped line and somebody adding it straight back. The log
can be narrowed rather than read whole: search the lines, their previous
wordings and the reasons things went, over a window of time, capped to a
count. `bb roadmap history --find picker --since 7d` does the same in a
terminal, which is how a session reads it without spending its context on
the whole thing.

**Shelving** is the state between *do this* and *we are not doing this*: the
tray icon parks an item, sinks it to the bottom, dims it and kills its
arrows, and a session is told it is parked rather than left to wonder. It is
the only control here that undoes itself (the same tap brings it back) and
it applies to an item, never to one step of a plan, because the thing you
have decided not to do now is the whole plan. Shelved items do not count
towards the number on the project row. A session can shelve (something turns
out to be blocked, and saying so on the row beats saying it in a reply nobody
re-reads), and can ask for one back with `bb roadmap unshelve N WHY`: taking
one off reverses a decision it was not told the reason for, so the request
is held on the notebook with its reason, whatever the roadmap gate says, and
a user or administrator on the project approves or denies it there.
**Finished** at the top of the tab shows the items ticked off, with the
plans they had, below the shelved ones; they are hidden until asked for,
because a list is read to find out what is left.

**A Claude tab does not come back on its own after a restart.** The
conversation ended with the container; the transcript did not, so the
project's Claude button offers to resume it and that stays a decision you
make. Enforcing it takes two halves: the saved layout drops Claude tabs at
boot, and, because a browser left open still holds its own copy, and a phone
waking up reloads the terminal iframe, which spawns whatever its URL names:
each Claude terminal's URL carries the run of the container it was opened in.
One from a previous run is refused where the session would have been created,
with a line saying to open it from the card instead. Shell tabs carry no such
marker and never needed one: a shell is safe to recreate in the same
directory, which is why it survives a restart and a conversation does not.

**A session can correct a plan, not just follow it**: `bb roadmap edit N`,
`bb roadmap step add|edit|rm|mv|done`, `bb roadmap mv N up|down`, which matters when the design moves under a plan
written a week ago. Every one of those lands in the history under `claude`,
so nothing gets quietly rewritten.

**The list reads top down, and the top is what matters most**: new items go
on the end, and the arrows in Reorder are how something gets promoted. Each
item wears its number: `R4` is the item's own name, not its position, so it is
what `bb roadmap done R4` takes, what a session means when it says "R4", and what
survives the list being rearranged. The R is the roadmap's letter and B is the
bug tracker's, so a number in a reply or a commit says which list it is from;
every verb takes the bare number too, and refuses the other tab's letter. The
prompt a session starts with carries the same names. Steps inside a group
number themselves 1, 2, 3 within it.
A gap in the numbers means something was removed; one out of sequence means
it was moved.

**Every line can carry details**, the technical half: which files, which
functions, the approach. They live under a "▸ details" fold on the row (the
words are the decision; this is the workings), travel with a step when it is
sent, and ride in the block a session starts with, so the session that works
the step does not start from a cold grep. Claude writes them with
`bb roadmap info N [M] "..."`, usually when it writes the plan; the pencil edits
them alongside the words.

**A group is one goal with an order to it.** Its title is that goal in plain
words ("make the picker usable on a phone") and the steps under it carry the
detail; the group folds like a bug's row, its title the heading and a tap on
it opening every step under it. Steps only exist because of one physical constraint: each is a message
*you* send by hand, one at a time, waiting on each. So a step is not a task,
it is a point at which the previous work has to have finished before the next
can start, and a session that splits work into more steps than that costs you
round trips for nothing. A step can be several lines, blank lines and all, so
the cheap unit is the line and the expensive one is the step. The briefing
every session gets says this in as many words.

**Items are handed to the session one at a time, by the arrow beside them.**
Sending types the line into the running Claude session and submits it, but
only if it can see that it arrived. There is no IPC into a session; the only
door is its terminal, and a session "waiting for input" is either at its prompt
or holding a permission dialog, which the title cannot tell apart. Answering a
permission dialog on your behalf, blind, is the worst thing anything here could
do, so instead of trying to recognize a dialog, it uses the one property every
text box has and no dialog does: **it echoes what you type**. Type the line,
look at the pane, and press Enter only if there is now one more of it on screen
than there was. If it did not appear, the line is left in the input box unsent
and the dashboard says so. With no session running, every arrow is dead.

A sent step is **struck through in place**, not removed, not reordered. Sent
is not done: a step can be handed over and quietly not carried out, and the
struck line is how you notice. It stays sendable, so "that did not take, do it
again" is one tap on the same arrow.

**Done is the session's mark, and it is a different one.** A session that
finishes a step says so with `bb roadmap step done N M`: the step it was
sent, or one it was told to go ahead with in chat, which used to have no mark
at all. The line is struck the same way but wears a tick instead of its
number, the frontier moves past it, and the log says a session finished it
and when. Only a session sets it, as with ticking off an item. Sending a done
step again is the override: the mark comes off, and the log shows the send
after the finish.

**The order that is protected is the order things are sent in**, and nothing
else. Only the frontier step of a group arms, and the group's own arrow stands
for that same step, so a plan cannot be handed over backwards, which is the
mistake that actually costs something: step three landing on a tree step two
was supposed to have made.

Editing is not constrained the same way, deliberately. The pencil rewords any
row, and the **bin is on every row**: item or step, anywhere in a plan, so a
stale step three does not cost you steps one and two to reach. A deletion
cannot send anything out of order. It can only make a plan shorter,
and it now says why it did, in a note kept with the entry in the history.
**The bin always asks; shelving never does**, because one is recoverable by
pressing the same button again and the other is not.

**And the panel keeps up by itself.** All four views now re-read when somebody
else writes: each carries a revision from the status poll, and a change to the
list, the memories or the tracker is picked up without anything being touched.
It is guarded rather than unconditional, and that guard is why two of them had
none for so long: the roadmap on screen may be carrying staged changes the
server has never seen, and the memory editor may be holding an hour of typing,
so a re-read waits until there is nothing to lose.

**A write that would go over somebody else's is refused, not applied.** Each
one says what it believes it is replacing: a roadmap field says the words it
read, a bug form the revision it opened over, a memory the digest of the bytes
it loaded, and if that is no longer what is stored, nothing is written. A
band says who moved it and when, shows what is stored beside what was typed,
and offers the two answers: **Keep theirs**, which drops the staged change, or
**Use mine**, which writes over what is there now. A memory has no "keep
theirs" (the version in the editor may be an hour of typing), so what is on
disk is shown to read and copy from, and the choice is to write over it or to
reload deliberately, with the loss said out loud.

The unit is different in each tab because what a write *replaces* is
different: one field of one roadmap item, a whole bug form, a whole memory
file. A roadmap item's check is per field on purpose: a session attaching
details while you reword the same line is two people doing two things, and
reporting that as a conflict would offer a choice between two things that do
not disagree.

`bb` is held to the same rule from the other side: a session that has not
re-read the roadmap since it moved is refused when it tries to reword, drop
or tick off an item, and told to run `bb roadmap` first. There is no
`--force`: re-reading is one command, and a flag would make the dishonest
path the shorter one.

**And a line says who else is in here**, under the view strip, so that most
collisions are seen rather than resolved: *Also open: your other window
(Roadmap)*, or somebody's name when the account is not yours. Both windows of
one account are the same account, so the account cannot be the answer: the
line is keyed on the browser tab, which is what lets it say *your other
window*. It rides on the same fifteen-second poll the panel already makes,
lives in the server's memory and nowhere else (a seat that survived a restart
would be a claim about somebody who is not there), and closing the notebook
says so rather than leaving the seat to time out.

Beside it, **when a session here last read the roadmap**, which is a
different claim from having been told. Being told rides in on the session's
next prompt; going to look is `bb roadmap`, and after changing something that
is the question worth answering.

Which is why **sending a step folds the two together**. Tapping an arrow
**arms** it: the arrow lights up and a **send box opens under that row**,
carrying the Send button and the two pickers below; tapping the arrow again
puts it down. Send then does four
things: the line goes, the step is crossed off, the panel closes and you land
in that session's tab. One tap for all four would be a mis-tap you could not
take back, and the highlight is the confirmation: a sentence restating the
line the arrow is sitting next to was not.

The box sits **under the line it would send**, not at the foot of the panel,
where on a phone it would be a screen away from the line it is asking about.

**A note can ride with it.** The box carries a field for anything to send
alongside ("the select is the one on the left") and it goes on the *same*
line as the step rather than as a second message, for the reason two messages
never work here: the second lands glued to the first. It is cleared once the
step has gone, where the pickers stay: a note belongs to the one thing it was
written for, and finding it still sitting there on the next step is how it
gets sent twice.

**Model and effort** are not questions in that box and are not applied by it.
They are the project's own setting, at the bottom of its **settings dialog**
(the gear on its row, which also gives the project a **color**: a bar down
the left of its row and its notebook tab, so several open notebooks tell
apart without reading each label), and `bb-tty` passes them as `--model` and `--effort`
when it starts a session there, so a session that is up is already on them
and a send is only ever the send.

**How much of what a session adds lands on its own** is the last row of the
same dialog: *Claude may* add to the roadmap, file bugs, add rules and fill
in build and test, each **auto**, **ask** or **deny**. Auto is today's behavior: an item, report or
rule a session adds lands at once, marked as its own. Ask holds it instead: the
session is told "held for approval as R12", the notebook shows a band above
its tabs with how many changes are waiting (and a count on each tab), the bell
carries a row per project that takes you there, and **Review** opens the
list: every held change with a checkbox and its full text under a fold, a
select-all box, and Approve and Deny at the foot. Approve replays the ticked
changes in the order they were made; Deny drops them and anything that rode
behind them (details or a step added to a held item, a note on a held
report). Deny refuses the add outright, with a sentence the session can quote
so it says the thing in its reply instead. It covers creation only: what is
already on a list a session may still tick, note and reword under every
setting, and the session is told on its next turn what you decided. The
settled ones are in `bb history` under *waiting*.

**Changing it while a session is running asks about that session.** Some
settings a session takes only when it starts: the model and effort, the
author it commits as, the projects it reads and the places it sees, its
node, and what its briefing says (replies, questions, how a test run meets
a change, how long captures are kept). Save with one of those changed while
your session is running and the dialog names the changes and puts two
answers in the foot: *Save and end it*, which ends the session so the next
press of Claude starts it on the new setting with the conversation resumed,
or *Save, keep it running*, which saves and leaves the session on what it
started with until you end it yourself. The setting lands either way;
only the interruption is asked about. Anything mid-turn is lost when it is
ended, which is the whole reason it asks. Everything else in the dialog
(the build and test commands, the dials, where tests run) is read when it
is used, so those save without a question. *Leave as is* passes no flag,
and claude uses its own default.

A group's own arrow **stands for its next step**: picking either lights both,
because they are one choice. A crossed-off line cannot be sent at all; put it
back first, so that struck-through means one thing rather than two.

The "I also changed the list" note rides on the *same message* as the step
rather than chasing it: two lines into one input box is how the second ends up
glued to the first. It rides on every send rather than being offered as a
choice: a session about to act on a step is exactly who wants to know the plan
around it moved, and by the time anything can be sent there is nothing unsaved
left to keep quiet about, which is the next rule.

The view opens the way the other three do: its one-line summary on the left
and **History** on the right, with the field, **Add** and **Reorder** together
on the row under it. Those three are the things that change the list; History
only reads it.

**Nothing can be sent while the panel is holding unsaved work.** The arrows go
down, and the line above the list says which change is not on disk and that
Save or Revert will clear it. The reason is what a step *is*: a line typed into
a session, which then goes and reads the list for itself. Send a step off a
list that exists only in this browser and the two are describing different
plans: the session is working from the file, and the file has never heard of
it.

**An item can be an ordered group of steps.** From a terminal that is
`bb roadmap add "rework the picker" --step "widen the select" --step "then
re-measure it"`; in the panel it is **+ step** under any item, which turns a
plain one into a plan, and the field stays open, so three steps is three lines
of typing rather than three dialogs. A step is **sent with the plan around
it**: "this is step 2 of 3 in a plan", the plan's own line, then the step,
because "then re-measure it" arriving on its own says nothing about what it is
for. Only the next unsent step can be sent; the one after it is dead until the
one before has gone, because three separate items can be handed over backwards
and the second then lands on a tree the first was supposed to have made.

**Reorder** is a mode rather than two more icons on every row: five controls
and a number do not fit a phone, and nobody rearranges a list at the same
moment they are sending from it. The toggle beside the hint swaps each row's
send/strike/bin for up and down: items move among items, steps move within
their group. A step that has gone is pinned and nothing moves above it, so the
crossed ones stay the block every other rule reads them as. The order on
screen is the order in the file; nothing is sorted on the way out, so a list
you arranged stays arranged and a ticked item fades where it is rather than
jumping to the bottom.

**Reordering is the one edit held back until Save.** Everything else here is a
decision (ticked, crossed, dropped) and is written the moment it is made, so
that a phone dying half way through tidying a list loses nothing. Arranging is
not a decision; it is something you are in the middle of. So the moves live in
the page until you save them, leaving the mode puts the order back, and closing
the panel on a half-done shuffle leaves the list alone. Both are asked about
first, since an arrangement is work.

**Every view keeps its history.** The roadmap's log came first; the bug
tracker and the memory view have the same button now, with the same bar:
search, a time window, a cap, and the same rows: what happened, to which
line, by whom, when. **By whom is the account, not just "you" or "claude"**:
those two say a person or a session, which was the whole answer while there
was one account, and with several on a project it does not say which of them
dropped an item. A session carries its account's name too, because a session
has an author: the person it was minted for. Entries written before this
carry no name and read as they did. The memory log records what the *notebook* changed
(wrote, edited, forgot): Claude's own memory writes are files, not events,
so they have no entry to make. For a session, `bb history --find X` is one
search across all three logs, merged by time and tagged by source; `bb roadmap
history` and `bb bug history` scope to one.

**Analysis** keeps a log too, and it is the odd one of the four: nothing here
writes a finding. The scan runs on the host, the container reads a report, and
between two runs a finding can simply stop being in it: fixed, or the file
went, or a rule changed upstream. The report cannot tell those apart and
neither does the log; what it says is *it was here on the 3rd and it is not
here now*, which had no answer at all before. So the entries are **derived**:
each read of the report is compared against the last, and the difference is
the entry: `found`, `gone`, or `changed` when the count or level moved.

Two things keep it honest. A finding is identified by **rule and path, not
line**, because line numbers move whenever anything is inserted above them and
a key including the line turns one edit into a gone-and-found pair for
everything below it. And **the first scan of a project seeds silently**: the
starting point rather than an entry, because stamping a discovery date on
findings older than the feature would be confidently wrong. A report that
fails to parse, or a reports directory that is not there this minute, is
skipped rather than read as "everything was fixed": that is the SARIF trap the
rest of this is careful about.

**Artifacts** is the fifth view: what the project has built, listed from its
`dist/` directory, and the convention is the feature. Build systems scatter
their outputs (gradle five directories deep, cargo into `target/`), and a tab
that went looking for all of those would be a catalog of build systems that
is wrong the week a new one arrives. So the deal is one word long: **what
ships goes in `dist/`**, a session that builds something copies it there, and
the tab lists `dist/` and nothing else. An empty tab on a project that builds
things means the copy step is missing, and it says so.

Each row is labeled by kind (apk, xpi, whatever the extension says) with
its size and age, newest first. Everything can be **downloaded**.

What a session looked with lands in `dist/` too: a reel's sheet under
`dist/reel/NAME` and an emulator shot under `dist/emu`, each with a record
of who asked and when (`bb capture`, R96). Those are not what ships, so the
list leaves them out and the tab draws them as one **Captures** fold, shut,
saying how many and how long they are kept; open, each row says whose it is
and offers Download and Remove. The recording and the full-size frames never
reach the share at all: they are working files on the node's own disk, at
the paths the reel's `frames.json` names.

They go by age and never by need. Nothing can tell whether a capture is done
with: two sessions on one project may each be reading a reel the other made,
and a session ending is not evidence that its reel is. So the project's
settings carry **Captures kept for N days** (7; 0 keeps them), the server
sweeps what is older on the read that draws the tab, a person removes one
from the fold, and a session lets one of its own go with `bb capture prune
NAME`, the same rule applied from the node.

A **script** is the one kind the extension cannot settle on its own: a shipped
shell installer is as often `dist/install` as `dist/install.sh`, so a file
whose extension the list does not know is asked for its first two bytes and a
shebang makes it a script. Those rows also offer **View**, which reads the
file over the panel the way a History opens, because a script is a thing
people read before they run it and a download is the end of that on a phone.
Nothing runs from the tab, and there is no control that would.

**The dev instance** heads the list, shaped like every other row in it: the
kind on a pill (`docker`, where a file says `apk` or `xpi`), the compose
project's own name in bold, and whether it is `(running)`, `(stopped)` or
`(down)` in parentheses after it, where a file carries its size and age. The
name is the compose project's rather than a container's: a compose file may
set `container_name` to anything it likes and may declare several, and this is
the one name that is always true of all of them.

Under it, and not behind a fold, are **what it publishes and what it mounts,
written the way Unraid's own Docker tab writes them**: container side
on the left, host side on the right, and the arrow saying which way it goes:
`/library ← /mnt/user/plex-media` for a read-only mount, `↔` for a writable
one, `7474:TCP ← 192.168.1.10:7475` for a published port. That is deliberately
not a second notation to learn; it is the one already used for every other
container on the box. All of it is read from the *resolved* compose config, so
a path or a port assembled out of variables shows as the value compose arrived
at rather than as the spelling, which is also how the checks below can judge
a mount without knowing anything about the variables that built it.

A running service gets **Open** beside its buttons. One published TCP port
links straight there, pointed at this page's own host; several open a chooser
listing every `host:port` for you to pick from. Unraid does not discover this
either: its tab reads a `WebUI` line somebody wrote into a template, or the
`net.unraid.docker.webui` label, so one port is the only case where it can be
known rather than asked, and asking beats guessing for the rest.

The mounts are not repeated in the warnings below. They are all on the row
already, with the path each one lands on, so naming the ones that reach past
the project restated what was two lines above in worse words. What the
warnings keep is the set that is invisible otherwise: `privileged`, added
capabilities, host devices, and the host's process or network namespace:
the flags that make a container more than a container. It appears when the project
carries a compose file
and the project's node is the [sandbox VM](sandbox-vm.md): a machine
whose only job is running Docker, which is what keeps all of this away from
the server's real containers: the project's compose app, built over there and
controlled in the file rows' own language. **Up** and **Down** are compose
against the project's own file, under a compose project named for the
instance. **Env** edits the
instance's env file: kept in `/config/devenv/`, never in the repo, handed to
compose as `--env-file`; Up stays dead while the repo's `.env.example`
declares keys the env does not answer, because starting a service against an
env known to be missing is a crash with extra steps. **Rebuild** un-ghosts
when the code has moved since the last build (a new commit, or a dirty tree)
and runs build → down → up, unless the rebuild finds new settings in
`.env.example`, where it stops after down, rewrites the env as the new
example with the old values preserved in comments, and leaves Up for the
operator. Before the first build the button reads
**Build**, and nothing is built until it is pressed.
**Build from** picks the branch it is built from. A project's tree is shared, one checkout for every session and person on it, so this does not switch it:
the build comes from a git worktree of that branch beside the project, marked
with a `.bbignore` so the projects list knows what it is, and the project's own
checkout is left where it is. The row then says which branch it was built from,
and "the code has moved" means that branch has, not the working copy. **Send to
Docker manager** offers the same picker, because a second instance is usually a
second branch: a pull request running beside the one that is up.

Two instances of one project are the same compose file, so they publish the
same host ports and the second cannot start as written. That is said **before**
the press: the row names the port and what already has it, read off the
container list the tab already has, and the answer is the per-instance env
file, which is where a compose written with `${PORT}` takes its ports from. A
compose that hard-codes them has no answer but a sentence. A compose that
references `${BB_DEV_DATA}/...` gets its volumes on the cache drive by
convention, in a per-instance directory the VM makes itself, so that share is
mounted over there and needs no mount here at all. By the same convention a
build sees `BB_BUILD_REV`, `BB_BUILD_AT` and `BB_BUILD_VERSION`: the commit
it is from, when, and the project's version in file form, for a compose whose
build args want a stamp (BuilderBot's own passes them to its Dockerfile). BuilderBot itself gets the
row too, as a second container on another machine, never the one you are
using; expect
`up` to refuse while the real one holds the same host ports, which is the env
file's job to change.

**The daemon's filesystem is not this container's**, and that is the one thing
about a remote daemon easy to forget and impossible to see: a bind mount's
*source* is resolved by whoever runs the container, which is the host.
`/workspace/alpha` and `/devdata/alpha` mean something here and nothing
over there, and docker answers a missing bind source by creating an empty
directory and mounting that, so on Unraid, whose root filesystem is RAM, the
result is an app that starts with no data and loses it again at reboot. It
reads as a bug in the app. The node's path mapping states it once: the
same one you made when you mounted the volumes, and BuilderBot both hands
over host paths (that is what `BB_DEV_DATA` now carries) and names any of a
compose file's *own* paths the host will not find, on the row, before you
press Up. Absolute host paths, which is what a working compose here already
writes, are unaffected. Build contexts are unaffected too: the classic builder
streams those from this side.

**Bind directories are made before anything starts**, as a step of Up and
Rebuild rather than a button somebody has to remember. A compose file names
directories that have to exist, and docker creates a missing bind source
itself (as root, then chowning it) which on a share that squashes root fails
and takes the whole run down with *operation not permitted*, leaving the
directory behind so the second press works: an intermittent-looking failure
with a fixed cause. So they are made first, owned by whoever BuilderBot runs
as, which is the ownership Unraid expects.

Made on whichever side can reach them, which is not something to think about:
a share this container mounts is a local `mkdir`, and anything else is a
one-shot container on the VM: the same mechanism that makes the per-instance
dev-data directory, running as BuilderBot's uid, which is the whole point
since docker's own attempt is as root. Which shares the VM has is the VM's
business: nothing is declared on this side, so a share added over there next
month needs no BuilderBot setting touched.

The one thing it will not create is a bind at a share root itself; there is
nothing below it to make, and docker creating the root is the as-root failure
this exists to avoid. The guard still holds the shape: the argv is rebuilt and
compared whole, the mount must be a single plain-named share root, and every
path in it is plain names only, so the reach stays a `mkdir -p` as an ordinary
user on a machine built to be wrecked.

`mkdir -p` throughout, so one that already exists is left alone and starting
twice does the same thing once. A directory made over there cannot be seen
from here afterwards, so what was made is recorded against the instance. What
could not be made is written into the job log and the compose runs anyway;
letting compose say what actually went wrong beats refusing on this side's
reading of a file compose is about to read for itself.

**A path this container also mounts needs a pair, even on a sandbox VM.**
`/workspace:/workspace` covers the projects share and nothing else. If you also
map the dev-data share here, so you can create a compose file's bind
directories from a shell, which is the usual reason to, then a compose
mounting `/devdata/...` is naming a path BuilderBot has, and it will say so
until the mapping answers for it. `/devdata:/devdata` is that answer when both
machines mount the same share at the same path, which is the arrangement the
sandbox is for. The alternative is to not map it here at all: what BuilderBot
cannot see, it does not check.

**Container names and project names are separate groups.** A project existing
reserves nothing: a container may be called `mediareducer-dev` while a project
is too, because they are not the same kind of thing. The one name that cannot
be reused is another *container's*: two instances resolving to one compose
project name would be one set of containers, one env file and one data
directory with two rows driving them, so the second is refused and told which
instance has it. A project's *default* instance is named for the project,
since nobody typed a name for it.

**Which project a container belongs to is tracked separately**, and is never
read out of its name; it is the key it is stored under. That is what decides
whose Claude session may touch it, so a project can stand up several
containers, name them anything, and still own all of them.

Which compose projects on the daemon are **this dashboard's** is answered the
same way, from what it has stored, not from what things are called. So the
manager can list every container on the VM, including ones you started by
hand, and still be right about which of them it is driving.

An `.apk` can be **installed** on the paired phone. `adb install -r` replaces
an existing copy in place and keeps its data, so install and update are one
verb and there is no second button. Two failures are common enough to be
turned into sentences rather than passed through: a **signature clash** (the
copy on the phone was signed with a different key: a release build, or one
from the Play Store, against a debug build from here) says to uninstall it on
the phone first, and notes that this takes the app's data with it, because
that is the operator's call to make on the handset rather than something to do
on their behalf. A **version downgrade** says so plainly; `-d` would allow it
but only for debuggable packages, and passing it always would quietly turn a
mistaken downgrade into a successful one. Neither `-g` nor `-t` is passed
either: granting every runtime permission, or allowing test-only packages,
makes the install behave unlike the one a real user would get, which is the
opposite of what testing on a real handset is for.

An `.xpi`
can instead be **pushed** to the paired phone, which unpacks it and hands the
directory to `web-ext` for a **temporary** install (gone when Firefox
restarts). Two rules keep the push honest. **Nothing auto-pushes**: web-ext's
file-watcher is disabled and what is pushed is a snapshot, so a push is a
decision made each time, and pushing the **identical build** into a live
session is said rather than done, since it would install nothing. Stop the
session and the same file becomes pushable again, because after a stop (or a
Firefox restart) that is a legitimate thing to want. No History button,
deliberately: the files' own timestamps are the history, and a log of "the
file changed" would restate the mtime column.

**Analysis** is the notebook's fourth view: the scanner's findings for that
project alone, worst level first, read-only: the scan runs on the host, and
`bb findings` reads the same digest in a terminal, and the Tools card's
**Static analysis** button opens the whole report as the Analysis tab, with a
project selector and the same filter bar. Findings whose paths
resolve into anything other than a **valid** project: one that is listed and
free of error-level issues; a locked one still counts: are set aside rather
than shown as "unattributed". The label is reserved for paths that genuinely
place nowhere, which is the case worth a look.

That rule is a subtraction, and deliberately so: rather than recognizing each
kind of thing that is not a project, findings attribute only to the projects
worth reading them for, and everything else in the share falls out together.
It matters because of how the toolchain store is mapped here, beside the projects
folder in the same development share, so the host's scanner walks it like
anything else and one report grew nine thousand findings for a pile of
downloaded toolchains.

**The row names what it could not place**, commonest first: `file:/src × 9`,
which is mobsfscan reporting its own container path. A bare count said
something was wrong and nothing about what, which is how it sat in the
hundreds through several passes when 267 of them were one share and 9 were a
scanner's configuration. A
marker file (`.bbignore`) handles the case where the container knows about the
directory, but a share mapped in with nothing to mark it is still listed as a
project (one with an error, because it is not a repository), so subtracting
only the *listed* names would have left it in play. Subtracting the valid ones
catches both, and needs no excludes configured on the scanner.

**The test registry** is the notebook's sixth view, and `bb tests` in a
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
workers** in the Sessions section of its row on the Nodes tab, 0 for the
machine's cores, handed to every test job there as `BB_TEST_WORKERS` for
the project's own test command to read (`pytest -n`, `--test-concurrency`,
`--max-workers`) and read by this harness to run its suites across that
many workers at once (roadmap R81).

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

**The bug tracker** is the notebook's third view, and `bb bug` in a terminal.
The roadmap is for things somebody decided to build; a bug is a different
record; it has a severity, a place it lives, a way to make it happen, and a
gap between expected and actual, which are exactly its fields, plus a notes
field the analysis accumulates in (`bb bug note N "..."` appends, dated,
rather than replacing: the last analysis is how the next one starts). Either
side writes it: you report from the tab, a session files what it trips over
with `bb bug add "..." --sev high --area "..." --repro "..."`. It is
write-through, not staged: a report is a form submitted once. Each report
is stamped with the project's version as `bb version` prints it, on filing
(*in 0.4.0-dev.390+e1615f5* on the row) and again on closing (*closed in*),
plus the image the container was running when it was filed; a report that
predates the stamp stays blank rather than being backfilled with a guess.
Closing a bug that is already closed is refused: reopen it first, so the
log says the earlier answer was withdrawn. A bug **closes**
three ways, and the difference is what the next reader is told: **fixed**
(somebody fixed it), **won't fix** (a decision to leave it), and **not
applicable** (it was real and stopped applying, because the feature it was
about went away: neither of the other two is true of that). Each asks for
the note that is the point of closing, and `bb bug all` still lists it,
because a closed bug is the record that stops the same report being chased
twice.

**Delete** is separate and narrower: for a report that should never have
existed: mis-filed, duplicated, aimed at the wrong project. It takes the row
and leaves the reason in the log. The briefing tells sessions that this is
the only case for it; anything that was a real bug gets closed.

**Send to Claude** hands one bug to the session running there, from the same
box the roadmap opens under a step: the same note field for anything to send
with it, opened under the report instead. Nothing is switched on the way in:
the session is already running on the project's own model and effort.

**A closed bug cannot be sent**: reopen it first. A closed bug is a record
rather than work, and the three closes exist to say which kind of dealt-with
it was; handing one over asks a session to deal with something somebody has
already decided is done. If a fix did not take, `reopen` is the honest way
back, and it leaves a line in the log where sending it again would leave
none. The button goes dead on the row and says so, and the server refuses it
independently: a rule only the panel honors is a suggestion, and this one is
reachable over the API.

Sending is **written into the tracker's log** as `sent`, because "was this
ever handed to a session, and when?" is a tracker question. It is not a status
change: sent is not fixed, and the bug stays open until somebody closes it.

The list **sorts** by severity, newest, oldest, recently changed or title,
from the same bar shape the log's filters use. Open before closed is not one
of the choices (a tracker is read to find what is outstanding), so every
order works within that. Open bugs ride into every session's starting prompt by number,
severity and title, with the fields on disk behind `bb bug show N`.

**Editing the list or the memories tells the running session**, in one line, to
go and read them and carry on, not to drop what it is doing. A list edited
under a conversation is a list that conversation is holding a stale copy of.

**The open items go in front of every Claude session the dashboard starts.**
`bb-tty` appends them to the session's system prompt, so a note left on Tuesday
is read on Thursday without anybody remembering to mention it. Items a session
added are marked, so you can see what it put there. It is given as context
rather than instructions: a session works an item when you ask, or when it is
plainly part of what you asked, and adds one when it notices something out of
scope for what it is on. A step that is done is counted and not printed: the
plan's past is a `bb roadmap show` away. The block travels to the session in a
file rather than on tmux's command line, which takes at most 16KB and answers a
longer one with `command too long` and nothing else.

**What is kept and what a session is sent are two things.** A project only
grows, and every conversation pays for the block. So the notebook keeps what
there is (two hundred open roadmap items, the parked ones not counted; two
hundred open bugs; forty standing rules and two hundred named ones), and the
block is an index into it. Each part that grows has a share of a session's
prompt: 16 KB for the rules, 16 KB for the roadmap, 8 KB for the bugs. A part
over its share says less per row before it leaves a row out. The roadmap gives
its items with their open steps, then their titles with the steps as a count,
then the titles cut short with the parked ones as a count, then as many as fit
in your own order with the rest as a count. The tracker gives every title,
then the titles cut short, then as many as fit, the worst first, with the rest
counted by severity. The rules keep every standing rule whole, since that is
what a session is held to, and give the named ones without what calls for
each. What a part left out is said in the part, where the session reading it
sees it, with the verb that prints all of it; and every part is always there,
whatever the others hold.

**And you can read the whole of it.** The Briefing tab's last fold, *What a
session is sent*, holds the exact string a session started here is handed: the
house rules, then the open roadmap, then the open bugs, with its size on the
heading and each part's size under it against its share, so a part that has
started saying less is seen there before a session meets it. It is the same string, not a rendering
of the same idea: the tab and `bb-tty` both ask `bb preamble` for it, so the
fold cannot quietly stop describing what sessions get. Shut by default, since
it is a thing to check rather than to read every time.

Two settings shape that string without touching what you read in the
notebook. Each person's **Replies** pick on a project, beside model and
effort, says how wordy Claude's replies to them are there, and their
**Questions** pick how often Claude asks them, more, fewer or rarely; both
ride the block as its own part and
govern the replies and the asks only, so the notebook, commits and files are
written as ever.

A running session keeps the block it started with. What it hears live: a
named rule on the turn it applies, whatever a `bb` verb answers, and, on
its next prompt after the controller was rebuilt to another build, one line
saying so and pointing at `bb catchup` and `bb preamble`, once per build.

- **Ending a session for good is the ✕ in the Sessions list**, under the
  terminal. That one asks,
  because that is where something is actually lost: the shell and everything
  in it, or the Claude conversation (its transcript is kept and can be resumed).
- **Switching between terminals is instant**, because a pane keeps the last
  three of them loaded behind the one on screen. Rebuilding the pane instead
  would throw the frame away, and the terminal is 700KB of JavaScript that
  then has to parse, open a websocket, attach to tmux and draw: a second and
  a half of blank pane on a phone, every switch. The frames sit exactly on top
  of one another at the same size, which is not just tidiness: a hidden frame
  is still an attached tmux client, and tmux sizes a window to its smallest
  one, so different geometry would mean the terminals fighting over the width.
  The fourth reloads: the ceiling is there because each
  one is a live xterm and its own socket, the same reasoning as the tab cap.
  Killing a session also closes its tab, whichever tab that is: a tab left
  pointing at a dead session would only offer to recreate it.
- **Tabs are named for where they are.** A terminal reads `sh: <directory>`,
  following the shell as it `cd`s; hover for the full path. A Claude tab reads
  `Claude: <project>`. Two terminals in the same directory carry their number
  so they stay distinguishable.
- **Drag a tab** by its label to reorder the strip. With a finger, hold for
  half a second first: the tab dims to say it is picked up; a finger that
  moves sooner is swiping, and on a phone that swipe scrolls the strip.
- **⇱ on a tab** pins it to the **left** or **right** pane, which splits the
  view. Once split, each tab on screen carries ◧ or ◨ for the pane it is in,
  and clicking into either terminal makes its pane the active one: the one
  the keys and the commands go to.
- **✕ on a pane** collapses back to a single pane. It does **not** close the
  tab or touch its session: the tab owns the session, the pane is only where
  it was being shown.
- **On a phone** there is no split: the pin buttons are hidden and only the
  active pane is shown: a split made at the desk is still there when you get
  back to it. The strip stays one row: swipe it, or page it with the **‹ ›**
  arrows (grayed at the end you cannot page past): instead of wrapping, so
  the terminal keeps its screen space; a tab you open is scrolled into view.
  Under the terminal sit **Keys**, **Commands** and **Sessions**. Keys is the
  phone's alone: a desktop has a keyboard, so it carries no on-screen one at
  all. One flyout at a time on a phone, because there is not the height for
  two, and a flyout that has done its job gets out of the way: picking a
  session or sending a command closes it. Which of the two
  views, Dashboard or Terminal, a phone was on is remembered across a reload,
  and while the dashboard is in front the **Terminal** switch carries the
  worst Claude state: amber if a session is waiting on you, blue if they are
  all working: as does each project's Claude button.

Every terminal runs inside **tmux**, so a dropped connection, a closed laptop
or a reloaded page detaches instead of killing the session. Coming back to a
backgrounded page reconnects **the terminal you are looking at**: the three
kept alive behind it reconnect when you switch to them, because reloading all
of them at once is several hundred kilobytes of terminal emulator apiece and a
phone spent its first seconds back doing exactly that. The **Sessions
card** is the full list: every terminal and every Claude session, named the way
the tabs are (`sh: <directory>`, `Claude: <project>`), including the ones you
minimized; the tmux name and full path are on hover. Document tabs are not
there, having nothing to keep.

**Selecting in a shell copies it.** Release the mouse and the selection is on
your system clipboard. That is why tmux's mouse mode is off in shell sessions:
with it on, tmux takes the drag and the text only ever reaches a tmux paste
buffer. The trade is that the wheel no longer scrolls tmux's scrollback there;
at a prompt it walks shell history instead. **Claude tabs keep mouse mode** and
so do not copy on select; its interface wants the mouse more than the
clipboard, and the wheel scrolls its output.

**Scrolling back is PgUp.** At a prompt, PgUp enters tmux copy mode a page up
and PgDn pages forward; copy mode ends by itself the moment you are back at
the bottom, so there is nothing to remember (`Ctrl-b [` still works, and `q`
still leaves). Inside a full-screen program the key is the program's. That is
also how a **phone** scrolls, with the PgUp/PgDn keys in the ⌨ Keys row: a
finger drag in the terminal reaches nothing, because tmux holds the alternate
screen and the browser terminal only turns wheel events into something tmux
can see, in either kind of tab.

The launcher sets this on the session as it starts one, not only in the config
file, because `~/.tmux.conf` lives on the persistent home and is yours.
Because the setting is applied per session, a `set -g mouse on` in your own
config does not override it: turn it back on where you want it with
`Ctrl-b : set mouse on`.

**Right-click gives you one menu, the browser's.** tmux draws its own context
menu inside the terminal, and the browser's lands on top of it: two menus for
one click, only one of them dismissable. The browser's cannot be suppressed
from outside the frame (the terminal is served from its own port), so tmux's is
unbound. **Alt+right-click** still opens it if you want *Copy Line* and the
pane commands.

**The tab strip is shared, not per-browser.** It lives on the container, so
opening the dashboard on a phone shows what the desktop has open, and a change
on either reaches the other within a poll. The tab cap on the Settings tab
(default 12) limits how many can be open at once: each terminal tab is an iframe running a
full terminal emulator over its own websocket, so the limit is about browser
memory, not tidiness.

**Terminals survive a container restart, scrollback and all.** tmux dies with
the container, so on the way down the supervisor writes each terminal's
directory and the last 2000 lines of its screen to
`/config/sessions/`, and a startup hook recreates them there and prints that
scrollback back in before the shell starts. Minimized terminals come back the
same way, since they are sessions like any other.

What comes back is the terminal, not what was running in it. A build that was
halfway through went down with the container: restarting it here would be a
promise this cannot keep, and the shutdown kills whatever was running before it
takes the sessions' picture. Sessions are single-pane by construction; if you
split one inside tmux, only the active pane's contents are kept.

**Claude sessions do not come back.** The conversation ended with the container,
and a session wearing its old name would be a new one pretending otherwise. Its
tab is dropped at boot too, and the project's **Claude** button offers to resume
the transcript, which is still on disk.

### Commands run in the terminal

They live under the terminal rather than in the sidebar, at every width:
**Commands** and **Sessions** in the bar below the panes, opening a flyout
over the terminal they act on. On a desktop it really is *over*: the panel is
an overlay and the terminal keeps its height, because a resize costs a terminal
a refit and a reflow of everything on screen, which is a lot to charge for
looking at a list. A phone pushes the terminal up for it instead, there being
no screen to spare for covering one thing with another. Both slide. That is where they belong: a command list is
about the shell in front of you, not about the box, and it is also what keeps
the sidebar to five cards you can read instead of twelve you scroll past. On
a wide screen the buttons sit at the bar's left edge and the flyout is capped
rather than stretched: a short list read across two thousand pixels is worse
than one read in a column.

Nothing about the graying-out below depends on where they live. It is computed
from the *active pane*, which is why the same markup served the phone's bar
and the desktop's cards for as long as it did.

The `bb` commands worth a button are buttons. Clicking one clears whatever is half-typed at
the prompt, types the command into the terminal you are looking at and presses
Enter, rather than reporting into a box of its own. The
output is then somewhere you can scroll it, a slow one like `bb toolchains install` is
watchable while it runs, and one that asks a question (`bb login`) or follows
(`bb logs -f`) behaves exactly as if you had typed it. A command only ever goes
to the tab you are looking at, and only if that is a plain shell: with a
**Claude** tab in front (it would submit the command as a prompt), a document,
or no tab at all, every command button is grayed out and its hover text says
where to go: never quietly typed into some other terminal.

The line is cleared with end-of-line then kill-line, which is readline editing
rather than a signal: `Ctrl-C` would also interrupt whatever is running in that
terminal, which is not something a button labeled `bb status` should be able to
do.

They are listed in `bb help`'s own order, so the card and the CLI read the
same. If the list outgrows its space it is cut off at eight with a **Show all**
button after the cut. The **thumbtack** on each command keeps it above that
cut: pinning moves a command up, it does not re-sort it into an order the CLI
never uses. Pins live in `/config/pinned-commands.json`: one machine, one
operator, so a pin made at the desk is there on the phone.

What is *not* there is most of `bb`, on purpose. Nothing that needs an argument
(`bb capture shot URL`): a button is never a half-written command line. Nothing a card
already does better: the Projects card lists projects and offers the CLAUDE.md
fixes on each row, the Doctor card runs doctor, the findings report beats
`bb findings`, and the Runner card has the runner's own controls. And nothing
that only means anything from a checkout of the BuilderBot repo (`bb drift`,
`bb dashboard dev`); those are for sessions developing the container. What is
left is what an operator actually reaches for from a terminal: status, update,
login, the emulator, lint, and the logs.

Two more lists flank the `bb` one in the same flyout, following the same
rules. **Linux commands** is the general toolkit: `ls -lah`, disk usage here and per mount,
memory, the biggest processes, listening ports: live on any shell tab. **Git
& GitHub** shows its commands verbatim (`git status`, log, diff, branches,
fetch, pull; `gh pr list`, `gh run list`, …) and ghosts against the directory
the active shell is *in*, not just whether it is a shell: outside a git
repository the whole list grays out, and in a repository whose remotes do not
include GitHub, just the `gh` half does: the hover text says which it is.
The verdict follows a `cd` on the next status poll, and the ghosting only
reflects the repo; `gh` itself still needs its own auth (`gh auth login`
in a shell) to answer.

### Your own commands

**Custom commands**, the last section of the same flyout, starts empty with a **+**. It takes a title and a
box of command lines, and the button it makes types those lines into the
terminal you are looking at, in order, exactly as if you had typed them: one
line or twenty. The pencil beside each one edits or deletes it.

Long titles are cut with an ellipsis so the list keeps its shape; hovering shows
the full title *and* the commands it will run, which is the thing you will want
six months later. They live in `/config/custom-commands.json`, so they survive
restarts and image updates and are the same on every device.

This is the one place the dashboard sends text you wrote rather than a name from
a fixed list, and it is still not a remote-execution API. The lines are stored
by one authenticated request and typed by another into a tty that the same
operator is already sitting at with a full shell. Nothing is executed in the
dashboard's own process.

### A phone, and asking before touching it

The container carries no adb and holds no phone. A handset is driven from a
**node** (whichever one has adb in its toolchain store), and that node's
**Phone** section on the Nodes tab pairs and connects it over Android's
wireless debugging and lists what a session is waiting to do there.
Several nodes can each hold their own phone; a project's sessions reach the
phone on the project's node and no other.

**Open the dashboard on the phone and the IP is already there.** The address
the field exists to capture is the client address of that very request, and
Docker's bridge does not masquerade it, so browsing from the handset fills it
in and says "this device". Only for an Android browser: from a desktop the
client address is the desktop's, which is not the phone, and filling it in
would be a confident wrong answer. The port and the six-digit code still come
off the phone's own screen; nothing but the phone knows those.

**Pairing is once per node, and it outlives a restart**: the key the phone
trusts is in the node account's `~/.android`. Which matters because pairing
has a trap in it: **Android cancels the pairing dialog the moment you
navigate away from it**, taking its port with it. Pairing from the browser
*on the phone you are pairing* therefore cannot work, by the time you paste
the code, the port it belonged to is gone. The tab notices that case and
says so, and says the thing worth saying first: try Connect, you are probably
already paired.

**A phone it has met is remembered.** Every pairing and every connection
puts the handset on the node's remembered list on the Phone tab: its
model, its address, when it was last seen, and Connect on that row is the
whole reconnect: the address goes back in the field and the node finds the
port. Forget drops the row and nothing else; the pairing key stays on the
node, so the phone can be connected again by typing its address.

**You give it an IP, not a port.** Android hands out a new one every time
wireless debugging is toggled, so a remembered port goes stale, and the port
on the pairing screen is a different number from the one on the main screen
anyway. The node scans for it, on its own network.

**A connection has one owner.** The account that connects a phone is the
only one that can disconnect it; everybody else sees the connection with
its controls grayed and the owner named. Every command a session asks for
goes to that account (on the Phone tab and in their bell, nobody else's),
because the phone is on their desk and they are the one who said yes to it.

**A session never touches the phone itself.** It is kept on an adb server of
its own on the node, so a plain `adb devices` in a session shows the emulator
and nothing else. To reach the handset a session runs `bb phone run --why
"..." -- …`, which puts the reason and the exact command in front of the
phone's owner and waits; on **Allow** the node runs it and hands back the
output. The reason is required, not optional: approving a command you did
not write, with no sentence saying what it is for, is a guess.

**Lent to a project, a phone is driven without asking, and only for that
project's app.** Its owner lends it from the project's row to one project on its
node, for an hour, four hours or until taken back. That project's sessions
then install one of its own builds (`bb phone install dist/APP.apk`, whose
package the lease learns), start, stop or pick it as the keyboard, read its
logcat, take screenshots and recordings into `dist/phone/`, read the
screen's layout, and tap, swipe, glide and type, the last two only while one
of the lease's apps is in front or is the keyboard. Everything else, another
app, Settings, a shell, still goes through `bb phone run --why`. The section
shows the lease, the newest screenshot a session took (it updates on the
next poll as a session works), Look now and Take back; a lease also ends
when its time is up or the phone disconnects. All of it is adb from the node,
nothing on the phone's side, so the companion app gains no permission for it
and looks to Play Protect as it did.

**The companion app connects the phone it runs on.** Its *This phone*
screen (under More) picks the node and the address the node reaches the
phone on, its VPN address first when a VPN is up, and offers Open Developer
options, Connect and Pair. Pair waits for Android's *Pair device with
pairing code* screen to announce its port on the phone's own network,
then posts a notification whose reply box takes the six digits over that
screen, since leaving it cancels it; the controller pairs the node and
connects it on the port debugging announces. The same screen lends the
phone to a project and takes it back. Android still wants Wireless
debugging switched on by hand: no app can read the code or turn it on. Over a VPN it is the same: pair and
connect by the phone's VPN address, and the node finds the port; Android
still wants the phone on Wi-Fi for wireless debugging.

**Root on a node has the same shape.** A session has no sudo there and gets
none; what it can do is `bb root run --why "..." -- CMD`, which puts the
reason and the exact command in front of a person, on the Nodes tab and the
bell, and waits. Which person is decided by the session that asks: the
account it belongs to, when that account is an administrator, and every
administrator when it is a user's, because a sandbox is a shared machine and
root on it is not a user's to allow. (Their own phone is: a phone request
goes to whoever connected the handset, which is the asker when it is theirs.
Letting a particular user allow root on a particular sandbox is a
permissions design of its own, not written yet.) Allow runs that one command as root on the
project's node, as a system job whose log opens with the reason and who
allowed it, so the Jobs tab is the record; Deny says no. Only a node
provisioned as a sandbox takes it: somebody's own machine is not the
controller's to run root on, and there is no fake sudo either: a refusal
that says why beats a success that did not happen.

**Installing an APK and pushing an extension** from the Artifacts tab go
the same way: the file is fetched onto the project's node and installed on
the phone there, or handed to web-ext there for a temporary add-on that
stays live until Stop. Both buttons are the connection owner's: anybody
else sees them ghosted with the owner named, and a push also needs web-ext
on that node, which the button says when it is missing.

### How a view knows to re-read

Every view shows facts it does not own. The roadmap's arrows depend on a Claude
session existing; the Artifacts tab's Install depends on a phone being
connected on a node; the Phone tab's questions arrive from a terminal. In
one week, four of them went stale in exactly the same way: each had invented
its own rule for when to re-read, out of knowledge it did not have. The worst
was self-defeating: the phone view polled only while it already knew of a
pending request, so it could never discover the first one.

So no view decides that any more. `/api/revs` returns one token per thing that
can change, a view registers what it depends on, and it is told:

```js
onRev("phone.asks", () => phFetch());
onRev(() => `dist:${project}`, () => loadArtifacts());
```

**The notebook is on the same clock.** Its halves: the roadmap, the memories,
the rules, the approval queue, the test registry, and the controller's own
settings: each carry a revision here too, so a change made in another window
or by a session shows up on the tab you are looking at within a second or two
rather than at the fifteen-second status poll. A view re-reads only when it is
not in the middle of something: a half with an unsaved edit, a staged change
or a write in flight is left alone until it settles, because a poll that
overwrites what somebody is typing is worse than a stale line.

The endpoint is **deliberately tiny**: file mtimes and in-memory counters, no
git, no tmux, no adb, which is what makes it affordable at a second and a
half, where `/api/status` runs git for every project and is affordable at
fifteen. The one thing that is not free, the set of attached devices, is
cached with a floor of a few seconds and refreshed at once when the dashboard
itself connects or disconnects, so pressing Connect is instant rather than up
to that floor late.

**A hidden tab slows down; it does not stop.** That distinction is the point:
a request lands while you are looking at something else, which is the ordinary
case rather than the exception. The poll drops to thirty seconds when the tab
is hidden (browsers throttle background timers hard anyway) and the tab
re-reads *immediately* on becoming visible, so coming back to it is never
looking at a stale page. A pending request also puts a count in the **tab
title** and a dot on the **favicon**, which is as far as a page can go without
asking for notification permission; that is a decision about your browser
rather than about the dashboard, so it is not taken on your behalf.

### Reading CI from inside the container

A self-hosted runner streams a job's console output to GitHub and keeps none
of it, and with no git token here there is no API to ask either, so *"CI is
red, why?"* had no answer in here. Every runner is on a node now, which moves
the log one machine further away and changes nothing about the answer.

So the lint workflow archives its own output, and so does the `dashboard
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

### Catching up after time away

Two things are recorded for no other reason than that a later session will
want them, and neither can be reconstructed afterwards.

The first is which images this container has actually run. It is recreated on
every update, so its own stamp answers only *what is running now*, the boot log
rotates away after a few starts, and with no PAT there is no registry to ask,
which leaves *"which build was the box on when I saw that?"* unanswerable, and
that is the first question whenever a fix appears not to have landed. So the
entrypoint appends a line to `/config/image-log.tsv` whenever the stamp differs
from the last one: first-seen, commit, version, build time. A restart writes
nothing; a rollback writes a line, which is the point.

The second is `bb catchup`, which reads both of those plus git and the
notebook's own logs and prints one screen: the image this box is running and
how far behind `origin/main` it is, recent commits **with the first line of
each body** (the line that says *why*, which `--oneline` throws away) what
moved in the roadmap and the tracker, and the builds archived above.

### Keeping a session in its own project

A Claude session started from the dashboard is launched with a generated
settings file that denies its file tools; `Read`, `Edit`, `Write` and
`NotebookEdit`, since a deny rule names one tool and Read does not imply the
rest: access to every *other* project under `/workspace`. Siblings are
enumerated by name rather than matched by
pattern, so a project called `app[1]` cannot quietly take its neighbors out of
the list. That file is passed with
`--settings`, which ranks as a command-line argument: above the project's own
`.claude/settings.json` and `.claude/settings.local.json`, so a session cannot
widen its own boundary by editing files in the repo it is working on. Only the
root-owned managed policy file outranks it.

**On its own this is a guardrail, not a sandbox.** It stops a session wandering
into the wrong tree by mistake, which is the common failure, and Bash is not
under it.

**The hard boundary is the session's view (roadmap R35).** Every session on a
node runs as one account and the node holds every project bound to it, so file
permissions cannot keep projects apart. On a Linux node provisioned as a
sandbox, a project's Claude session and its project shells start inside a
mount, PID and IPC namespace built by `nodes/bb-session`, a root helper that
is the session account's one sudo rule. Inside it `/workspace` holds only the
project, its worktrees and the account's Claude share (other projects'
transcripts are empty); the account's home is the only home and its
BuilderBot cache keeps only this project's folder; `/tmp`, `/var/tmp` and
`/dev/shm` are the session's own; the agent's stores keep only the
emulator's logs and the project's own CI logs and artifacts; the toolchain
store is read-only, so nothing a session writes can reach
a command another account or a job runs (Flutter's own tree is the one
exception, since it writes there on every run, with its `bin` still
read-only); and the process list and tmux server of other sessions are out of
reach.

The view is built from what a session is given, not from a list of what to
hide. At the top of the machine the system's own directories stay (`/usr`,
`/etc`, `/var`, `/opt`, `/home` and the rest), and everything else there is
out: a directory that holds one of the view's own places (the toolchain
store under `/mnt`, say) is covered and that place put back inside it, and
one that holds none is hidden whole, with the mounts inside either let go so
the mount table names no export. The agent's own directory
(`/var/lib/builderbot`) is covered the same way, so other projects' build
caches, their containers' data and the agent's tools are not there. The
base home, which belongs to the account every session runs as, is new in
the view and holds what a session runs from it, read-only: the launchers on
its `PATH` and Claude Code. Its keys, history and settings are not there. So
a share mounted on the node next month is out of every view without anybody
naming it. A share a project works with is named in the project's settings
(**Also sees**, a path on the node, set by whoever may set the project's
node); it is handed to the helper as `--sees` and put back as the node has
it. The helper refuses one that names the system's own, the projects share,
a home or the agent's stores, so the setting cannot bring back what the view
leaves out on purpose. Two things are known to show through: the names of
the account's own other projects, as empty folders under
`~/.claude/projects`, and a share mounted under one of the system's own
directories, which is left as the node has it.

Each account on a node keeps its own tool caches and dotfiles
(`.gradle`, `.m2`, `.npm`, `.cache`, the Rust crate cache and the rest)
rather than sharing the base home's, so a person's first build on a node
downloads its own dependencies. Java tools take their home from the session
user rather than `$HOME`, so a session points Gradle, the Android tools and
the Kotlin compile daemon at the account's home by the variables they read
(`GRADLE_USER_HOME`, `ANDROID_USER_HOME`, `XDG_DATA_HOME`). Updating Claude Code on a node is the
provisioner's; a session's own updater is off. The helper
then drops to the session account with `no_new_privs`, so nothing inside
can gain privilege again. The agent installs the helper, its layout file and
the sudo rule from the bundle, and reports on the node's Sessions section
whether a view can be built and why not. A Mac, a guest machine or a
container node, whose agent is not root, cannot, and says so there. The
view is not a VM: the kernel is shared, and so is the network unless the
node keeps each session to its own project's network (below).
A workspace-root shell, which needs the `terminal` right, is not confined.

**Each session on its own project's network (roadmap R79)** is a switch in a
node's Sessions section, off by default. On, a session started there gets a
network namespace of its own from `bb-session`: a veth pair to the node, an
address from `10.231.0.0/16`, and a resolver file naming the node's upstream
DNS servers. The agent keeps an nftables table (`builderbot_sessnet`) that
judges everything leaving a session's link: the internet, the controller and
the DNS servers pass, and so do the containers the session's project owns on
that node (the project a container belongs to on the Docker tab, the same
setting that says whose sessions may work on it); everything else that is not
the internet (every other container, the node's own services, the LAN) is
refused, and nothing, on the network or on the node itself, can open a
connection into a session. Only those sessions are touched: every rule matches
their links (`bbsN`) or their range, and everybody else's programs on the
machine keep its network as it was. What passes is
marked, and Docker's `DOCKER-USER` chain lets through only marked traffic
from a session, so if the table ever disappears a session loses its network
rather than gaining the node's. A session reaches its own containers at the
node's address and published port, not at `localhost`, which is its own; the
emulator it starts itself runs inside with it. Turning the switch on or off
applies to sessions started afterwards; one started while it was on keeps
its network until it ends. The row says, in red, when the switch is on and
it is not in force: an agent that is not root, a firewalld or ufw firewall,
no upstream DNS server, an older `bb-session`, or a node whose own network
already uses `10.231.x.x` (a LAN, a VPN or a VM bridge), which a session's
address would hide from everything on the machine. When setting it up fails,
no session starts on that node until it works or the switch is turned off.
A container in Docker's host network mode is not reachable from an isolated
session, since it has no address of its own to allow.

**Each project's containers on their own network (R178, the operator, 11
Oct)** is the same idea for the containers themselves, for a node two
web-facing projects share. Docker already keeps compose networks apart,
but a container reached another project's container by the node's address
(its published port, after Docker's DNAT) and the node's own ports, measured
on the dev pair. The agent's keeper runs a second table,
`builderbot_ctrnet`: forward from a compose bridge passes to its own
bridge, the bridges of the projects its owner reads, the controller, DNS
and the internet, and is dropped to any other bridge and rejected to the
private ranges; into the node it passes to the controller, DNS, 80 and 443
(nginx, the way in) and the published ports of its own project and the ones
it reads. The hello carries the map (`devapp.container_net_own`, compose
project to the compose projects it may reach) and the switch (config
`container_net`, on by default for a hosting-only node, on the row beside
the session switch elsewhere); a prefs change or the switch asks for a
hello, so a container reaches a newly read project within a poll. Nothing
is marked: a missing table leaves Docker's own rules, and the row says not
in force rather than a container being cut off. A container BuilderBot
deploys itself is **System**'s (R180, the operator, 11 Oct): the nginx
tab's container today, set by that deployment and by no picker, a person's
or a session's, and given every bridge and every published port on its node
by the map (`all`), since a proxy or a monitor that is nobody's has to see
everybody's. nginx needs none of it yet, being on the host network; the
owner is for the day a deployment of BuilderBot's sits on a bridge.

nginx keeps up to date like the toolchains and the agent (R192, the
operator, 11 Oct). The controller reads the registry's tag list once a week
(Check now on the nginx tab reads it at once) and keeps the newest release
line's alpine tag with its digest; a node's nginx is pinned to a digest when
it is deployed or updated, written into its compose file as
`nginx:TAG@sha256:...`, so a Save rebuilds with exactly what it had and
nothing moves under it. A deployed nginx behind the newest line says so on
the nginx tab's node and on its Docker tab row, each with Update, which pins
the new digest and rebuilds; the bell carries a note of its own kind, to the
digest, so Dismiss holds until the registry moves the line again. One
deployed before any check had read the registry is unpinned, and behind
whatever is newest until its first Update.

Every other container's registry images keep up to date the same way (R195,
the operator, 11 Oct). A service that runs an image by tag, with no `build:`
(mariadb, a linuxserver image, ghcr.io/aquilaelabs/builderbot:latest), is
compared once a week, and on Check for updates on the Docker tab: the digest
its node pulled (`docker inspect`'s RepoDigests) against what the
registry serves for that tag now, over the registry's v2 API with an
anonymous token (imagecheck.py). One that differs says so on its row with
Update, which pulls (`compose pull --ignore-buildable`) and starts it again;
the bell carries one note per node. What is built from code is not asked:
Rebuild is what moves that, and it is ghosted until the code has moved. An
image pinned by digest (nginx's) is its own tab's, an image never pulled is
pulled by Up, and a private one says the registry would not answer. A
project's container is named whatever its owner wants: Send to Docker
offers the project's name and the compose file's folder or variant, and the
Edit dialog renames it while it is down, its record carrying the name while
the instance keeps its key.

**Also reaches**, under What a session sees in a project's settings, opens
the rest by hand (the operator, 7 Oct): a machine its sessions may still
reach, by its address, or one service on it, as `address:port`, without
making the project read another. Each address applies on the project's
nodes ticked beside it when the project is on more than one, on all of them
when every one is ticked, which also covers a node added later. It is
handed to the node with what the project owns there and lands in the same
sets, so sessions already running reach it within a poll, without a
restart. Setting it is an administrator's, since it is a hole in a shared
node's firewall that reaches past the project; a session cannot. An IPv4 address only:
a name or a range is refused by name, as are this machine, multicast, the
sessions' own range and a project's own node, which a session reaches only
through its containers. On a node whose switch is off it does nothing yet,
and the field says so.

### Push rights

A clone is read-only unless you tick **I want to push to this repository**, and
that decision is made once. Three rules, all deliberate:

- **It cannot be turned off.** A working copy that could push yesterday and
  cannot today explains nothing to whoever is standing in it. Deleting the
  project is the way out, which never touches GitHub.
- **One project per repository.** Two working copies pushing to one remote is
  how a branch ends up racing itself, and here both may be the same session on
  different days. Deleting the holder frees it.
- **The token is checked first.** Before the clone starts, GitHub is asked
  whether that token can actually push to that repository: a missing scope
  otherwise surfaces days later as a failure with nothing connecting it to the
  box you ticked. A deploy key cannot be checked this way short of pushing, so
  it is taken at its word.

Enforcement is a `pre-push` hook, which is transport-agnostic; it catches an
ssh push through a deploy key exactly as it catches an https one, and refuses
with a sentence rather than an auth error. Like the sibling-project rule it is
a guardrail, not a sandbox: a shell in the container can delete it.

A grant names the **host as well as the path**, because `sean/app` on GitHub
and `sean/app` on a Gitea in the cupboard are two repositories: mirroring one
to the other is a reason to link a second project, not a collision to refuse.
Grants written before there was more than one host are stamped as GitHub's
once, at startup, since nothing else could be linked when they were made.

### An access token for one project

Cloning a private repository asks for an optional **access token**. It is
written in git's own credential-store format to `/config/gitcreds/<project>`,
mode `0600`, and named from that repository's `.git/config` and nowhere else,
with git's empty-value reset ahead of it, so the globally configured helper is
never asked and no container-wide token authenticates the fetch.

That last part is the point. A token minted to reach one private repo usually
reaches every repo it was scoped to; in the environment it also reaches them
from every project and every session. Here it opens the one project you gave it
to, and stays with that project whatever it is renamed to.

A project that already has push rights can be given a token from the **chain**
on its row, including one that pushes with a **deploy key**. Setting one there
does not switch anything by itself: git never asks a credential helper about an
ssh remote, so a project with an `ssh://` or `git@` origin goes on using its
key however many tokens are stored for it.

None of this is GitHub's alone. The same dialog, the same file and the same
switch serve a Gitea, a Forgejo, a GitLab or anything else git can reach; only
two things differ by host, and both live in `forges.py`: whether a token can
be checked before it is stored, and whether a missing repository can be
created. Where the host has no API for either, the first fetch is the check
and the repository has to exist already, which the dialog says in a line.

The **Authentication** segment beside that field is what changes it. Three
answers, not two: *Disabled*, *Deploy key* and *Access token*. It shows which
one the remote actually reaches for and lets you move between them; the change
is applied when you press Save, which is also how a token typed in the same
dialog gets written before the switch that needs it. Under the hood it is one
`git remote set-url`, between `git@…:owner/repo.git` and
`https://host/owner/repo.git`, plus the credential helper.

*Disabled* is a real answer rather than the absence of one: the remote keeps
its https form and the helper comes off it, so a push is refused instead of
quietly falling back on whatever else git can find. It is also what makes the
dangerous case sayable: **clearing a token while the switch still says
*Access token* is refused at Save**, in those words. The pick is left exactly
where you put it and the reason is stated, rather than sliding to another mode
on your behalf: being corrected without being asked is how you end up on a
credential you did not choose.

**Test**, under the segment, says whether it works before a session finds
out (the operator, 7 Oct). It runs `git ls-remote` for the read and `git push
--dry-run` of HEAD to a branch nobody has for the write, which the host refuses
at the handshake when a deploy key is read-only or a token cannot push, and
which sends nothing; the project's own pre-push hook is skipped, so a clone
without push rights is still asked about its credential. For a token it also
asks the host's API what git cannot see: on GitHub a classic token's scopes
(without `workflow` a push touching `.github/workflows` is refused) and the
repository's push permission, on GitLab the role and the token's scopes, on
Gitea the push permission. What is missing is listed in red under the button
in the host's own words with what to change; a token typed and not saved yet
is what is tested, from a credential file of its own that is gone after.

The https address it writes is the **host the remote is actually on**, not a
constant: a deploy-key remote names a `bb-<key>-<host>` alias, and the server
it stands for is resolved out of `~/.ssh/config` with `ssh -G`, which reads
the file and touches no network.

**A stored token is closed, not shown.** Only its file has the value, so the
field cannot be pre-filled and typing over an invisible one is how a working
credential gets replaced by accident. It is disabled, with **Clear the stored
token** under it: pressing that opens the field for a new one, ghosts the
*Access token* side and puts the choice back on *Deploy key*. Like everything
else in this dialog it is staged: the project changes when you press Save,
and the link offers the way back until you do.

Clear the only credential a project has and both sides go quiet, with a line
saying it cannot push to GitHub and that everything else, commit, branch and
build, still works locally. The field stays typeable there deliberately:
ghosting it would be tidier and would leave no way back to pushing.

**Switching removes neither credential.** The token file stays in `/config`,
the deploy key and its `~/.ssh/config` alias stay where they are, and the
repository keeps its credential helper: an ssh remote simply never consults
one. So going back costs nothing, and the exact alias is restored rather than
guessed, because the alias is named after the *key* and there would be nothing
in the project to guess it from. A side you cannot take is shown disabled with
the reason: a project with no token stored, or one that has only ever been
https and so has no key remote to return to.

**It is not shielded the way a deploy key is.** Those are served by a root-owned
agent and cannot be read at all. This is a file owned by the same user your
shells run as, so a session with Bash can read it. Better than an environment
variable every process inherits, and not a secret store, for a repository
where that matters, use a deploy key.

The credential is filed under the **scheme, host and port** the remote uses,
because that is what git matches a stored line on. A token written against
the wrong one is a file git reads and then ignores: a credential that looks
stored and authenticates nothing, so the host is never defaulted. The
username beside it is a formality every host here accepts; where the host has
an API it is the account the token actually belongs to, asked for at the same
time the token is checked.

### Unlinking

**Unlink** sits at the far end of that dialog's foot, in red, with the verbs
that cannot be undone. It takes four things off, and the answer names each:
the `origin` remote, the stored access token, the credential helper pointing
at it, and the push grant, which is what frees the repository for another
project to be linked to it.

**It touches nothing in the tree.** No commit, no branch, no file, no reflog:
the history that was pushed is still here and can be pushed again the moment
something is linked. It is local and instant: the host is not contacted at
all, which is one of the reasons to reach for it, since the server may be the
thing that has gone. Any remote other than `origin` is left alone and named
back to you.

The deploy-key alias in `~/.ssh/config` stays as well. It is named after the
*key* and the host, not the project, and another project may be using it.

Unlinking is also **how a project moves from one host to another**: linking
refuses a repository that already has a remote, so this is the first half of
the move and pointing it at the new host is the second. The same repository
at a new address on the same host is not a move, and needs no unlinking:

### A new address for the same repository

Renaming your account or an organization on the host changes every
repository's address under it. The host redirects the old one only until
somebody claims the old name, so the remote should follow. **Repository
address**, in the same dialog, is where: type the new address and Save.

Only the path changes. The remote keeps its form (https, ssh, or a deploy
key's alias, which is named after the key and reaches the same host), the
access token stays filed under the host it always was, and the push grant
moves to the new path, so pushing carries on with nothing typed again.
Before this the push rights still named the old path, and the relay refused
every push to a remote pointed at the new one by hand.

Saving asks the new address for its branches and needs one of them to be a
commit this project already has: a renamed owner keeps every commit, while a
typo or another repository has none. Refused, with the remote left where it
was: an address on another host, a repository another project may push to,
and one that shares no history. A fork shares history too, so this checks
that it is the same history, not the same repository on the host's books;
that difference is why it is the administrator's control.

Changing it does not wait for the project's terminals to close: the address,
like the token and the authentication switch, is `.git/config` and the
store, which a running session reads on its next push. Only a new name, which
moves the directory, still asks for them to be closed first.

### Android signing keys

A project keeps up to two keys, set by an administrator under **Signing keys**
in its settings (the gear):

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
store's own `keytool` (the jdk toolchain) has to open it with the password
given, find the alias (or the only key in it) and see a private key, and its
certificate's SHA-256 fingerprint is what the dialog shows. A session never
receives the key or a password, and is refused even the list of which keys
exist: it signs with `bb sign`, which runs on the project's node as a job the
session cannot look inside. Renaming the project leaves its keys where they are, with it.

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
like everything else in the dialog: nothing is sent until Save.

**Several apps, several keys.** A project keeps as many named keys as it needs,
each with both slots; the first is **default**, which is where keys from
before there were names went. **Generate** makes one on the controller with
the store's `keytool` (RSA 4096, ten thousand days) behind a random password
kept with it, so nobody types or sees one, and its backup is a zip of the
keystore and that password. Under **Apps** an app's package is mapped to a
key; a sign job reads the package from the build (`aapt2` for an `.apk`, the
bundle's manifest for an `.aab`) and the controller hands it the mapped key, or
the default for a package with no line, unless the signing named one
(`bb sign FILE --key NAME`). Sharing one key between apps is allowed, and
sensible for apps meant to trust each other; a key of their own keeps one
app's lost key from being every app's. A session reads which keys exist and
proposes a new one or a mapping (`bb sign keys`, `bb sign key new NAME --for
sideload`, `bb sign map PACKAGE KEY`) under **Claude may: Manage signing
keys**, ask by default, which puts it in front of the project's owner.

**Moving an app to another sideload key.** **Rotate to it** on a key's
sideload row (or `bb sign rotate OLD NEW`, under the same dial) makes a proof
of rotation on the controller with the store's `apksigner`, signed by both
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

**Signing a build.** A person signs from the **Artifacts** tab: an `.apk` or
`.aab` row offers **Sign** for each key the project has. A session runs
`bb sign FILE [--for play|sideload] [--why "..."]` (Play for an `.aab` and
sideload for an `.apk` unless it says), under the project's dial **Claude
may: Sign a build**: auto signs, **ask** (the default) puts the build, the
key and the reason in front of the project's owner in their bell, and deny
refuses naming the setting. Either way it is the same job, and the session
follows it to the signed file's name. A signing that could not happen (no
such key, no such build, no node) is refused before anybody is asked.

**A release from a session.** `bb version release --why "..."` tags the
commit and publishes the release the way **Release** on the Artifacts tab
does, on the controller and with the project's own credentials, which the
session never holds (R138). It is its own dial, **Claude may: Tag and
publish a release**, named apart from signing, which makes a build rather
than a release: auto releases at once, **ask** (the default) puts the tag
and the commit it would mark in front of the project's owner in their bell
and the app, and deny refuses naming the setting. A release that could not
happen (no version, a tag already there, uncommitted changes) is refused
before anybody is asked.

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
deletes a release or moves its tag (R139).

A file comes off a release with `bb version release --remove NAME --why
"..."` (once for each name), and only that way: its own ask under the same
dial, never part of an edit, since it is the one change that takes
something away from the people downloading. The names are checked against
the forge's own list of the release's files before anybody is asked, so
the ask names files that are there, with their sizes, and the bell shows it
in the destructive color. On GitLab the release's link to the file goes;
the file itself stays in the package registry.

**What is signed says so.** The node reports what `apksigner verify` (or
`jarsigner -verify` for a bundle) found: the certificate's SHA-256 and the
signature schemes that verified. The controller keeps that in the file's
provenance, and its Artifacts row wears a *signed* tag, says which key and
from which build, and gives the whole fingerprint with **Copy for F-Droid**,
which copies it the way F-Droid's `AllowedAPKSigningKeys` takes it (lowercase,
no colons). A signed file is not offered Sign again.

### File access over FTP

A project's tree can be reached from outside BuilderBot with an FTP client
(R151, the operator, 7 Oct): the **File access** section of its settings
turns it on, picks the port, and gives each account that sees the project
**Read** or **Read and write**. Setting it up is the project owner's or an
administrator's; signing in also needs File access on the account's roles
on that project (R152), and gets the lesser of the two, so a role without it
refuses even the project's owner. A session never may set it. Anybody else on the project
is shown only that it is on, and where.

The server is the project's primary node's: the **ftp** toolchain's
`bb-ftpd` (pyftpdlib), one per project, which the agent starts from what
hello hands it, as the session account, rooted at `/workspace/NAME`, so a
file written over FTP is owned as a session's would be. It listens on the
port and uses the nine after it for passive data, which is why two projects
on one node are kept ten ports apart; the first free block from 2121 is
offered. TLS is required on the control and the data connection (FTPS,
explicit), because the password is the account's own BuilderBot password and
plain FTP would carry it as written. The certificate is made on the node the
first time and kept in the session account's home, so a client asks to trust
it once.

`bb-ftpd` knows nobody's password. Each login goes up its stdout to the
agent, which asks the controller's `ftp-auth`, and the answer goes back down
its stdin: the name and password checked as the dashboard's sign-in checks
them, then the access the project's settings give that account, and none for
an account since taken off the project. Nothing is cached, so an access taken
away holds from the next login. Ten failed logins from one address in five
minutes refuse that address for the rest of the window, and every login,
failed or not, is in the audit log. The project's `.git` is read-only over
FTP whatever the access, and nothing outside the tree is reachable, a
symlink pointing out of it included. A node whose store has no ftp
toolchain is said in red under the section as soon as it is ticked, from
the node's last report, before anything is tried; the tick stays usable,
so the port and the access can be set before the install. Save, when it
turns the server on or moves its port, asks the node's address from the
controller whether anything answers on the port or the nine after it and
refuses, naming the ports, when something does; the project's own running
server is not asked about.

### Locking a project

The **padlock** on a project row is the one gate there is, and it carries the
whole meaning: no session, a read-only notebook, no CLAUDE.md.

The list lives in `/config/locked-projects.json`, so it survives restarts and
image updates, and it is enforced by the terminal launcher and the server
rather than the page: the ttyd URL is reachable on its own, and so are the
API paths, so a rule only the UI honored would be advice. Locking a project:

- refuses `claude:<project>` at launch, with a message saying why
- ends every Claude session already running there, whoever's and on
  whatever node, rather than taking effect "next time"; the padlock's
  question names who is running one before it does
- is an administrator's: a user account sees the padlock dead and the
  server refuses the request
- makes its notebook **read-only**: the roadmap, the bugs and the memories
  open and cannot be changed, by you or by anything else
- refuses to write a `CLAUDE.md` into it, so the `no CLAUDE.md: create one`
  line stays as plain text rather than being an offer

**What it deliberately does not touch is everything you do yourself.** A locked
row is not folded away and not grayed out; it is a project you are actively
running, and dimming it would say the opposite. A closed padlock sits after the
name so the row reads *"StreamLift, locked"* without hunting for which of six
icons is lit, and:

- the **shell** still opens, which is how you go and look at it
- its **static analysis** is still counted and still opens on the Analysis
  view, with its history: locking says who runs a project, not whether its code
  is worth knowing about
- its **artifacts** are still listed, and a **dev instance** still builds and
  runs; that is usually the reason a project is locked in the first place
- the **version** block, the settings dialog and the rename all still work

One limit worth stating, because it is the same one the sibling-project rule
carries: this stops a session **starting here**, and the file tools are already
denied on every project but a session's own. It is not a sandbox: a session in
another project can still reach this directory through Bash.

**There is no password setting.** The first page the dashboard serves asks you
to make the **owner** account, and it is the only page it serves until you
have; nothing else is reachable, signed in or not. So open it as soon as the
container is up: until somebody claims it, whoever can reach the port can.

Afterwards, `bb users passwd <name>` changes a password and `bb users add`
makes the others. `bb users token <project> [<account>]` mints the scoped
session token a Claude session is given, for proving a node by hand, where
`bb` reaches the controller with `BB_TOKEN` and nothing else; with an
account named it is the token a node-bound terminal carries, which is also
what reports that account's Claude sign-in on the node.

**A Claude sign-in is one account's, on one node.** A person signs in on
each node they work on, and the login stays in that account's home on that
machine: nothing carries it to another node, and the controller holds no
credential, only what each node reported. A refresh rotates the refresh
token, so one login on two machines signs each of them out in turn; a login
per machine is the shape Claude supports. The sign-in is at the top of the
node's Claude Code section on the Nodes tab, for whoever is looking: *You
are signed in here as* the Anthropic account that node reported, with **Sign
out**, or *You are not signed in to Claude on* that node, with **Sign in**.
**There is no terminal in it.** `claude auth login` is interactive, printing
a URL and waiting for the code the browser gives back, and a terminal is the
worst place for both on a phone: a wrapped URL cannot be selected out of a
canvas and a paste into one silently does not arrive. The flow runs on the
node under a pty, as a job; the row shows its link to tap and a field for
the code, which goes down to the node on the job's own channel, and what the
flow says when it refuses a code is said on the row in its own words. The
field passes the code through rather than judging it: the authorize URL the
code page glues to it is cut off, whitespace and control junk are stripped,
and the only pastes refused outright are one with no code left in it and
one far too long to be a code. A running flow, with its link, is shown to
the account it was started for and to nobody else. Sign out asks first and
runs `claude auth logout` on that node, in that account's home; it is dead
while that account has a Claude session open there, which the row names,
and a sign-in on any other node is untouched. A node that is not answering
offers neither, with the reason on the row.

**A project's Claude button knows which node it is about.** Where this
account's session is already running, the press opens the chooser rather
than jumping to the tab: **Open tab** and **End session** for the node it
runs on, and the project's other nodes offered beside it, so a session on a
second node can be started from the same place. Where this account is
signed in on the project's node, the press starts the session or opens the
chooser with Resume and New conversation, as it always has. Where
it is not, the chooser offers **Sign in on** that node in their place, which
opens the Nodes tab on that node with its Claude Code section unfolded. A
project on several nodes lists each under its name: Resume and New
conversation for a node this account is signed in on, the sign-in for one it
is not, and the reason alone for one where a session cannot start.

**An account that does not administer sees the Nodes tab and changes
nothing on it but its own sign-in.** Its picker lists the nodes its own
projects work on and no others; every control on the node's page is
ghosted for it, updating Claude Code and enrolling included, and a line on
the row says so; the verbs behind those controls are an administrator's on
the server as well.

**Claude Code is a toolchain of each node, installed on purpose, and by
nothing a session can do.** The provisioner does not install it: a node's
Toolchains tab has a Claude Code row, with the version its session account
runs against the latest the controller knows, asked on the toolchains' own
clock (weekly, when a node starts, and on **Check for updates**). Until it
is installed no Claude session starts there: the project's Claude button
is ghosted with the reason, and the terminal refuses with the same
sentence. Tick it and press **Install selected** to install or update it:
that ends every Claude session on the node first, then the agent runs the
installer as the session account and, on a managed node, pins the binary
where the account cannot write it, so `claude update` typed in a session
changes nothing that runs (the auto-updater is off there too). The bin
removes it. Nothing starts again on its own: the project rows do, when you
press them, and until the job ends those rows are held with the reason. A
node behind is a row in the bell, and stays on what it has until you
install the update: nothing updates it before a session starts (a switch
that did went on 7 Oct). The node's Claude Code section on the Nodes tab
keeps each account's sign-in, and a button to the Toolchains tab.

**A token lasts twelve hours, and a conversation can last longer.** One is
minted per connection, so opening the session's tab refreshes it, but the
`claude` already running keeps the environment it started in, and nothing
outside a process can change that. So `bb-tty` also writes the fresh token
beside the launcher in the account's own cache (0600), and `bb` reads it the
moment the one in its environment has expired. A long session therefore
recovers by having its tab opened, and until it is, `bb` says the token
expired and when, rather than "not signed in", which sent somebody looking
for a sign-in that was never the problem.

**And it renews itself while the session works.** Past half its life, every
authenticated answer from the controller: a `bb` verb, the hook that runs
on each prompt: carries a fresh token in an `X-BB-Session` header, and the
client writes it into that same cache file; `bb` then sends whichever of
its two tokens expires later. A session in use therefore never runs out; only
one idle for twelve hours does, and that one is told to have its tab opened.
An expired token is never renewed, which is what keeps twelve hours meaning
something for one that leaked. This came from a session driven from the
remote view overnight: the token from the tab it was started in ran out at
one in the morning, every `bb` verb stopped, and there was no tab to open.
`bb status` says which copy is in use and when it runs out (the
environment's, or the kept one once that has been renewed past it), so
renewal is something to see: a session reading only its environment once
reported a token that had been replaced hours earlier as expired.

#### Accounts

The Administration card's **Users** tab adds people, and **Edit** on a row opens everything about one account in a dialog (its name, role, projects, name and email, git identity and a new password) saved together. There is exactly one **owner**,
undeletable and renameable; an **admin** can do everything except act on the
owner; a **user** gets the projects you give them and the work inside them,
but not deleting one, renaming one, or changing which node it builds on: a
node is shared, and that setting reaches every project on it.

**The project list means the same thing for every role; what differs is the
remedy.** A project not on your list is read-only: no Claude session, no
notebook edits, no rebuild. An admin is shown *every* project: hiding one
from somebody who administers the box only sends them looking for it, with
the ones they have not taken on marked read-only, and they can add any of them
to their own list themselves. A user is shown only what you give them, and
cannot grant themselves anything. So for an admin the list is a seatbelt
against working on the wrong project; for a user it is the boundary. The
owner wears the same seatbelt (R135): they see every project by role and
work on the ones on their own list, which an owner record from before
carried as `*` and now carries by name; the one difference from an
administrator is that the owner may add themselves to an invite-only
project without an invitation.

**Roles and permissions.** Everything an account may do comes from its
roles, set on the **Roles** tab and nowhere else (R152, the operator, 7 Oct).
A role is a **scope** (**Global**, which holds everywhere and is the only one
that reaches the machinery, or **the user's projects**) and, per area,
**Read** and **Write**: Projects, Project settings, Releases and versions, Git
authentication, File access, Containers and Terminal on a project;
Nodes, Toolchains, Jobs, New projects, CI runner, Accounts and roles and
Controller beside them. A Global role may name the nodes it holds on (**On
these nodes**, none ticked being every node) for Nodes, Toolchains, Jobs and
New projects: a role with New projects to write on bb-sandbox alone lets an
account make projects there and nowhere else, a project made elsewhere or on
no node being refused by name, and the account owns what it makes, so it
holds PROJECT_owner on it. Write needs Read, and an area without Read is not shown. Terminal's
Read is the shielded Claude console and its Write the full tmux shell, which
reaches every account's files on its node.

**owner** and **admin** are built in with everything; an admin may not change
the owner's account or roles. There is no built-in user role: an account
added holds none and may do nothing until it is given one, and the accounts
that were on `user` were moved to none, once. A project's owner holds
`PROJECT_owner` on it, every project area to write, made when the project is
and moved with it when it changes hands; it is an ordinary role, so cutting
it back (taking File access off it, say) holds for whoever owns the project.

A person may do what their roles give and nothing else: an account on a
project's list with no role there works on nothing. A Claude session does no
more than the person behind it: what its own rules (its project's Claude may
dials, a session's limits) allow and what its account's roles give on the
project, whichever is less, the projects it reads included, so a session of
somebody who may only read a project can only read it.

An area without Read is not offered (the status carries each area's level,
and the page hides the tab or card), and the server holds the same line: the
Users and Roles reads, a Claude console without Terminal Read (no terminal
at all), the Jobs listing (a person's own projects' jobs alone) and the
Docker listing (the projects whose Containers they may read). Without Nodes
or Toolchains Read those reads answer only for the nodes of the person's own
projects, which a Claude sign-in there needs, and never for another machine.

The tab is two sections, each with its own **Save** and **Revert**. **People**
picks an account: its Global roles, the projects it is on, and the roles it
holds on each. **Roles** picks a role or adds one: its scope, what it is for,
and a Read and a Write per area. A project's owner who is not an
administrator opens the tab from the People field of their project's
settings and sees the people and roles of the projects they own: they put
people on those projects and give them roles there, and nothing Global. Every
gate on the server reads the same roles (`users.may` through
`roles.CAP_AREA`), which keeps the tabs and the refusals consistent.

**Every project has an owner, and an owner can close it to administrators.**
Whoever made a project owns it; one from before there were owners belongs to
BuilderBot's owner. Under **People** in the project's settings (the gear)
BuilderBot's owner hands it to another account at once, and the project's own
owner offers it: the offer waits in the other person's bell like an
invitation, and the project changes hands when they accept (and only if the
one who offered still owns it then). Either can make it
**invite only**: then nobody else changes who is on it, so an administrator
can still see it but cannot add themselves, or anybody, on the Users tab or
anywhere, and people join by invitation. BuilderBot's owner is never kept
out. **Invite** there picks an existing account, user or admin; the
invitation waits in that person's bell with **Accept** and **Decline**, and
accepting puts the project on their list. Whoever invited, the owner, or
BuilderBot's owner can **Withdraw** one still waiting. On a project that is
not invite only any administrator may invite too, as they could always add
people. A session has no say in any of it.

Each account works as itself:

- **its own home**: own shell history, own Claude login, own memories. The
  box's own dotfiles are shared into it rather than copied, so the Android
  pairing key, the AVDs and the build caches are not duplicated per person
- **its transcripts and memories in one place whichever machine ran the
  session**: the home's `~/.claude/projects` is a link to the account's own
  directory at `/workspace/.claude/<uid>/projects`, made on this container
  and on every node alike (a node keeps that directory itself and its agent
  mirrors it here), so a
  conversation held on a node is offered here to resume and its memories
  show on the notebook's Memory tab. A home that already held transcripts has them copied across
  once, the original kept beside the link as `projects.moved-<date>` for
  you to delete. The login itself stays in the home, per machine
- **its own terminals.** A shell session is named for the account, so two
  people opening a terminal on one project do not land in the same one
- **its own tab strip and color scheme**, which follow the account to any
  browser it signs in on rather than living in one browser
- **the owner keeps this container's original home and session names**, so an
  install with one operator is unchanged by any of it

**More than one person can work a project at once, in a working tree each.**
The owner works in the project directory as always; anybody else gets a **git
worktree**: a checkout of their own, on a branch of their own, sharing the
project's one `.git`. That is what makes it safe, and coordination inside one
tree could not have been: `/workspace/<project>` is a single working tree, so
two sessions in it commit each other's half-finished work and delete it with a
`checkout`. Separate trees make that impossible and put the conflicts at the
merge, where git is good at them. A worktree session builds into its own
`dist/`, which the Artifacts tab lists apart from the project's, under whose
worktree and branch it is, with Download and View; Install and Push stay with
the project's `dist/`. The dev instance belongs to the project rather than to
the session.

**Chat** is the fourth flyout beside Keys, Commands and Sessions. It lists the
other accounts (a green dot for whoever is here right now) and, under them,
the **project channels**, which are group chats for everybody on a project. A
channel carries what people type into it *and* what the box notices: a Claude
session started, a rebuild, and what each person asked Claude. Three people on
one project not doing the same work twice is the whole point of it.

An admin is shown every project's channel, since they are shown every project,
with the ones they have taken on marked and sorted first. A `user` has the
channels for the projects they were given. Reading and answering a channel is
not a change to the project, so it follows what you can *see* rather than what
you have taken on.

**Prompts on a shared project are not private**, and the panel says so where
the channel is drawn rather than leaving it to be discovered: what you ask
Claude on a project you share goes to the people you share it with.

`bb work` says who else is in the project and which files two of you have
uncommitted at once. Two answers, and the cheap one is the truthful one: **git**
is exact: a file changed in two trees at once is a collision whatever anybody
intended, and it needs nothing recorded, while a **PreToolUse hook** adds the
finer grain, naming the definition an edit lands in, which is a guess and is
labeled as one. The hook also tells the second session, before its edit, that
somebody else has that file open. It does not refuse it: each session is in its
own worktree, so two people editing one function are making two commits rather
than corrupting one tree, and that is what a merge is for.

Each account signs in to Claude for itself, on each node it works on, from
that node's row. Which Anthropic account that is is the person's own choice:
the Users tab says when two BuilderBot accounts are on one, since Anthropic's
terms allow one person per Claude account, and nothing is refused for it.

The notebook (roadmap, bugs, analysis) stays shared, because it is about the
project; memories do not, because they are about the person.

**How many sessions work at once is a node's to limit**, not a project's:
what a working session costs is the machine's (Claude Code itself, and the
builds and tests it runs), several projects share a node, and each Anthropic
account's own limits are already its own. An administrator sets it in the node's
**Sessions** section on the Nodes tab, where the line beside it says how many are
working and waiting now; 0, the default, is no limit. A prompt past the limit
is not thrown away: it waits for a turn ("Waiting for a turn on this node" under
the prompt), and the turns go in the order they were asked for. One that has
waited fourteen minutes is refused with a sentence naming the node and the
limit, since a UserPromptSubmit hook is cut off at fifteen. A session counts as
working from the moment its prompt is let through until it stops, and also
whenever its pane's title shows Claude working, so a session opened before the
limit existed, or one that was interrupted, is counted by what it is doing.

**A `user` has no shell and no command line at all**, and that is what makes
the rest of the role mean something: everything else is enforced by the
dashboard, in Python, and a terminal is the way around all of it. So a `user`
gets no terminal tab, and their Claude session opens as a **console** instead:
the real interface, rendered by a `ttyd` started without `--writable`, with
a box to type a message and a button to end the conversation. The proxy
refuses anything else they ask a terminal for, so a read-only window cannot be
pointed at somebody else's session. They see Docker and the Toolchains tab
for their own projects' nodes: the scoping is on the answer, not just the
picker, so a node none of their projects builds on is refused rather than
listed, and change neither, with one exception: **Rebuild**, and Abort with
it. Building what you committed and looking at it is the point of having the
project, and Rebuild is also how a stopped instance comes back; the page
already ghosts it until the code has actually moved. They cannot create or
rename a project, change how one authenticates, or touch a stored token. What
they can write is the notebook, a rebuild, and a Claude session on a project
they were given.

Only the dashboard port is published. ttyd binds the loopback and the
dashboard relays `/term` to it, so the browser asks for credentials once and
the router needs one port. The relay is deliberately dumb: after checking the
session it splices the two sockets byte for byte and never parses a frame, and
credentials are checked in one place: the cookie or basic auth this server
already verifies. curl and scripts can skip the
login page entirely: basic auth is honored preemptively on every request
(`curl -u user:pass ...`), there is just no `WWW-Authenticate` challenge, and
that header is exactly what made browsers pop their own dialog.

The dashboard's own API runs commands from a fixed list; it takes a macro name,
never a command string, and the list is `bb`'s own commands rather than anything
the page can compose. The one exception is a **custom command**: the operator's
own lines, stored by one authenticated request and typed by another into a tty
they are already sitting at with a full shell. Nothing runs in the dashboard's
process either way, and anything else belongs in the terminal, which is one port
away and honest about being a shell.

## Telling a project's sessions about this environment

Every session is handed one block of text before it types anything, assembled
by the controller at the moment the session starts: how this machine works,
then the house rules in effect, then the open roadmap and the open bugs. The
Briefing tab shows a person exactly that string, byte for byte, because it is
the same assembly rather than another rendering of it.

What a session is told is split by one question: is there value in turning
it off? An obligation somebody might reasonably not want (sessions filing
what they notice, chasing a bug they meet, installing nothing, walking a
change in the app before calling it done) is a **global rule**, and what
nobody would switch off (no credential in a repository, a true report,
another person's branch left alone, the project's own files) is a line of
the briefing. The global rules are listed in every project's notebook,
under the project's own rules on the Briefing view: anybody who works on
the project can switch one off for that project alone, staged behind the
rules section's own Save, and an administrator also adds, edits and removes them,
or turns a shipped one off, for every project from the same place.

None of it is copied into the project. There is no file to render, push, or
keep in step, and nothing to go stale: the briefing is one file in the image
(`config/templates/briefing.md`), the rules live in `/config`, and a project
that has never heard of BuilderBot gets the same briefing as one that has.
The parts that only apply to some projects are marked in that file with the
evidence that decides them, matched as globs against the project's tree, so a
project with no Android in it is not told how to drive an emulator.

`CLAUDE.md` in a project is the project's own notes, committed, and nobody's
to generate. **A session is still held to the current environment**: a hook on
every tool call (`bb-gate`) refuses to run anything while the controller is
not answering, which is what a restart after an update looks like. That is
waited out. The compatibility window still holds a project whose *node* runs
an agent from another window, and the Nodes tab's Update is what clears it.

## Playwright, Android, plugins, publishing

- **Playwright**: the browsers are a toolchain on the store (the Toolchains
  tab's playwright), so `npx playwright test` runs headless in a session on any
  node that has it installed.
- **Android**: `./gradlew assembleRelease` runs on the project's node once
  the Toolchains tab has installed the JDK and the Android tools there; the
  emulator is that node's too, `bb emu start`. See
  [Multiple Android versions](#multiple-android-versions) to emulate more
  than one API level.
- **Claude Code plugins**: `/plugin` inside a session installs one for that
  person alone, in their own `~/.claude` on the node; a project's committed
  `.claude/settings.json` can name plugins everybody on it is offered. Each
  person's are listed on their **Profile** tab and every account's in
  `bb diag plugins`, since a plugin adds its own hooks and instructions beside
  BuilderBot's and a session that behaves oddly may be carrying one. The
  language-server plugins run a server a session cannot `npm install -g`
  into the store, so the Toolchains tab carries them: **language-servers** (pyright
  and typescript-language-server, for pyright-lsp and typescript-lsp) and
  **kotlin-lsp** (JetBrains' server, for kotlin-lsp). rust-analyzer and clangd
  already come with the rust and swift toolchains.
- **Training or running a model on the card**: the **pytorch** toolchain is a
  Python of its own, run as `python-ml`, with PyTorch built for CUDA (13 today, so a driver of 580 or newer),
  numpy and ONNX. PyTorch's wheels carry the CUDA libraries, so a node needs
  only its NVIDIA driver; a heavy job runs as `bb gpu run --mem MB --
  python-ml train.py`. A project wanting more packages makes its own
  environment over it (`python-ml -m venv --system-site-packages .venv`), so
  the store's copy stays as installed. Its install works in a folder beside
  itself on the store rather than in the node's `/tmp`, since the download is
  gigabytes and a node's own disk may not have them.
- **Publishing**: from a session, whatever the project's own credentials
  allow on its node (`gh release create`, Gradle publish tasks); from a shell
  on the controller, `npm publish` with `NPM_TOKEN`. An Android build is
  signed with `bb sign`, on the node, with a key the session never sees;
  any other signing key belongs in CI secrets, never the image.

## Logs

**One file per container start, per stream.** All four rotate together on
boot, so a generation number means the same boot in every one of them, and
`.1` is the previous run of the container.

| Log | Where |
|---|---|
| Startup, the runner supervisor, and every later warning | `config/logs/builderbot.log` |
| The dashboard server, in full | `config/logs/dashboard.log` |
| Every compose call the Docker manager made | `config/logs/docker.log` |
| The terminal server | `config/logs/ttyd.log` |
| Runner diagnostics | `_diag/` under the runner's directory on its node (`/var/lib/builderbot/runner/<slot>/_work/`) |
| CI job output | GitHub → Actions → the run |
| Emulator | `home/.android/emulator.log` |

All of them persist across updates, are secret-redacted, and move together to
the `/logs` mount if you map one.

**Kept for a number of days, not a number of boots.** Thirty by default, set
in the dashboard's settings menu: the gear, beside the color schemes. A
count was the wrong unit for the question anybody has (*was that this week?*)
and a container in a crash loop can burn five generations in a minute;
a ceiling of sixty generations survives for exactly that case.

**Apply crops.** Lowering the number deletes what it already excludes, then
and there, rather than waiting for the next boot, which is why it is a button
and not a field that saves itself: a number input fires `change` on its way
through every value the keyboard passes, so typing `30` over `300` would have
pruned at `3` in passing. Pressing it without changing anything is a
crop-now, which is the other thing you sometimes want. The same menu
downloads this session's logs as one file, or everything kept as a `.tar.gz`,
or the controller's **diagnostics** as one JSON file (what `bb diag` prints,
the reports sessions made about BuilderBot among it, redacted and on the audit
trail), and clears the kept generations without touching the ones being
written. Below it, **Clear reports** deletes every report sessions made about
BuilderBot, after a confirmation that says how many; the numbers carry on, so a bug that names report #3 never meets a
second one, and a session cannot clear them.

Two deliberate omissions from *this session*. `ttyd.log` is the terminal
server's connection churn (22,000 lines against 4KB of boot log on this box),
so it is in the archive and not in the thing you open to read what happened.
And the **CI logs stay where they are**, under `config/ci-logs/<repo>/`, one
file per run: a CI run is not a container session, it belongs to a workflow
run and spans whatever session was up. They are already grouped the way you
would want and `bb ci-log` reads them by run id: what was missing is that the
settings menu did not know they existed, so they are in the archive and under
the same retention now.

## A Mac as a node

`nodes/provision-macos.sh` enrolls a Mac as a **guest** node (bare, it prints
its help; the command to run is the one **Enroll node** gives you): one
directory
(`~/.builderbot`) and one launchd agent that runs as you at login, no root,
nothing in `/etc`, and `--remove` takes exactly that away. It is written for
the bash macOS ships, so it is its own file rather than a branch of the
Linux provisioner. `--check` runs only the pre-flight: the command line
tools, python3, Homebrew, Xcode, room, and whether the controller answers.

What a Mac node is for is what only a Mac builds: iOS, macOS, the Apple
half of a Flutter app. `--toolchains /Volumes/SDK` points its toolchain store at
the same share the Linux nodes use, mounted over SMB; its toolchains land under
`darwin-arm64` (or `darwin-x86_64`) in it and nobody else's are touched. The
Toolchains tab shows the node as a Mac and offers what the catalog packages for
`darwin`: the JDK, Node, Go and Flutter resolve their macOS downloads
through the same recipes, and `xcodes` installs and switches Xcode versions
from Apple's own downloads (Xcode itself is Apple's to serve and needs an
Apple ID once). The agent's package manager there is Homebrew, its service
launchd; the Nodes tab offers no Storage or Network, because a Mac's mounts
and address are its owner's, and asks for no root. Sessions on the Mac
itself need a `/workspace` the agent can keep a synced copy in, which on
macOS is one line in `/etc/synthetic.conf`, and are not set up by the
script.

Untested on a real Mac yet: the script and the agent's macOS path are
written against Apple's documentation and the agent's own tests, and the
first enrollment is the proof.

## The companion app

`android/` is an Android app that does most of what the dashboard does,
minus the terminals: the projects and their notebooks (roadmap, bugs,
briefing, design, artifacts, containers, tests, the repository's state),
the approvals, the nodes, the jobs, the accounts and your profile, in the
shape an Android app takes, screens and a bottom bar, not the tabs a
browser page needs. Sign in with the dashboard's address and your account;
the credential is kept in the device's encrypted preferences.

**More than one BuilderBot.** The app pairs with as many dashboards as
you have (R132): **Add another** under More signs in to the next, with a
name for it (home, work), and the one in front is picked from Home's title
or the list under More. Every pairing is watched, and each note names the
dashboard it came from once there are two, so an ask from one is never
answered on the other; the phone is lent from the one in front. **Forget**
takes a pairing off, with what the watch remembered about it.

**Its lock.** **Lock the app when it opens**, under More, asks for the
phone's own lock, a fingerprint, a face or its PIN, every time the app
comes to the front (R133). Nothing of the app's own is stored for it, and
a phone with no screen lock set is told to set one first.

**Claude, from the phone.** A project opens on its Claude view. Where a
session of your own is open on it, the view says whether it is working or
waiting on you and carries a box to say something to it, which goes into
that session's input and nowhere else (`/api/say`). Under it are your
conversations on the project: **Read the end** shows what was said last,
and **Share** hands the whole text to another app. Starting a session
stays the dashboard's, since that opens a terminal. The projects list says
the same per project, so the question a phone is picked up to ask, *is it
done?*, is answered before anything is opened.

**What else a project's views do.** Design is read here: the pages as
their boards, the themes with their colors, and the rules under what they
hold for. Docker lists the project's containers with Start, Stop and
Rebuild, each asked twice and run as a job on its node. Artifacts names
the version and opens a file of `dist/` with whatever the phone has for
its kind, which for an APK is the installer. Git fetches, pulls
(fast-forward only) and pushes under the project's push rights. Settings
sets the model, the effort and the project's color, staged until Save.
The controller's own settings are not in the app.

**Its look.** The app wears the dashboard's schemes, by the same names and
hexes, chosen under More and kept on the device.

**Notifications.** The app asks the dashboard what the bell would show and
posts it: on the interval you set while the app is open, and about once a
minute in the background through an inexact alarm, so nothing stays in the
shade between questions and the icon carries no dot of its own. A session
asking for your phone or for root on a node arrives as a notification with
**Approve** and **Deny** on it, answered without opening the app; changes a
session has waiting, a session of your own coming free to take a message
(a switch under More turns that one off), and a node whose agent is
behind or out of window or whose Claude Code is behind, arrive as notes
that open the right screen. The note that a session is waiting on you
names the project first and follows the project's *During a test run*
setting: where a new ask interrupts a run, it comes as soon as the session
is waiting, tests running or not, and says so; where a new ask waits for
the run, the note waits too, and comes when the tests finish. `bb test`
tells the dashboard when a run starts and ends, which is how it knows;
a run that never reports its end is forgotten after four hours. A
phone left alone can hold the alarm back for some minutes, which is why the
dashboard's bell carries the same questions. There is no push service: the phone reaches
your BuilderBot directly, on your network or over your tailnet, so nothing
needs an account with anybody, and nothing is kept in the repository.

**Keeping it in step with the dashboard.** `android/api-surface.json` names
every path the app calls and the fields it reads, and carries a number that
`server.py`'s `APP_API` and the app's `TARGET_API` both carry. The dashboard
suite's `appapi.mjs` holds the running server to that file, so a change that
renames a field or a path the app reads fails the suite until the app is
updated with it; and the app compares the dashboard's number to its own on
the More screen and says when it is behind, naming the newer APK in
BuilderBot's own Artifacts tab. Moving the surface means moving all three
together: the file, the constant, the app.

**Building it.** `.github/workflows/android-app.yml` builds the debug APK on
a node's runner: the JDK and the Android SDK come from the node's toolchain
store, the same environment every `bb` job gets, on a push to `main` that
touches `android/`, names it by `bb version --file`, drops it into
BuilderBot's `dist/` where the runner's machine mounts the projects share,
and uploads it as a workflow artifact. Locally, `cd android && ./gradlew
assembleDebug` with `JAVA_HOME` and `ANDROID_HOME` pointed at a node's store.
On a node the build writes under the node's own disk rather than the
projects share (a job's cache folder, or the account's `~/.cache/builderbot/gradle`),
because a directory emptied and removed in one build on NFS can fail to go
(B351); `./gradlew bbApk -PbbOut=NAME.apk` puts the debug APK into `dist/`
from wherever it was built, and that is what `bb build` runs.
