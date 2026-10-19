# The bb command

`bb` is BuilderBot's command line, on the PATH in every shell and session:
`bb help` lists its verbs, and [reference.md](reference.md#the-bb-helper)
prints every one. This doc explains the ones with more behind them than a
line: the test harness's verbs, the code map, capture, and the tools a
session uses on graphics, sound and documents.

## The test harness and the code map

`bb tests keep` holds the dashboard's test fixture up after the harness's
set-up, so `bb dashboard test SUITE` and `bb tests probe FILE.mjs` attach
to it: half the time of a fresh run, and the world a suite just left is
still there for a probe to look at. A probe is a scratch Playwright script
(importing `./lib.mjs`) that asks the page a question, which is how a
session finds out what a page really fetches or what a variable holds. The
kept world is not put back between runs, and a change to the dashboard's
python needs a fresh keep; `bb tests keep stop` ends it. Both are R75's
second step.

`bb dashboard trace [SECONDS]` prints what the dashboard was asked over
that window, by endpoint and by who asked, from a ring the server keeps in
memory: the command that shows a poll that should not be there or a page
that asks twice. The design suite holds the matching invariant: an idle page
issues only its two polls, and opening a page asks each endpoint once. R75's fourth step; the fifth puts the
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

## Capture and graphics

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

## Sound, documents and the machine's load

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

## As builder, not root

`bb` re-execs as `builder` automatically: `docker exec` lands as root, which
would break file ownership. A bare `docker exec -it BuilderBot bash` is still
root; use `bb shell` for the normal user.
