# Toolchains, the emulator and the phone

The Build group on the rail is where a node gets what a build needs:
**Toolchains** installs into a node's toolchain store, **Emulator** keeps
that node's Android system images, and **Phone** pairs a real handset with
it. **CI runner** is in [building.md](building.md#ci-runners), and **Apps**,
the apps to install on your own machines, in
[reference.md](reference.md#the-apps-a-person-installs). This doc covers the
store and the Toolchains page, the NVIDIA card, Android versions and the
emulator, and a phone lent to a project.

## The toolchain store lives outside the image

The image carries no toolchain beyond node, python and the Playwright
module. Everything a build needs: the JDK, the Android SDK, the emulator,
Flutter, .NET: is a recipe installed into a **node's toolchain store**, from
the Toolchains page with that node picked; the page lists nodes and nothing else,
and with none enrolled it says so. The controller's own store: the SDK
share, mapped at `/sdk` (Unraid default `/mnt/user/sdk`): holds
only what its boot keeps for `bb capture shot`, the Playwright browsers; nothing is
installed on the controller from the dashboard. A node enrolled with the same
share is recognized as sharing it, and each keeps its own directory there.

**One store, a directory per node.** A node's toolchains live under
`<store>/<node id>` (R196), so one share can serve every node and no node's
binaries land on another's, whatever distro each runs; this container keeps
its own under `<store>/<os>-<arch>` (`linux-x86_64`). The Android
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
the operator ticks the row.
What a project pins by number in its Gradle files (`ndkVersion`,
`buildToolsVersion`, `compileSdk`) is a row of its own on the page of the
node it builds on, named for the project, installed or not. Two more rows come from
what a build needs with no line pinning it: the build-tools its Android
Gradle plugin version defaults to when no `buildToolsVersion` says
otherwise (read from the version catalog, a plugins block or the old
classpath, against the table in the plugin's release notes). The level a
project compiles against is the Emulator page's question instead: it says
which of its node's projects compile against a level no image here is of,
and names the index's plain Google APIs image of that level to pick, since
an image exists at every level in several flavors under names only
Google's index knows (API 37 is `android-37.0`).

**The NVIDIA driver is the machine's, not the store's.** On a node whose
census names an NVIDIA card, the Toolchains page shows the driver as a row of
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
not for it, the Containers page's row says the compose cannot start as written
and why, and an Up or a Rebuild asked anyway (a session's `bb devapp
rebuild` included) is refused in the same words, rather than failing after
the build with Docker's "could not select device driver".

**What the card is used for** is three settings and a queue, none of which
moves work onto it: a program uses a GPU only if it was written to, through
CUDA or the video encoder. A node with a card has a **GPU** section on the
Nodes page with two switches and one Apply: *render the Android emulator on
the card*, which starts or stops the headless X server the emulator needs,
and *let sessions and jobs compute on it*, on by default. A project has its
own setting, *The node's GPU* in its Nodes settings, for running as if the machine
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
you.** `bb toolchains install|update|remove` refuses to run when `CLAUDECODE` or
`BB_AGENT` is in the environment; one of them is in everything a session runs,
whichever agent it is, and
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

On the page, one button does it: **Install selected** installs what is not
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
the state volume rather than only in memory. That is what makes the page open
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

**From the dashboard.** **Toolchains**, under Build on the rail, is a
**page** the way the findings report is: a list of
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
interchangeable. An image no AVD names says so, and is the one that is spare. A page rather than a dialog because an install runs for
minutes; it stays a page you can leave and come back to while you work, and the work itself is a background job on the container, so the
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

The Emulator page offers a level and a flavor and adds it to the picked node;
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
purpose: a workflow bumping a version must not move the ground under a
session.

**The first boot after an update is not free.** A container whose share is
empty installs the Playwright browsers (~1.3GB) on first start. That happens
once per share; from then on updates cost nothing.

## The Library

**Build** opens on the **Library**: everything a BuilderBot installs or
runs as one list for one node, picked in the bar. A section per kind, in
this order: the coding agents a session runs (Claude Code, Codex CLI,
Copilot CLI, Grok Build), the toolchains a project builds with, the tool
packs a person added, the apps a NAS runs as containers, and under **For
you** the companions a person downloads for their own machines. Every row
is one shape: its name, its tier (official, shipped with BuilderBot;
vetted, from the catalog the maintainers sign; sideloaded, added by URL or
made here), what is installed and what an update would move it to, one
line saying what it is, and at its right the one verb it takes: Install,
Update, Remove, Edit on a pack, Download on a companion. Details opens the
row on the whole description, the lines the Toolchains page's open row had:
what it adds to a session, its terms, its system packages, what it needs,
where it is on the store, how its download was checked, and its size; a
pack's **Look**, which fetches its manifest at the commit it is pinned to
and says what it fetches and runs, as the Add tool pack dialog does; an
agent's facts, your sign-in on this node and what you added to it; an app's
compose file as the catalog holds it, with the blanks New container fills
and the secrets made for it; a companion's other files. A search box under the head matches a
name, a description, a kind or a tier, and the chips beside it narrow the
list by kind and by tier; nothing there is saved.

Nothing installs a second way from here. A toolchain's Install is the
toolchain job described below, with its agreements asked the same way; an
agent's is the Agents verb; a pack's Install opens the Add tool pack dialog
on the catalog's commit, with Look first; an app's Install opens New
container with the app picked and its blanks shown, and Create makes it a
container on the Containers page. **Check for updates** in the bar asks
about every row that installs on the node, and **Add your own** is the
sideload: a tool pack from a repository, a pasted manifest or an upload.
The Toolchains and Agents pages below are what the Library reads.

## The Toolchains page

**Build**: **Toolchains**, the installer as a page:
every toolchain on the [toolchain store](#the-toolchain-store-lives-outside-the-image) with its
size, its installed version, its path, and an amber line when a check finds
a newer one. Ticks are for things there is something to do to; uninstalling
is a bin on the row. A recipe that gives a session commands says under
which name: they live under `bb tool NAME` (`bb tool graphics`, `bb tool
diagrams`), one name per recipe, so the row says what installing it adds,
two toolchains may both have a `render`, and none can shadow a verb of
bb's own; the suite holds the catalog to the script. The page holds build
toolchains alone: the coding agents a session runs (Claude Code, Codex CLI,
Copilot CLI) are installed, updated and removed on the **Agents** page beside
it (`POST /api/agents`), and on a node this page says so in one line with the
way there. Each row also names the system packages its tool puts
on the picked machine, in that machine's package manager's names, and for
one already installed which of them are missing there. They install with
the tool and only then; uninstalling a tool leaves them, since another may
use the same library. Each list is written per package manager (apt, dnf,
pacman, zypper, apk) and may name alternatives for a library renamed
between releases; `tools/check-sysdeps.py` checks every name against the
real package indexes of Ubuntu 22.04 to 26.04, Debian 12 and 13, Rocky 9
and 10, Fedora, Arch, openSUSE and Alpine. A recipe's system libraries are each machine's own,
outside the store, so when a node lacks some for a toolchain its store
already holds (a package removed since, or a machine rebuilt under its
store), a node BuilderBot manages installs them by itself the next time it
reports in, once per missing set, and never while its system changes are
locked to its console. Anywhere it cannot (a guest node, a locked one, an
install that failed) the page says which and **Install system packages**
puts them on that node without reinstalling the toolchain, and the row
that lacks them carries **Install them now**, which does it for that row
alone; the node's page says the same, before a build fails on it. A
toolchain another one needs (the JDK that PlantUML runs on, the Node that
Playwright's module needs) is installed with it, and a row whose needed
toolchain is not on the picked node says which and offers that row's own
install. A toolchain that puts something on
PATH reaches a session when the session starts, so its row says how many
sessions open on that node started before it was installed, and to reopen
them. Beside it under Build, **Emulator** (a node's Android system images:
which it has, which AVDs are built on each, and ticking the ones to add as
on Toolchains; a node without the command-line tools and the emulator says
so in amber, with a link to install them from Toolchains), **Phone** and
**CI runner**, each a page of its own.

**A toolchain that needs another says so, and the missing one is installed
first.** `android-tools` drives `sdkmanager`, which is a Java program, so it
needs a JDK. The catalog carries `requires`, the
install pulls in what is missing (never what is already there) and the page
says what it added. Node.js is a toolchain like any other for the same reason:
it is not needed to *be* a node (the agent is Python, and the provisioner
installs that), but a project built with npm needs it, and so does anything
driving a browser through Playwright, which declares it.

**Two machines may share one toolchain store, and BuilderBot recognizes the
pair.** An NFS export mounted by the controller and by a node is one
directory, and two machines unpacking one toolchain into it at once is a
broken install nobody can debug, so a job waits for one on a machine that
shares the store only when both write the same directory, in both
directions. Each machine's toolchains are in a directory of its own, so in
practice that is the Android system images under `<store>/shared`; toolchains
install on two machines side by side, and a check, the NVIDIA driver, the
container toolkit and system packages, which write no store, wait for
nothing there. One machine still runs one toolchain job at a
time. What identifies the pair is a marker file
inside the store itself, not the mount: this container reaches the toolchain store
through Unraid's FUSE layer while a node reaches the same bytes over NFS,
and neither mount string can be derived from the other. Nothing
machine-specific is written into a shared store: the generated
`sdk-env.sh`, whose every line is an absolute path, lives on the home volume
for that reason. Any number of machines may share one: each node installs
under its own directory in the store, named by its node id (R196), so no
machine runs a binary another put there.

### Licenses and agreements

Every row names what its tool is under, with a link. BuilderBot ships none of
these tools: an install downloads each from its own vendor onto your node.

A few install under an agreement rather than a license alone: Google's
Android SDK terms (every Android row) and NVIDIA's CUDA license (PyTorch).
Their rows say "Installing it asks you to accept", and Install selected
names each agreement with its link and asks **Accept and install** before
anything is fetched. The server refuses an install under an agreement that
was not accepted, and keeps who accepted it, when, and for which toolchains
in the audit log. A session is never the one to accept: `bb
toolchains install android:...` from a session, on a store nobody has
accepted Google's terms for, is refused and sent to this page.

## Multiple Android versions

Nothing Android is in the image: the SDK, the emulator and the system images
are a node's, in its toolchain store. An API level exists where that store
holds a system image for it: add one on the Emulator page with the node picked,
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
become DRM master. *Render the Android emulator on the card*, in the GPU
section of the node's page under Nodes, is that: `bb-sandbox gpu` starts a
headless Xorg on the card as a unit of the machine's own, on the driver the
Toolchains page's row installed (it installs none itself, and the section's
line opens that page until the driver is there), which writes
what it found to `/run/builderbot-gpu-display` and restarts a dead server
three times before saying so. The driver takes the card only after a reboot,
which the section says and Reboot under Advanced does; bb-session binds the
server's socket into each session's own `/tmp`, so `bb emu start` inside a
session finds `:0`. `bb emu start` **tests** for
the hardware path rather than trusting it: EGL has to answer on an X server
with a vendor driver, and Mesa answering counts as failure for exactly the
reason above, and it falls back to software when it does not. `bb emu gpu`
says which you have and why, in one line.

**Each project has its own emulator**, so one project's sessions never boot
a phone another project installed and signed into things on. `bb emu` keeps each project's AVDs in
a folder of its own (`~/.android/avd-projects/PROJECT`), and a project's
first `bb emu start` makes its phone. With nothing making projects take
turns, `bb emu start` decides whether the node has room for another: not
while the node is saturated, and only with the phone's memory, the
emulator's own and 2 GB for builds free, waiting up to five minutes for
room and then refusing with the numbers; a card short of a few hundred MB
free renders that phone in software. Phones made before AVDs were kept per
project are one project's to keep (`bb emu adopt`, or automatically for the project named
in the old folder's `.heir`), and a `bb-scrub.txt` beside an adopted phone
names packages another project left there, removed on its first boot.

## Playwright, Android, plugins, publishing

- **Playwright**: the browsers are a toolchain on the store (the Toolchains
  page's playwright), so `npx playwright test` runs headless in a session on any
  node that has it installed.
- **Android**: `./gradlew assembleRelease` runs on the project's node once
  the Toolchains page has installed the JDK and the Android tools there; the
  emulator is that node's too, `bb emu start`. See
  [Multiple Android versions](#multiple-android-versions) to emulate more
  than one API level.
- **Claude Code plugins**: `/plugin` inside a session installs one for that
  person alone, in their own `~/.claude` on the node; a project's committed
  `.claude/settings.json` can name plugins everybody on it is offered. Each
  person's, and the MCP servers they added to each coding agent, are listed
  under that agent on the node's **Agents** page, and every account's in
  `bb diag plugins`, since a plugin adds its own hooks and instructions beside
  BuilderBot's and a session that behaves oddly may be carrying one. The
  language-server plugins run a server a session cannot `npm install -g`
  into the store, so the Toolchains page carries them: **language-servers** (pyright
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
  on the controller, `npm publish` with an `NPM_TOKEN` from an `*.env` file
  in the secrets folder. An Android build is
  signed with `bb sign`, on the node, with a key the session never sees;
  any other signing key belongs in CI secrets, never the image.

## A phone, and asking before touching it

The container carries no adb and holds no phone. A handset is driven from a
**node** (whichever one has adb in its toolchain store), and the **Phone**
page, under Build with that node picked, pairs and connects it over
Android's wireless debugging and lists what a session is waiting to do
there.
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
the code, the port it belonged to is gone. The page notices that case and
says so, and says the thing worth saying first: try Connect, you are probably
already paired.

**A phone it has met is remembered.** Every pairing and every connection
puts the handset on the node's remembered list on the Phone page: its
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
goes to that account (on the Phone page and in their bell, nobody else's),
because the phone is on their desk and they are the one who said yes to it.

**A session never touches the phone itself.** It is kept on an adb server of
its own on the node, so a plain `adb devices` in a session shows the emulator
and nothing else. To reach the handset a session runs `bb phone run --why
"..." -- …`, which puts the reason and the exact command in front of the
phone's owner and waits; on **Allow** the node runs it and hands back the
output. The reason is required, not optional: approving a command you did
not write, with no sentence saying what it is for, is a guess.

**Lent to a project, a phone is driven without asking, and only for that
project's app.** Its owner lends it from the project's menu (**Lend your phone**) to one project on its
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
reason and the exact command in front of a person, on the Notifications page and the
bell, and waits. Which person is decided by the session that asks: the
account it belongs to, when that account is an administrator, and every
administrator when it is a user's, because a sandbox is a shared machine and
root on it is not a user's to allow. (Their own phone is: a phone request
goes to whoever connected the handset, which is the asker when it is theirs.
Letting a particular user allow root on a particular sandbox is a
permissions design of its own, not written yet.) Allow runs that one command as root on the
project's node, as a system job whose log opens with the reason and who
allowed it, so the Jobs page is the record; Deny says no. Only a node
provisioned as a sandbox takes it: somebody's own machine is not the
controller's to run root on, and there is no fake sudo either: a refusal
that says why beats a success that did not happen.

**Installing an APK and pushing an extension** from the Artifacts view go
the same way: the file is fetched onto the project's node and installed on
the phone there, or handed to web-ext there for a temporary add-on that
stays live until Stop. Both buttons are the connection owner's: anybody
else sees them ghosted with the owner named, and a push also needs web-ext
on that node, which the button says when it is missing.
