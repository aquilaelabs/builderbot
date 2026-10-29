#!/usr/bin/env python3
"""Writes docs/git-hosts.md from forgeaccess.ABILITIES (R188): what an agent
can do on a project's git host, and what to enable on GitHub, GitLab and
Gitea for each. The table is the one the controller measures a token
against and the relay refuses by, so the page is that table, never a copy
of it: bb lint holds the two equal with --check.

    python3 tools/git-hosts-doc.py           write the page
    python3 tools/git-hosts-doc.py --check   fail when the page is behind
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "dashboard"))
import forgeaccess  # noqa: E402

PAGE = os.path.join(HERE, "..", "docs", "git-hosts.md")

HEAD = """# What an agent can do on your git host

A session works its project's git host (GitHub, GitLab, Gitea or Forgejo)
with `bb forge`: pull requests, issues, CI runs and their logs, releases.
Every verb runs on the controller with the access token linked to the
project, so the token never reaches a node or a session. What a verb may do
is decided twice:

1. **The token.** The host only lets a token do what it was given. The
   controller measures what the project's token may do without changing
   anything (a read is asked; a write is sent with a required field missing,
   which the host refuses for its content when the token may write and
   outright when it may not), keeps the answer, and measures again when the
   token changes, when Measure is pressed and once a day.
2. **The project.** The project's Permissions view, On the git host, has
   Allow or Deny for each ability below. Deny takes the ability away
   whatever the token allows; Allow can never give more than the token has.
   Merging starts at Deny.

Every session is told at its start what the token lets it do and what to
ask for (`bb forge whoami` prints the same), and a verb the token cannot
do is refused with the permission it needs.

The token is linked on the project's settings, Git, or when the project is
made or linked, where *Which permissions?* opens this page.
"""

SETS = """## Ready sets

What to tick for the common cases, on GitHub's fine-grained token page
(**Settings, Developer settings, Personal access tokens, Fine-grained
tokens**), with only the project's repository chosen. Metadata: Read-only
is always there.

| For | Contents | Pull requests | Issues | Actions | Workflows |
|---|---|---|---|---|---|
| Reading only | Read-only | Read-only | Read-only | Read-only | |
| Branches and pull requests | Read and write | Read and write | Read-only | Read-only | |
| Everything BuilderBot offers | Read and write | Read and write | Read and write | Read and write | Read and write |

On GitLab a project access token with the Developer role and the `api`
scope covers everything offered; `read_api` and `read_repository` alone
read. On Gitea and Forgejo, `write:repository` and `write:issue`, and their
read halves to read.
"""

TERMS = """## The terms

A token acts as its account, so what an agent does with it is that
account's doing under the host's terms, and the person's. GitHub allows a
machine account beside a person's own, which is the cleaner choice for an
agent: its pull requests and comments then say who wrote them, and taking
the token away takes nothing from the person. Nothing here automates in
bulk; the relay asks one thing at a time and an agent works one project.
"""


def render():
    out = [HEAD, "## The abilities\n",
           "| Ability | GitHub (fine-grained) | GitHub (classic) | GitLab | Gitea and Forgejo | Through |",
           "|---|---|---|---|---|---|"]
    for a in forgeaccess.ABILITIES:
        gh = f"{a['gh'][0]}: {'Read and write' if a['gh'][1] == 'write' else 'Read-only'}"
        if a.get("also"):
            gh += f", {a['also'][0]}: Read and write"
        how = ", ".join(f"`bb forge {v}`" for v in a["verbs"]) or a["how"]
        start = " (starts at Deny)" if a["default"] == "deny" else ""
        out.append(f"| {a['label']}{start} | {gh} | {a['classic']} | {a['gitlab']} | {a['gitea']} | {how} |")
    out += ["", "Where a host has no word for something, the verb says so rather than doing",
            "something else: GitLab has no request for changes on a merge request, and",
            "Gitea's API cannot rerun a CI run.", "",
            "## Not offered", "",
            "Named so nobody looks for them, and never done by an agent:", ""]
    for what, why in forgeaccess.NOT_OFFERED:
        out.append(f"- **{what}**: {why}.")
    out += ["", SETS, TERMS]
    return "\n".join(out).rstrip("\n") + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        try:
            have = open(PAGE, encoding="utf-8").read()
        except OSError:
            have = ""
        if have != text:
            print("  [fail] docs/git-hosts.md is behind forgeaccess.ABILITIES: python3 tools/git-hosts-doc.py")
            raise SystemExit(1)
        print("  [ok]   docs/git-hosts.md is forgeaccess.ABILITIES, word for word")
        raise SystemExit(0)
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(text)
