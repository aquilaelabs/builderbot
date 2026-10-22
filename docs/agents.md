# Coding agents

A session on a project runs a coding agent in a terminal on a node. Claude
Code is the one BuilderBot started with; OpenAI's Codex CLI (ChatGPT's
coding agent) and GitHub's Copilot CLI are being added beside it (R95), and
after them one open agent that drives any model through a model router.
This page says what each agent is to BuilderBot, where it is installed and
signed in to, and how far each is wired.

## One table of agents

Every place that used to say "Claude" asks one table which agent it is
looking at: `scripts/dashboard/agents.py`, with the page's copy in
`page-agents.js` (held to it by `unit/test_agents.py`). A row is an
adapter: the agent's name as a person reads it, its program and command,
whose account signs it in, the node jobs that install, sign in and sign out,
how it takes the briefing, what holds its guards, where its state and its
transcripts are read from.

| Agent | Program | Signs in with | Install job | Sign-in jobs | Sessions |
|---|---|---|---|---|---|
| Claude | Claude Code | an Anthropic account | `claude-update` | `claude-login`, `claude-logout` | yes |
| ChatGPT | Codex CLI | an OpenAI account (ChatGPT) | `codex-update` | `codex-login`, `codex-logout` | new conversations |
| Copilot | Copilot CLI | a GitHub account with a Copilot plan | `copilot-update` | `copilot-login`, `copilot-logout` | new conversations |
| Any model | an open agent (OpenCode, picked when its step is built) | none: the router holds the keys | | | not yet |

A row whose sessions are not wired yet is read by nothing that names a
session: `open-alpha` is a scratch terminal until the open agent lands, and
no Start offers it. A session's name carries its agent (`claude-alpha`,
`codex-alpha`), so one person may run a Claude session and a Codex session
on one project at once, and two people may run different agents on it.

## Starting a session

A project's Start opens the chooser, as it always has: each node the project
works on, Claude's Resume and New conversation, and under them a line for
each other agent installed on that node: **New conversation**, **Open tab**
and **End session** where yours is running there, or **Sign in on** the node
where you have no sign-in to it there, which opens the Agents page at that
agent's section.

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
  `COPILOT_CUSTOM_INSTRUCTIONS_DIRS`.
- **Its first-run questions answered.** The session's tree is marked trusted
  in the agent's own config (Codex's `[projects."DIR"]`, Copilot's
  `trustedFolders`), so a read-only console never meets a question it cannot
  answer.
- **Its model and effort.** New conversation for Codex or Copilot turns to
  that agent's own models and reasoning efforts, its default first (Codex
  CLI's from `codex debug models`, Copilot CLI's from `copilot help config`,
  read on 22 Oct); the pick rides the terminal's argument and bb-tty passes
  only a word on that agent's list. Nothing is saved for the next start.
- **Which agents a project allows.** Its settings' Agents may section has
  Coding agents, a tick for each agent beside Claude; one left unticked is
  not offered there and its terminal refuses. Claude always may.
- **The one Start opens.** Under the same ticks, *Start opens* names the
  agent the project's card and header say (Start ChatGPT, Open Copilot);
  Claude unless it names another. Its chooser still offers every allowed
  agent installed on each node.
- **Signed in or refused.** A terminal that would start a Codex or Copilot
  session with no sign-in there says so and where to sign in, as Claude's
  does.

## The Agents page

**Build, then Agents**, beside Toolchains: one node at a time, picked in the
bar, and a section per coding agent installed there.

- **The version.** Each section says what the node's session account runs
  against the newest release: Claude Code's from Anthropic's download
  service, Codex CLI's and Copilot CLI's from the npm registry, asked once
  after the controller starts, weekly, when a node starts, and on Check for
  updates on the Toolchains page. A node behind is a row in the bell, which
  opens this page when only agents are behind.
- **Install, Update, Remove.** An administrator's, or whoever may install
  toolchains on that node. Each ends that agent's sessions on the node
  first, then runs the vendor's own installer as the session account
  (`claude.ai/install.sh`, `chatgpt.com/codex/install.sh`,
  `gh.io/copilot-install`), and where the node's agent is root copies the
  binary somewhere the account cannot write, so an update typed in a
  session changes nothing that runs. Nothing installs or updates by itself.
- **Your sign-in on that node.** A sign-in is one account's on one node and
  never travels to another. Claude's flow prints a link and waits for the
  code the page gives back. Codex's and Copilot's are device flows: the
  section shows the link and a one-time code, which you enter on OpenAI's or
  GitHub's page; nothing is pasted back. Codex's device login has to be
  switched on in the ChatGPT account's security settings first.

The Nodes page keeps one line per node saying which agents are installed
there and which you are signed in to, with **Agents**, the way here. A
project's Start sends a person here when they have no sign-in on its node.

## The guards

Every guard a Claude session is held by holds for Codex and Copilot too,
through their own hooks rather than Claude Code's: BuilderBot writes them
into the account's hooks file for each (Codex's `hooks.json`, Copilot's
`hooks/builderbot.json`), each calling `bb-agent-hook` with the agent and
the event, which says the agent's payload again in Claude's shape and runs
the same hooks in the same order: before a tool the hold while BuilderBot
updates, the house rules' command guard and the work note; on a prompt the
relay, the rules and the node's turn limit; at the stop the house rules'
checks and the turn handed back; on the agent's own permission prompt the
asking mark. A refusal reaches Codex as Claude's does (exit 2) and Copilot
as its own `deny`. The hooks act only in a session BuilderBot started; the
same agent run by hand is untouched. Codex's own hook trust is passed over
for BuilderBot's where its version has the flag for it.

Not every guard has a place on every agent, and the project's settings
(Agents may, Coding agents) say which hold for which: Copilot has no hook
after a summary, so the house rules are not said again then, and neither
has a search tool for the code map's hint.

## In the dock, the bell and the turn limit

A Codex or Copilot session's dot in the dock reads from its own hooks, since
its pane title is not Claude Code's: working from the prompt its turn began
on, waiting once the turn ended, asking while its own permission prompt is
up, which the bell shows as it does a Claude session's. Its turn on a node
with a limit on sessions working at once is its own beside a Claude session
of the same person, and every agent's working session counts toward the
limit and Home's sessions tile alike.

## Your conversations, every agent's

`bb transcripts` in a session lists the asking account's own conversations
on the project, from every coding agent that account uses, each marked with
its agent, and never another account's: the controller looks under that
account's transcripts and nowhere else. Claude Code's are listed today;
Codex's and Copilot's session logs join the list as R95's step 8 keeps them.

## What the node reports

The node's agent probes each agent's `--version` as the session account on
its heartbeat, under the census key the table names (`claude`, `codex`,
`copilot`). Every few minutes it reads, for each account, who it is signed
in as: Claude Code's account from `.claude.json`, Codex CLI's from the id
token in `~/.codex/auth.json` (the account it names and its plan, never a
token), Copilot CLI's from the GitHub login its config remembers. The
controller keeps that per account, per node, per agent, and holds no
credential of any of them.

## Not built yet

Resuming a Codex or Copilot conversation, their transcripts, a model and effort kept per agent, the model router and the
open agent: R95's later steps.
A sign-in with real ChatGPT and GitHub accounts has been walked against
stubs only; the walk on a real account is the operator's.
