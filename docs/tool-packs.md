# Tool packs

A tool pack is a toolchain you add to BuilderBot yourself, from a git
repository you choose. BuilderBot ships no packs and keeps no list of them:
a pack is somebody's repository, and adding one is your decision. Once
added, it installs onto a node like any shipped toolchain, and it gives
Claude commands of its own through `bb tool`.

Use one for a tool BuilderBot does not carry: a decompiler, a protocol
analyzer, a game engine's headless editor, your company's internal CLI.

## Adding one

1. On the **Toolchains** page, press **Add tool pack** and give the
   repository's address. Only an administrator can.
2. Press **Look**. BuilderBot fetches the repository at its current commit
   and shows what it would do: what it fetches and runs to install, each
   command Claude would get and the exact words it runs, its license, and
   whether it comes with guidance.
3. Press **Add**. The pack is kept at the commit you looked at. A later
   commit to the repository changes nothing here until somebody approves it.
4. Install it on a node from the same page, like any toolchain.
5. In each project that should use it, open **Settings**, then
   **Toolchains**, and tick it. A pack starts off in every project, so
   adding one hands it to nobody by itself.

To update a pack, open its row's **Edit** and press **Look for a newer
commit**. The form marks every command the new commit adds, changes (with
what it was) or removes, and **Update** keeps the new commit. Where the pack
is installed, uninstall it and install it again to take the new commit.
**Remove** takes it out of the catalog.

## What a project's sessions can use

Each project's **Settings → Toolchains** lists every toolchain installed on
its node, shipped ones and packs alike. Shipped toolchains start on, packs
off. A toolchain left off is:

- not on a session's `PATH` or in its environment,
- hidden from the session's view of the toolchain store, and
- refused by `bb`, which names this setting as the reason.

A session started after you save takes the change.

## Writing one

A pack is a repository with a `bbtool.json` at its root:

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
  "system": {"apt": ["libmagic1"]},
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
| `label`, `about` | What the Toolchains page shows. |
| `platforms` | Where it works, as `linux/amd64`, `linux/arm64`, `darwin/arm64` and so on; `*` for any architecture. |
| `terms` | The licenses or agreements it is under, each a label and a link, shown on its row. |
| `install.steps` | What runs after the repository is fetched into the store, each a list of words; `{dir}` is the pack's directory. This is where a pack downloads its binaries. |
| `install.verify` | One command that must succeed for the install to count. |
| `layout` | `bin`: directories inside the pack to put on `PATH`. `env`: variables to set, each a path inside the pack or `=VALUE`. `tool`: a file whose presence means it is installed. |
| `system.apt` | Debian packages the node needs; installed first where the node lets BuilderBot administer it. |
| `verbs` | The commands a session calls as `bb tool NAME VERB`. |
| `guidance` | A Markdown file in the repository telling Claude when and how to use the pack. A session reads it with `bb help tool-NAME`. |

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

### What a pack can and cannot do

- It installs and runs as the node's job account, inside the session's view
  and network, like everything else a session runs. It gets no access a
  session does not already have.
- Its files are read-only to sessions, so a session cannot change what a
  verb runs.
- It runs only what its manifest says, at the commit an administrator
  approved.
