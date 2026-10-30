# What an agent can do on your git host

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

## The abilities

| Ability | GitHub (fine-grained) | GitHub (classic) | GitLab | Gitea and Forgejo | Through |
|---|---|---|---|---|---|
| Read the code and its history | Contents: Read-only | repo, or public_repo for a public repository | read_repository | read:repository | git fetch and pull (bb git) |
| Push branches | Contents: Read and write | repo | write_repository | write:repository | bb git push, under Permissions: Pushing |
| Change CI workflow files | Workflows: Read and write | workflow | write_repository | write:repository | a push that touches .github/workflows |
| Read pull requests | Pull requests: Read-only | repo | read_api | read:repository | `bb forge pr list`, `bb forge pr view` |
| Open, update, comment on and review pull requests | Pull requests: Read and write | repo | api | write:repository | `bb forge pr create`, `bb forge pr comment`, `bb forge pr review`, `bb forge pr close` |
| Merge pull requests (starts at Deny) | Pull requests: Read and write, Contents: Read and write | repo | api | write:repository | `bb forge pr merge` |
| Read issues | Issues: Read-only | repo | read_api | read:issue | `bb forge issue list`, `bb forge issue view` |
| Open, comment on, label and close issues | Issues: Read and write | repo | api | write:issue | `bb forge issue create`, `bb forge issue comment`, `bb forge issue close`, `bb forge issue label` |
| Read CI runs and their logs | Actions: Read-only | repo | read_api | read:repository | `bb forge run list`, `bb forge run view`, `bb forge run log` |
| Rerun and start CI workflows | Actions: Read and write | repo, and workflow to start one | api | write:repository | `bb forge run rerun`, `bb forge run dispatch` |
| Read releases | Contents: Read-only | repo | read_api | read:repository | `bb forge release list`, `bb forge release view` |
| Publish and edit releases | Contents: Read and write | repo | api | write:repository | bb version release, under Agents may: Tag and publish a release |

Where a host has no word for something, the verb says so rather than doing
something else: GitLab has no request for changes on a merge request, and
Gitea's API cannot rerun a CI run.

## Not offered

Named so nobody looks for them, and never done by an agent:

- **Delete, transfer, archive or rename the repository, or change its visibility**: Administration: the repository's existence is the person's.
- **Branch protection and rulesets**: Administration: the person's guard against the agent itself.
- **Collaborators, teams and organization members**: Administration and Members: who may reach the work.
- **Secrets, variables, deploy keys and webhooks**: a session never handles a credential, and a webhook sends the work elsewhere.
- **Billing, the account's settings and its keys**: the account is the person's.

## Ready sets

What to tick for the common cases, on GitHub's fine-grained token page
(**Settings, Developer settings, Personal access tokens, Fine-grained
tokens**), with only the project's repository chosen. Metadata: Read-only
is always there. On an organization's repository, the organization may have
to approve the token first (its **Settings, Personal access tokens, Pending
requests**); until it does, GitHub lets the token read what is public and
refuses every push. A person keeps one token for each host and account:
giving a new one replaces the one before for every project that used it.

| For | Contents | Pull requests | Issues | Actions | Workflows |
|---|---|---|---|---|---|
| Reading only | Read-only | Read-only | Read-only | Read-only | |
| Branches and pull requests | Read and write | Read and write | Read-only | Read-only | |
| Everything BuilderBot offers | Read and write | Read and write | Read and write | Read and write | Read and write |

On GitLab a project access token with the Developer role and the `api`
scope covers everything offered; `read_api` and `read_repository` alone
read. On Gitea and Forgejo, `write:repository` and `write:issue`, and their
read halves to read.

## The terms

A token acts as its account, so what an agent does with it is that
account's doing under the host's terms, and the person's. GitHub allows a
machine account beside a person's own, which is the cleaner choice for an
agent: its pull requests and comments then say who wrote them, and taking
the token away takes nothing from the person. Nothing here automates in
bulk; the relay asks one thing at a time and an agent works one project.
