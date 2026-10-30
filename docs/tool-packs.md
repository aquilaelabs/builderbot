# Tool packs

A tool pack is a toolchain you add to BuilderBot yourself, from a git
repository you choose. BuilderBot ships no packs and keeps no list of them:
a pack is somebody's repository, and adding one is your decision. Once
added, it installs onto a node like any shipped toolchain, and it gives
sessions commands of its own through `bb tool`.

Use one for a tool BuilderBot does not carry: a decompiler, a protocol
analyzer, a game engine's headless editor, your company's internal CLI.

## Adding one

A pack is a `bbtool.json` (Writing one, below, says what goes in it) and
whatever scripts it runs. It does not have to come from the tool's own
authors: you can write one for any tool, as Wrapping someone else's tool,
at the end, shows.

1. On the **Library**, press **Add your own** and pick a tool pack. Only an
   account whose roles give Curate can. Then pick where it comes from:
   - **A repository**: a git repository with the `bbtool.json` at its root
     (`https://`, ssh, or `http://` for a git host on your network).
   - **Paste bbtool.json**: the manifest alone, which is the whole pack
     when its install steps fetch the tool itself.
   - **Upload files**: a zip or tar of the pack's folder, the `bbtool.json`
     at its top beside the scripts it runs. A single top-level folder is
     dropped, as with a project's archive, and it is at most 8 MB, since
     every node carries it; a pack fetches anything bigger as it installs.
2. Press **Look**. BuilderBot shows what it would do: what it fetches and
   runs to install, each command a session would get and the exact words it
   runs, its license, and whether it comes with guidance.
3. Press **Add**. A repository's pack is kept at the commit you looked at,
   and a later commit to it changes nothing here until somebody approves it.
   A pasted or uploaded pack is kept on the controller as a repository of
   its own, its version a commit there; the nodes take it from the
   controller, so it needs no git host at all.
4. Install it on a node from its card on the Library, like any toolchain.
5. In each project that should use it, open **Settings**, then
   **Toolchains**, and tick it. A pack starts off in every project, so
   adding one hands it to nobody by itself.

To update a pack, open its row's **Edit**. For a repository's pack it looks
at the repository's head as it opens; for a pack made here it opens on its
`bbtool.json`, to change in place, or takes an upload of a new version, and
**Look** reads what you gave. Either way the form marks every command the
new version adds, changes (with what it was) or removes, and **Update**
keeps it. Where the pack is installed, uninstall it and install it again to
take the new version.
**Remove** takes it out of the catalog. It is refused while a node's store
holds the pack, naming the node: uninstall it there first, since a pack gone
from the catalog leaves no row to uninstall its files from.

## Official packs and agent packs

