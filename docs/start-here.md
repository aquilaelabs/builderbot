# Start here

You have an account on somebody's BuilderBot. This page is the whole of what
you need to do something useful with it; [how-it-works.md](how-it-works.md)
is the overview, and each part of the dashboard has a doc of its own beside
it in Help.

## What it is

A Claude Code workstation you reach in a browser. Each project on the Projects page
is a git repository on a shared disk. A **session** is Claude working in that
repository, on one of the machines behind the dashboard, with a terminal you
can watch and type into. A project's page holds its **notebook**, where you and
Claude keep the plan: the roadmap, the bugs, the house rules and the git view.

Nothing runs on your laptop, and nothing here is on your laptop. Close the tab
and a session keeps going.

## The first five minutes

1. **Sign in** with the account you were given, and change the password on your
   Profile if somebody set it for you.
2. **Your profile** (the gear, top right, then Profile): your name, your email and the git
   identity your commits will carry. No session starts until these are set,
   because a commit with no author is a mess somebody else has to clean up.
3. **Install Claude Code, then sign in to Claude**, on each machine your
   projects work on. A node has no Claude Code until the **Toolchains**
   page (under Build, with that node picked) installs it: tick Claude Code,
   press Install selected. Then press a project's **Start Claude**: where you are not signed in on its node yet,
   it offers **Sign in on** that node, which opens the node's page at its
   Claude Code section. Press Sign in there, open the link, and paste the
   code back. The login stays on that machine and is yours: it is not
   shared with the other people here, nobody else's sessions use it, and
   another node asks for its own the first time you work there.
4. **Open a project**: press its name for its page and notebook, **Start
   Claude** for a session, **Shell** for a plain shell. Terminals open in the
   dock at the foot of every page.
5. **Say what you want done.** A session starts already knowing this project's
   house rules, its roadmap and its open bugs, so you can ask for the thing
   rather than explaining the place.

## What is shared, and what is yours

The machines are shared. So is the disk the projects live on, and the store
the toolchains live on. Two people working on one project will see each
other's uncommitted changes, and the dashboard says so when it notices.

Your Claude login is yours. Your terminal sessions are yours. Which projects
you can see is set per account, so a project you cannot see is not one you are
missing: you have not been given it.

## When something says no

A refusal is meant to name the way out, so read it rather than pressing again.
The four you are most likely to meet:

- **not signed in to Claude**: step 3 above, once per person on each node.
- **the node is away**: the machine a project builds on is not answering, so
  nothing runs there until it is back. It is not your doing.
- **a tool is missing**: builds use what the machine has, and installing more
  is an administrator's call, on the Toolchains page. Say what you needed.
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

**Let the notebook hold the plan.** Anything you want Claude to pick up later
belongs on the roadmap rather than in a message: the next session reads the
roadmap, and it never reads your chat history.
