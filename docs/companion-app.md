# The companion app

The companion app is BuilderBot on an Android phone: the projects and their
notebooks, the approvals and the notifications, without the terminals.
Download it from **Apps**, under Build on the rail. This doc covers what it
does, pairing it with several BuilderBots, its lock, Claude from the phone,
its notifications, and how it is kept in step with the dashboard and built.

`android/` is an Android app that does most of what the dashboard does,
minus the terminals: the projects and their notebooks (roadmap, bugs,
briefing, wiki, design, artifacts, containers, tests, the repository's state),
the approvals, the nodes, the jobs, the accounts and your profile, in the
shape an Android app takes, screens and a bottom bar. Sign in with the dashboard's address and your account;
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
suite's `appapi.mjs` holds the running server to that file, each field's
type pinned too, so a change that removes, renames or retypes a field or a
path the app reads fails the suite; and the app compares the dashboard's
number to its own on the More screen and says when either is behind, naming
the newer APK in BuilderBot's own Artifacts view. A field may be added at any
time; one is removed only in the release after the app stopped reading it,
with the file, the constant and a changelog line moved in that change. The
Windows companion and the VS Code extension are pinned the same way in
`scripts/dashboard/test/device-api.json` and held by `deviceapi.mjs`, and
each says plainly when its controller is too old or too new for it
([reference](reference.md)).

**Building it.** `.github/workflows/android-app.yml` builds the debug APK on
a node's runner: the JDK and the Android SDK come from the node's toolchain
store, the same environment every `bb` job gets, on a push to `main` that
touches `android/`, names it by `bb version --file`, drops it into
BuilderBot's `dist/` where the runner's machine mounts the projects share.
It is not kept as a workflow artifact: the builds worth keeping are the
releases, whose files hang off the GitHub release, and one artifact per
push filled the account's Actions storage in a month (B669). Locally, `cd android && ./gradlew
assembleDebug` with `JAVA_HOME` and `ANDROID_HOME` pointed at a node's store.
On a node the build writes under the node's own disk rather than the
projects share (a job's cache folder, or the account's `~/.cache/builderbot/gradle`),
because a directory emptied and removed in one build on NFS can fail to go
(B351); `./gradlew bbApk -PbbOut=NAME.apk` puts the debug APK into `dist/`
from wherever it was built, and that is what `bb build` runs.