Everything BuilderBot ships is a pack in this same format too (R169): under
`packs/official/` one `bbtool.json` per shipped toolchain, carrying the
recipe `config/toolchains.json` has for it under `shipped` (where it is
fetched from, how it is verified, the system packages it needs), and under
`packs/agents/` one per coding agent, carrying the adapter under `agent`
(the program sessions run, how it installs and updates, how a person signs
in, how it takes the briefing and BuilderBot's guards, where its
conversations are). Both carry `"tier": "official"`, which is what lets
them stand in for install steps and verbs and take a shipped name; a pack
you add is `url`, and a pack from the vetted catalog is `vetted`. An agent whose manifest cannot name how it takes the guards is
not a pack and is not listed. The files are written from the tables by
`tools/packs-export.py --write` and `bb lint` fails when they drift, so
the format is one; the installer and the agents' adapters still read
their own tables. The same folders live in the catalog repository
(`packs/official/NAME`, `packs/agents/NAME`, written there by
`tools/packs-export.py --catalog DIR`), and its index pins every one of
them at tier official to the catalog's own commit (`--catalog DIR
--index`, then the maintainer signs), so the catalog is the one list of
everything official and an install's Library shows a shipped row as the
catalog's, never twice.

### A coding agent of your own

A pack from the vetted catalog can bring a coding agent beside the five
BuilderBot ships. Its `agent` block is an adapter of data, never code: it
says how BuilderBot starts the agent, hands it the briefing and holds it to
the same guards, in the shapes BuilderBot already writes for the shipped
agents. The pack installs the agent's program like any pack (its `install`
steps, its `layout.bin` on `PATH`), and a catalog update updates it.

```json
"agent": {
  "name": "Kite", "product": "Kite CLI", "provider": "Kite Labs",
  "command": "kite",
  "briefing": {"how": "flag-text", "flag": "--rules"},
  "hooks": {"file": ".kite/hooks/builderbot.json", "shape": "grouped", "payload": "camel",
            "events": {"pre": "PreToolUse", "prompt": "UserPromptSubmit", "stop": "Stop",
                       "recall": "PostCompact", "asking": "PermissionRequest"},
            "tools": {"shell": ["run_command"], "edit": ["edit_file"]}},
  "env": {"KITE_DISABLE_AUTOUPDATER": "1"},
  "respawn": ["-c"],
  "first_prompt": {"how": "after-dashdash"},
  "signin": {"file": ".kite/auth.json", "env": "KITE_API_KEY", "login": ["kite", "login"]},
  "transcripts": {"dir": ".kite/sessions", "file": "{session}/log.jsonl", "session_key": "sessionId"},
  "models": ["kite-1", "kite-1-mini"], "model_flag": "--model"
}
```

| Key | What it says |
|---|---|
| `name`, `product`, `provider` | What the page calls it (Start, the dock, the Library card). |
| `command` | The program a session runs, on `PATH` from the pack's own `layout.bin`. |
| `briefing` | How it takes BuilderBot's briefing: `flag-text` (the text after `flag`), `flag-file` (the file's path after `flag`), `env-file` (a variable naming the file) or `none`. |
| `hooks` | Its hooks file under the account's home, written by BuilderBot at each start. `shape` is `grouped` (`{hooks: {EVENT: [{hooks: [{type, command, timeout}]}]}}`, as Claude Code, Codex CLI and Grok Build read) or `flat` (`{version: 1, hooks: {EVENT: [{type, bash, timeoutSec}]}}`, as Copilot CLI reads). `payload` is the fields its hooks send: `snake` (`tool_name`, `tool_input`, `session_id`) or `camel` (`toolName`, `toolInput`, `sessionId`). `events` names its own event for BuilderBot's `pre` (before a tool), `prompt`, `stop`, and optionally `recall` (after a summary) and `asking` (its permission prompt). `tools` adds its own names for a shell, an edit and a search where they are not the usual ones. |
| `env` | Up to eight fixed words its sessions start with (an updater or telemetry off). Never a path, `PATH`, `HOME`, `LD_*` or a `BB_` name. |
| `respawn` | The arguments that resume its newest conversation, when a session comes back. |
| `first_prompt` | How a new project's brief is handed over: after `--`, after a `flag`, or not at all. |
| `signin` | Where its sign-in is kept (a file under home, or a variable such as an API key), and the login command a terminal tab runs for it. |
| `transcripts` | Where its conversations are kept, so `bb transcripts` and the Sessions view read them, and which payload field carries a session's id. |
| `models`, `model_flag` | What Start's model step offers, and the option a pick is handed over with. |

`pre`, `prompt` and `stop` are required: an agent that cannot take the
guards is refused, as the shipped ones would be. The pack's name is its
sessions' name (`kite-myproject`), so it is 2 to 16 lowercase letters and
digits and never a shipped agent's. An agent is offered only from a pack the
vetted catalog pinned (or an official one): a pack added by its address
installs its program but never offers its agent, since the adapter decides
what runs in every session of it.

## The vetted catalog

The public catalog (the `builderbot-catalog` repository, R169) is an index
of packs reviewed by BuilderBot's maintainers, each entry pinning a pack's
repository to an exact commit and the sha256 of its archive at that
commit, never a branch or latest. The index is signed with the
maintainers' Ed25519 key; the public half ships with BuilderBot
(`config/catalog.pub`), and an install reads an entry only after the
signature checks: an index changed on the way, or signed by another key,
is refused and the one read before stands, with the reason said. Where it
is read from is the **Address** in Controller settings' Vetted catalog group. A pack the
catalog withdraws (`withdrawn: true` in the next signed index) is a line on
the bell for every install that holds it, saying to remove it. The Library
is what reads it. An entry may name a `path`, the folder of its repository
the pack lives in (the catalog's own packs do; a repository of several
packs may): its sha256 is then of that folder's archive at the commit,
Look reads the manifest there, and an install keeps the folder's files as
a pack made here, so a node fetches the folder and nothing else.

### Installing from the catalog

The Library's **Tool packs** cards are the index's packs not yet added,
each with its tier (official, vetted, sideloaded for one added by address
or made here), what it is and the platforms it works on; **Install** opens
the same dialog as Add your own on the commit the index pins, with the
archive's sha256 checked on the way in: Look (on the card, or in the
dialog) shows what it fetches and runs, and Add keeps exactly that. A pack
the catalog withdrew is not offered, one already added is its own card,
and an official entry is the shipped row it names. The catalog's trouble,
when it cannot be read, is said over the cards.

A pack kept from the catalog stays at the commit it was kept at. When a
later index pins a newer commit of it (the same repository and folder), its
card says so and offers **Catalog update**, which opens the dialog on the
new pin with what it changes marked verb by verb, as Edit does for a pack
added by address; **Update** keeps it at that pin with the index's sha256
checked, its tier kept. Edit on a pack kept from the catalog looks at the
index's pin too, never at the repository's head. A pack is kept as vetted or
official only at a commit and sha256 the signed index pins; anything else
is a pack by address.

### Without the network

A controller that cannot reach the catalog installs from a mirror of it.
`tools/catalog-mirror.py catalog-mirror.tar.gz`, run on a machine with the
network (from a checkout of BuilderBot), reads the catalog's index, checks
its signature, and fetches every repository the index pins at each commit it
pins, into one archive: the index as signed and a git bundle per repository.
`--from-dir` reads the index from a checkout of the catalog instead.

Controller settings' **Vetted catalog** imports it with **Import a mirror**.
The import is refused when the index is not the maintainers', when a pinned
repository is missing, or when the mirror was made before the one held.
Once imported, the Library reads the mirror's index whenever the catalog
does not answer, and a pack or app the mirror holds is fetched from its
bundle with nothing going to the network. A pack kept this way is kept as a
pack made here, so the nodes take it from the controller too. **Forget**
drops the mirror; what was kept from it stays. The same group holds the
catalog's address. A USB stick can carry one from the start: the stick
maker's `--mirror FILE` writes it onto the stick, and the controller imports
it as it starts (docs/image.md).

### Docker apps in the catalog

An entry of `"kind": "app"` is a Docker app: its folder holds `bbapp.json`
(`name`, `label`, `about`, `port`, `media`, `platforms`, `license`, and an
optional `icon`, a PNG, WebP or SVG file in the folder held to a pack's
rules) and
`compose.yml` beside it, the compose held to what an app of your own is held
to (every image pinned to a tag that is not latest, never built or
privileged, only the blanks New container fills). The Library lists it as
an **Apps** card with its tier. **Install** fetches the folder at the commit
the signed index pins, checks its archive's sha256, keeps the app and opens
New container with it picked, on the Library's node when that node runs
Docker (the card says when it does not); from then on New container offers
it to everyone, and each Create makes another container of it.

### A session asking for one

A session looks through the catalog with `bb tool search WORDS`: each
entry's name, kind, tier and what it is, and whether it is added here, never
its address or commit. `bb tool install NAME --why "what it is for"` asks for
a tool pack from it, and the project's **Install a tool pack** setting,
under Agents may, says what happens: **deny** refuses, **ask** (the default)
puts it on the bell for a person who may curate the catalog, whose Allow
adds it at the commit the signed index pins, its sha256 checked, and
**auto** adds it at once the same way. A session never installs a pack on a
node itself: once it is added, a person installs it from the Library. The
briefing names the two verbs and the setting's value.

## What a project's sessions can use

Each project's **Settings → Toolchains** lists every toolchain installed on
its node, shipped ones and packs alike. Shipped toolchains start on, packs
off. A toolchain left off is:

- not on a session's `PATH` or in its environment,
- hidden from the session's view of the toolchain store, and
- refused by `bb`, which names this setting as the reason.

A session started after you save takes the change.

## Writing one

A pack is a `bbtool.json`, at the top of a repository or of an upload, beside
the scripts it runs:

```json
{
  "name": "hexkit",
  "label": "Hex kit",
  "about": "Looks inside binaries: dumps, strings, headers.",
  "platforms": ["linux/amd64", "linux/arm64"],
  "terms": [{"label": "MIT", "url": "https://opensource.org/license/mit"}],
  "install": {
    "steps": [["sh", "{dir}/install.sh"]],
    "verify": ["{dir}/bin/hexkit", "--version"]
  },
  "layout": {"bin": ["bin"], "tool": "bin/hexkit"},
  "system": {"apt": ["libmagic1"], "dnf": ["file-libs"], "pacman": ["file"]},
  "verbs": {
    "dump": {"about": "A file's bytes as hex.", "usage": "FILE",
             "run": ["{dir}/bin/hexkit", "dump", "{args}"]},
    "report": {"about": "A report on a binary, into dist/.", "usage": "FILE",
               "run": ["python3", "{dir}/verbs/report.py", "--out", "{dist}", "{args}"]}
  },
  "guidance": "GUIDE.md"
}
```

| Field | What it is |
|---|---|
| `name` | The pack's name, 2 to 40 of `a-z`, `0-9` and `-`. It is the toolchain's name and the word after `bb tool`, and it cannot be a shipped toolchain's. |
| `label`, `about` | What the Library and the Installed page show. |
| `platforms` | Where it works, as `linux/amd64`, `linux/arm64`, `darwin/arm64` and so on; `linux/*` or `darwin/*` for any architecture of that system. A bare `*` is refused. |
| `terms` | The licenses or agreements it is under, each a label and a link, shown on its row. |
| `install.steps` | What runs after the repository is fetched into the store, each a list of words; `{dir}` is the pack's directory. This is where a pack downloads its binaries. |
| `install.verify` | One command that must succeed for the install to count. |
| `layout` | `bin`: directories inside the pack to put on `PATH`. `env`: variables to set, each a path inside the pack or `=VALUE`. `tool`: a file whose presence means it is installed. |
| `system.apt`, `system.dnf`, `system.pacman`, `system.zypper`, `system.apk` | The system packages the node needs, in each package manager's own names, installed first where the node lets BuilderBot administer it. A node's family installs its own manager's list; a pack that names lists, but none for a node's manager, is not offered on that node, its card and an Install there saying which managers it names. A pack with no system packages fits every family. |
| `verbs` | The commands a session calls as `bb tool NAME VERB`. |
| `works_with` | The BuilderBot release lines it works with, e.g. `["0.9", "0.10"]`; none named is every one. A pack that does not name this install's line is not added, and one held that stops fitting after an upgrade is a line on the bell saying to update or remove it (R169 step 6). |
| `touches` | What it touches: `hosts`, up to 16 host names its install fetches from, and `root`, true when it needs root on the node to install. Look shows both before it is added, and a pack that needs root is added by an administrator alone (R169 step 4). |
| `config` | What it asks for on each node (R172): a list of fields, each `{name, label, kind, help, required, env, scope}`, the kind one of `secret`, `text`, `choice` (with `choices`), `list` (with `fields`, rows of them), `switch` or `projects`. The Installed page draws them as Configure on the pack's row for the node picked; the answers are kept on the controller, a secret sealed and never shown again, and handed to the node, where a field with `env` reaches the pack's verbs as that environment variable (a switch as `1` or empty, a list as JSON). `scope` is `node` (the default: one answer for everybody on that node, set by whoever may Configure there) or `person`: each person's own, set under **Yours** on the same row by anyone who works on that node's projects, a secret sealed under their own key, written into their home on the node and read by their sessions' verbs over the node's answer. |
| `guidance` | A Markdown file in the repository telling a session, whichever coding agent runs it, when and how to use the pack. It reads it with `bb help tool-NAME`. |
| `icon` | Optional: a PNG, WebP or SVG file in the repository, at most 64 KB, which its Library card shows in place of its kind's glyph. It is read at the commit the pack is kept at, and refused with the pack when it is not the image its name says. It is shown as an image and nothing else, so an SVG's scripts never run. A pack without one keeps its kind's glyph. |

### Verbs

Each verb's `run` is a list of words, never a line a shell reads. Its first
word is a file inside the pack (`{dir}/...`), or `sh`, `bash` or `python3`
followed by a script inside the pack. These may appear in the words:

- `{dir}`: the pack's directory in the store.
- `{dist}`: the project's `dist/`, made if it is missing, where results the
  Artifacts view lists belong.
- `{project}`: the project's name.
- `{args}`: a word on its own, replaced by whatever the caller typed after
  the verb, each word passed as one word.

So `bb tool hexkit dump "a b" '$(id)'` runs `{dir}/bin/hexkit` with
exactly the arguments `dump`, `a b` and `$(id)`. Nothing is expanded.

The install marks executable every file a verb, an install step or
`verify` runs by its path, the layout's `tool`, and the files in its `bin`
directories. A file committed without its executable bit, as a forge's web
editor commits one, still runs.

### What a pack can and cannot do

- It installs and runs as the node's job account, inside the session's view
  and network, like everything else a session runs. It gets no access a
  session does not already have.
- Its files are read-only to sessions, so a session cannot change what a
  verb runs.
- It runs only what its manifest says, at the commit an administrator
  approved.

## Wrapping someone else's tool

A tool's authors need never have heard of BuilderBot. To give a session a
decompiler, say, write the pack yourself: a `bbtool.json` whose install
steps download the tool's own release, and whose verbs run it.

```json
{
  "name": "ghidra",
  "label": "Ghidra",
  "platforms": ["linux/amd64"],
  "terms": [{"label": "Apache-2.0", "url": "https://github.com/NationalSecurityAgency/ghidra/blob/master/LICENSE"}],
  "install": {
    "steps": [["sh", "{dir}/install.sh"]],
    "verify": ["{dir}/ghidra/support/analyzeHeadless", "-help"]
  },
  "layout": {"tool": "ghidra/support/analyzeHeadless"},
  "verbs": {
    "analyze": {"about": "Decompile a binary headless, the results into dist/.", "usage": "FILE",
                "run": ["{dir}/ghidra/support/analyzeHeadless", "{dist}", "proj", "-import", "{args}"]}
  }
}
```

`install.sh` beside it fetches the release archive and unpacks it into the
pack's directory. Upload the two files as a zip, or keep them in a
repository of your own; a pack whose install needs no script of its own
can be pasted as its `bbtool.json` alone. A session then has
`bb tool ghidra analyze FILE`, and nothing else of the tool's.
