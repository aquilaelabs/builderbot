# Coding agents

A session on a project runs a coding agent in a terminal on a node: Claude
(Anthropic's Claude Code), ChatGPT (OpenAI's Codex CLI), Copilot (GitHub's
Copilot CLI), Grok (xAI's Grok Build) or Any model (OpenCode, through a
node's model router), each used the same way and held to the same briefing
and guards. This page says what each agent is to BuilderBot, where it is
installed and signed in to, and how each is wired.

## One table of agents

Every place that names an agent asks one table which agent it is
looking at: `scripts/dashboard/agents.py`, with the page's copy in
`page-agents.js` (held to it by `unit/test_agents.py`). A row is an
adapter: the agent's name as a person reads it, its program and command,
whose account signs it in, the node jobs that install, sign in and sign out,
how it takes the briefing, what holds its guards, where its state and its
transcripts are read from.

| Agent | Program | Signs in with | Install job | Sign-in jobs | Sessions |
|---|---|---|---|---|---|
| Claude | Claude Code | an Anthropic account | `claude-update` | `claude-login`, `claude-logout` | yes |
| ChatGPT | Codex CLI | an OpenAI account (ChatGPT) | `codex-update` | `codex-login`, `codex-logout` | yes |
| Copilot | Copilot CLI | a GitHub account with a Copilot plan | `copilot-update` | `copilot-login`, `copilot-logout` | yes |
| Grok | Grok Build | a SuperGrok or X Premium+ account | `grok-update` | `grok-login`, `grok-logout` | yes |
| Any model | OpenCode | none: a node's model router holds the keys | `opencode-update` | | yes |

A session's name carries its agent (`claude-alpha`,
`codex-alpha`), so one person may run a Claude session and a Codex session
on one project at once, and two people may run different agents on it.

## Starting a session

A project's **Start agent** opens the chooser, in three bands under the
node it shows (a picker where the project works on several):

- **Yours here.** Every session of yours on the project, each agent's and
  each slot's on whichever node, with its state (working, waiting for you,
  asking you) and its **Open**, **Restart** and **End**.
- **Start.** A line for each agent installed on that node, the project's own
  first: **New** starts a conversation, or **Sign in** where you have no
  sign-in to it there, which opens that agent's own page on the node, at its sign-in.
- **Resume.** Your conversations on the project, newest first, each with its
  agent, when it was and its first words; one running in a session of yours
  is marked so and not offered, since two sessions would write over it.

While one of yours runs, the button reads **Manage agent**.

- **Several sessions of one agent.** New while a session of that agent is
  yours already starts a second one beside it, a **slot** of its own: its
  own session (`claude-alpha~2`), its own worktree on `<agent>/<name>-2`
  (the owner's too) and its own conversation, read as *Claude 2* in the
  dock, the card and Sessions. A Send with several of yours running asks
  which one. Each person may run three of one agent on a project at once
  unless its settings say otherwise (Agents may, *Sessions of one agent*,
  1 to 9); a slot past it is refused at the terminal.

- **A tree of its own.** Each agent's session works in a tree of its own: an
  agent other than Claude in a worktree on a branch `<agent>/<name>`
  (`codex/pat`), the owner's included; Claude keeps `claude/<name>` and the
  owner's project directory, so nothing that existed moves. Two agents of
  one person meet through git, as two people do.
- **The briefing, the agent's own way.** The same briefing a Claude session
  is handed, never written into the project's tree: Codex CLI is given it as
  developer instructions (`-c developer_instructions=...`, read from the
  file at exec), which add to its own rather than replace them; Copilot CLI
  reads it as an `AGENTS.md` in a folder named by
  `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`; Grok Build has it appended to its own
  prompt (`--rules`, read from the file at exec).
- **Its first-run questions answered.** The session's tree is marked trusted
  in the agent's own config (Codex's `[projects."DIR"]`, Copilot's
  `trustedFolders`), so a read-only console never meets a question it cannot
  answer.
- **Its model and effort.** New conversation for Codex or Copilot turns to
  that agent's own models and reasoning efforts, its default first (Codex
  CLI's from `codex debug models`, Copilot CLI's from `copilot help config`,
  read on 22 Oct); the pick rides the terminal's argument and bb-tty passes
  only a word on that agent's list. Nothing is saved for the next start.
  Grok runs its own default model: no list of its is kept yet.
