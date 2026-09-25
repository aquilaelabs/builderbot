# Start here

You have an account on somebody's BuilderBot. This page is the whole of what
you need to do something useful with it; [how-it-works.md](how-it-works.md)
is the reference, and it is long because it is a reference.

## What it is

A Claude Code workstation you reach in a browser. Each project on the left is
a git repository on a shared disk. A **session** is Claude working in that
repository, on one of the machines behind the dashboard, with a terminal you
can watch and type into. The **notebook** beside each project is where you and
Claude keep the plan: the roadmap, the bugs, the house rules and the git view.

Nothing runs on your laptop, and nothing here is on your laptop. Close the tab
and a session keeps going.

## The first five minutes

1. **Sign in** with the account you were given, and change the password from
   the gear menu if somebody set it for you.
2. **Your profile** (the gear, top right): your name, your email and the git
   identity your commits will carry. No session starts until these are set,
   because a commit with no author is a mess somebody else has to clean up.
3. **Sign in to Claude.** The card under Doctor says, in red, that you are not
   signed in and that sessions will not start. Press Sign in: it runs on one
   of the machines, you paste the code back, and the login stays on that
   machine. It is yours. It is not shared with the other people here, and
   nobody else's sessions use it.
4. **Open a project**: press its name for the notebook, **Claude** for a
   session, the terminal button for a plain shell.
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

- **not signed in to Claude**: step 3 above, once per person.
- **the node is away**: the machine a project builds on is not answering, so
  nothing runs there until it is back. It is not your doing.
- **a tool is missing**: builds use what the machine has, and installing more
  is an administrator's call, on the Toolchains tab. Say what you needed.
- **a session may not push here**: the project's git policy keeps pushing with
  a person. Your commit is made; push it from the notebook's Git view.

## Telling somebody

Use the **Bugs** tab in the project's notebook. It is the same tracker the
sessions read, so what you file is what gets picked up, and a report that says
what you pressed and what it said back is worth ten that say it broke. If the
dashboard itself is the thing that is broken, tell the person who gave you the
account, because a tracker on a box that is down helps nobody.

## Two habits worth having

**Ask which build is running before deciding a fix did not work.** The header
carries the commit the box is on, and `bb status` in any terminal prints it.

**Let the notebook hold the plan.** Anything you want Claude to pick up later
belongs on the roadmap rather than in a message: the next session reads the
roadmap, and it never reads your chat history.
