# Data and privacy

BuilderBot is software you run yourself. Everything it keeps stays on your
controller and your nodes, and nothing is ever sent to BuilderBot's authors:
there is no telemetry, no usage reporting and no account with us. This page
says what an install keeps about the people who use it, what it contacts on
their behalf, and how to remove it, so whoever runs one can tell their own
users.

## What an install keeps

On the controller, in its state directory (`/config`):

- **Accounts**: each person's sign-in name, full name, email address and git
  identity (what their commits carry), their roles, and their password as a
  salted PBKDF2 hash, never the password itself.
- **Devices signed in**: for each device an account
  pairs, its name, its kind and when it was paired and last seen.
- **The audit log**: when, who, what was done and to what, with a digest of
  the request rather than the request itself, so a token or an environment
  typed into a form is not kept in it.
- **Every project's notebook**: its roadmap, bugs, house rules, design,
  wiki, memories and chat, with who wrote each entry.
- **Notifications** each account was shown, and **problem reports** sessions
  filed about BuilderBot itself (`bb report`), both cleared from the
  dashboard. Reports pass through redaction before they are kept.
- **Node records**: each node's name, address and what it reported about
  itself.

On the projects share and the nodes:

- **Each project's files**, and its copy on the node it builds on.
- **The coding agents' own records**: each account's sign-in to each agent
  (Claude Code, Codex CLI, Copilot CLI) on each node, kept on that node and
  used only by that account's sessions, and the transcripts each agent writes
  of each session, under that account's own home (Claude Code's on the
  share).
- **Toolchains** installed into each node's store.

What it does not keep: BuilderBot writes no log of requests, so it holds no
record of the addresses people sign in from or of the pages they open.

## What it contacts

Only when something is used, and only from your own machines:

- **The agent's company**, through its agent: a Claude session sends the
  code and text it works with to Anthropic, a ChatGPT session to OpenAI and
  a Copilot session to GitHub, each under that person's own account and that
  company's terms, which they accept when they sign in to it.
- **GitHub and the container registries**, to check for newer images and
  apps, and **the git hosts** you add projects from.
- **Each toolchain's vendor**, when one is installed or checked for updates.
- **Cloudflare's API**, only if you turn on the controller's outside tunnel.

## Removing it

An administrator removes an account on the Users page, and a project, with
its notebook and files, by deleting it and purging it from the trash.
Notifications and problem reports are cleared from the dashboard. A
person's sign-in to an agent is removed by signing out on the
Installed page. The
whole install is removed by deleting the controller's `/config`, the
projects share and each node's store.

## If you run BuilderBot for other people

The data above is yours as the operator: you decide who has an account,
which projects they see and what an agent may do, and any duty to tell the
people you give accounts to how their data is handled is yours. This page is
meant as the basis for that notice. A BuilderBot that is reachable from the
internet holds the same data, so it also needs the care any service holding
accounts and source code does: HTTPS, strong passwords and timely updates.