- **Which agents a project allows.** Its settings' Agents may section has
  Coding agents, a tick for each agent beside Claude; one left unticked is
  not offered there and its terminal refuses. Claude always may.
- **Who may.** A role's Terminal area covers every agent alike: an account
  that may start a Claude session on a project may start any agent the
  project allows, and one that may not is offered none, the server refusing
  the same whoever asks.
- **The one Start opens.** Under the same ticks, *Start opens* names the
  agent listed first in Start agent's menu, and the one a project offers to
  install where its node lacks it; Claude unless it names another. The
  menu still offers every allowed agent installed on each node.
- **Signed in or refused.** A terminal that would start a Codex, Copilot or
  Grok session with no sign-in there says so and where to sign in, as
  Claude's does.

## The Library and the Installed page

**Build, then Library** has a card per coding agent under Coding agents,
for the node picked in the Build group's header
([toolchains.md](toolchains.md#the-library)): what it is, its version
against the latest, and Install or Update. **Machines, then Installed**
holds what that node has: a row per agent installed there, which opens on
your sign-in, what you added to the agent and Remove.

- **The version.** Each card and row says what the node's session account runs
  against the newest release: Claude Code's from Anthropic's download
  service, Codex CLI's and Copilot CLI's from the npm registry, Grok Build's
  from its stable channel (`x.ai/cli/stable`), asked once
  after the controller starts, weekly, when a node starts, and on Check for
  updates in the Library. A node behind is a row in the bell, which
  opens the Library on that node.
- **Install, Update, Remove.** Install and Update on the Library's card,
  Remove on the Installed page's row; an administrator's, or whoever may install
  toolchains on that node. Each ends that agent's sessions on the node
  first, then runs the vendor's own installer as the session account
  (`claude.ai/install.sh`, `chatgpt.com/codex/install.sh`,
  `gh.io/copilot-install`, `x.ai/cli/install.sh`), and where the node's agent is root copies the
  binary somewhere the account cannot write, so an update typed in a
  session changes nothing that runs. Nothing installs or updates by itself:
  Copilot's and Grok's own updaters are switched off in a session. Grok's
  installer checks its download against nothing published.
- **Your sign-in on that node.** A sign-in is one account's on one node and
  never travels to another. Claude's flow prints a link and waits for the
  code the page gives back. Codex's, Copilot's and Grok's are device flows: the
  row shows the link and a one-time code, which you enter on OpenAI's,
  GitHub's or xAI's page; nothing is pasted back. Codex's device login has to be
  switched on in the ChatGPT account's security settings first.

- **Your plugins and MCP servers.** Each agent's own page on a node (Open on
  its Installed row) lists what you added to that agent on the node, as the node last said: Claude Code's plugins, and
  every agent's MCP servers by name (never their settings). They are changed
  in a session, for you alone; Profile no longer lists them.

The Nodes page keeps one line per node saying which agents are installed
there and which you are signed in to. A project's Start sends a person to
that agent's own page on its node, at its sign-in, when they have no
sign-in there.

## The guards

Every guard a Claude session is held by holds for Codex, Copilot and Grok too,
through their own hooks rather than Claude Code's: BuilderBot writes them
into the account's hooks file for each (Codex's `hooks.json`, Copilot's
`hooks/builderbot.json`, Grok's `~/.grok/hooks/builderbot.json`), each calling `bb-agent-hook` with the agent and
the event, which says the agent's payload again in Claude's shape and runs
the same hooks in the same order: before a tool the hold while BuilderBot
updates, the house rules' command guard and the work note; on a prompt the
relay, the rules and the node's turn limit; at the stop the house rules'
checks and the turn handed back; on the agent's own permission prompt the
asking mark. A refusal reaches Codex and Grok as Claude's does (exit 2) and Copilot
as its own `deny`. Grok also reads Claude's hooks from `~/.claude/settings.json`
on its own; a session turns that off, so each guard runs once. The hooks act only in a session BuilderBot started; the
same agent run by hand is untouched. Codex's own hook trust is passed over
for BuilderBot's where its version has the flag for it.

Not every guard has a place on every agent, and the project's settings
(Agents may, Coding agents) say which hold for which: Copilot has no hook
after a summary, so the house rules are not said again then, and Codex's and
Copilot's searches are in the shell, out of the code map's hint's reach.
Grok has no hook for its permission prompt alone, so its dot is never
asking, and it does not pass a prompt hook's words on to the model, so a
house rule named in a prompt is not said to it then.

## In the dock, the bell and the turn limit

A Codex, Copilot or Grok session's dot in the dock reads from its own hooks, since
its pane title is not Claude Code's: working from the prompt its turn began
on, waiting once the turn ended, asking while its own permission prompt is
up, which the bell shows as it does a Claude session's. Its turn on a node
with a limit on sessions working at once is its own beside a Claude session
of the same person, and every agent's working session counts toward the
limit and Home's sessions tile alike.

## Your conversations, every agent's

`bb transcripts` in a session lists the asking account's own conversations
on the project, from every coding agent that account uses, each marked with
its agent, and never another account's (unless its person made one visible
on the Sessions view): the controller looks under that account's transcripts
and nowhere else. Codex's and Copilot's are kept by their Stop hook at the
end of every turn (Grok's too), copied from the agent's own log into an `<agent>/` folder
of the tree's folder in the account's transcripts, which the projects share
or claudesync carries to the controller as it carries Claude Code's. The
Sessions view shows each row's agent, reads and downloads it, shares and
deletes it, and Resume opens that agent and no other: the log is put back
where the agent looks for it on a node that never ran it (Codex's
`sessions/`, Copilot's `session-state/`) and the agent is told to resume it.
Grok keeps a session under a folder of its own encoding, so a Grok
conversation resumes on the node that ran it, and elsewhere says so.

## What the node reports

The node's agent probes each agent's `--version` as the session account on
its heartbeat, under the census key the table names (`claude`, `codex`,
`copilot`, `grok`). Every few minutes it reads, for each account, who it is signed
in as: Claude Code's account from `.claude.json`, Codex CLI's from the id
token in `~/.codex/auth.json` (the account it names and its plan, never a
token), Copilot CLI's from the GitHub login its config remembers, Grok
Build's from `~/.grok/auth.json` (the email its token names, never the
token). The
controller keeps that per account, per node, per agent, and holds no
credential of any of them.

## Any model, through a router

The fifth agent signs in to nobody. The **Model router** is a card of the
Library's under Services, and it is set up on the node's Installed page:
with a node picked, its page there (Configure on its row) takes the
provider keys you give it, other OpenAI-compatible endpoints, Ollama
beside it where you turn it on, and the projects allowed to use it;
Install deploys LiteLLM there as a written container once something is
behind it, Save on a deployed one rebuilds it with the change, and Remove
takes it off. On the Containers page it is a row of the System section. Each allowed project is handed the router's
address and a key of its own at a session's start, so its spend is its
own. Start's **Any model** offers the router's models with their context
and price where the router knows them (`Read the models` on its page reads
them), and OpenCode's own card says whether the router on that node is
there for it, and bb-tty
starts OpenCode with a config written for the session: the router as its
one provider, the briefing as an instructions file, and its permissions.
Each model is marked: one walked with OpenCode and BuilderBot's tools
(`router.WALKED_MODELS`) plain, the rest **untested** and offered all the
same, and one whose context cannot hold the briefing and the house rules
(the block a session is handed, counted by the server) says **too small
for the briefing**, with Start's line under the picker saying by how much.
While an Any model session runs, its tab on the dock says what its project
has spent through the router so far (the key is the project's, so the
spend is) and, for a model Ollama runs on the node, its tokens per second
as the router's log last measured it (**Read the spend** on its page
reads both). Its guards are a plugin of BuilderBot's that bb-tty writes into the
account's OpenCode plugins folder, calling `bb-agent-hook open` before a
tool (a refusal throws, so the tool does not run), on a prompt, at a
permission ask, at the turn's end and after a summary, and exporting the
conversation into the tree's transcript folder at each turn's end, where
bb transcripts and the Sessions view read it. A project no router allows
is told so at Start.
