# Start here

You have an account on somebody's BuilderBot. This page is the whole of what
you need to do something useful with it; [how-it-works.md](how-it-works.md)
is the overview, and each part of the dashboard has a doc of its own beside
it in Help.

## What it is

A workstation for coding agents you reach in a browser. Each project on the
Projects page holds git repositories on a shared disk. A **session** is a coding
agent working in them (Claude, through Claude Code; ChatGPT, through Codex
CLI; Copilot, through Copilot CLI; Grok, through Grok Build; or any model,
through OpenCode and a machine's model router), on one of the machines
behind the dashboard, with a terminal you can watch and type into. A
project's page holds its **notebook**, where you and the sessions keep the
plan: the roadmap, the bugs, the house rules and the git view.

Nothing runs on your laptop, and nothing here is on your laptop. Close the tab
and a session keeps going.

## Finding your way

- **The rail**, down the left edge: Home, Projects, Build, Containers,
  Controller, Machines, Sessions, Jobs, People, Settings and Help, each a
  page. On a
  phone it is the bar at the foot, in the same order: Home, Projects, Build,
  Containers, and More for the others.
- **The search** at the top jumps to a page, a project, a container or a
  node by its name.
- **The dock** at the foot of every page holds the chat and your terminals;
  a tab pulls it up, and on a phone it is a sheet.
- **The bell** holds what needs your answer, and **the dot** beside it is
  the doctor's verdict on this controller.

## The first five minutes

1. **Sign in** with the account you were given, and change the password on your
   Profile if somebody set it for you.
2. **Your profile** (the gear, top right, then Profile): your name, your email and the git
   identity your commits will carry. No session starts until these are set,
   because a commit with no author is a mess somebody else has to clean up.
3. **Install an agent, then sign in to it**, on each machine your projects
   work on. A node has no agent until the **Library** (under Build, with
   that node picked in the header) installs one: press Install on Claude
   Code, Codex CLI, Copilot CLI or Grok Build. Then press a project's **Start
   agent**: where you are not signed in on its node yet, it offers **Sign in
   on** that node, which opens that node's **Installed** page (under
   Machines) on that agent's own page. Press Sign in there: Claude's
   gives a link and takes the code back, ChatGPT's, Copilot's and Grok's
   give a link and a code to enter at OpenAI, GitHub or xAI. OpenCode signs
   in to nobody: it uses the model router an administrator set up. The login stays on that machine
   and is yours: it is not shared with the other people here, nobody else's
   sessions use it, and another node asks for its own the first time you
   work there.
4. **Open a project**: press its name for its page and notebook, **Start
   agent** for a session (its menu picks the agent, and resumes the last
   conversation or starts a new one), **Shell** for a plain shell. Terminals
   open in the dock at the foot of every page.
5. **Say what you want done.** A session starts already knowing this project's
   house rules, its roadmap and its open bugs, so you can ask for the thing
   rather than explaining the place.

## What is shared, and what is yours

The machines are shared. So is the disk the projects live on, and the store
the toolchains live on. Two people working on one project will see each
other's uncommitted changes, and the dashboard says so when it notices.

Your agents' logins are yours. Your terminal sessions are yours. Which projects
you can see is set per account, so a project you cannot see is not one you are
missing: you have not been given it.

## When something says no

A refusal is meant to name the way out, so read it rather than pressing again.
The four you are most likely to meet:

- **not signed in** to an agent: step 3 above, once per person on each node.
- **the node is away**: the machine a project builds on is not answering, so
  nothing runs there until it is back. It is not your doing.
- **a tool is missing**: builds use what the machine has, and installing more
  is an administrator's call, from the Library. Say what you needed.
- **a session may not push here**: the project's git policy keeps pushing with
  a person. Your commit is made; push it from the notebook's Git view.

## Telling somebody

Use the **Bugs** view (under Plan) on the project's page. It is the same tracker the
sessions read, so what you file is what gets picked up, and a report that says
what you pressed and what it said back is worth ten that say it broke. If the
dashboard itself is the thing that is broken, tell the person who gave you the
account, because a tracker on a box that is down helps nobody.

## Two habits worth having

**Ask which build is running before deciding a fix did not work.** The header's
About control carries the build the box is on, and `bb status` in any terminal prints it.

**Let the notebook hold the plan.** Anything you want a session to pick up later
belongs on the roadmap rather than in a message: the next session reads the
roadmap, and it never reads your chat history.

## As an administrator

- **Controller**: the machine the controller runs on (on a bare-metal
  install), its settings, each waiting for its Apply, how it is reached on
  the Network page, its keys and its audit log.
- **Machines**: the nodes where builds, tests, CI, the emulator and
  sessions run, what their disks hold, and what the Library put on each
  (Installed). Enroll node gives you the script to run on a machine.
- **Build**: the Library, where everything a node installs or runs comes
  from (coding agents, toolchains, tool packs, services and apps), its
  emulator, a phone lent to it and its CI runner.
- **Containers**: what runs on each node's Docker and its VMs; the nginx in
  front of them and the scanners are the System section's rows.
- **People**: accounts, roles and which projects each one sees.

A project's own settings are on its page. The Machines, Build and
Containers groups each show one node at a time, picked once in the header
over their pages.
