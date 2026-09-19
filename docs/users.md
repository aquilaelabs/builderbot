# Users, roles and project access

*Design, 4 September 2026. Nothing here is built yet: roadmap #22 carries the
steps. Read this before starting one.*

## The problem

There is exactly one credential, it lives in the environment, and it is
absolute. `DASHBOARD_AUTH=user:password` gets you the dashboard, and the
dashboard has no idea who you are once you are in: every button is available to
whoever opened the page. Three things follow.

- There is no way to let somebody work on one project without handing them
  every project, the Nodes tab, the package installer and the phone.
- A Claude session is given that same credential, so "the operator only" is a
  convention rather than a mechanism (bug #16).
- It is the last big thing hardwired into the template. Everything else the
  controller owns has been moving into the GUI (docs/nodes.md §11); this has
  not, because there was nowhere for it to go.

## The model

Three roles and one special account. Not a permission matrix: a matrix is a
thing nobody maintains, and it answers questions nobody asked.

| Role | What it is |
|---|---|
| **owner** | The master admin. Exactly one, always. Its username can be changed; it cannot be deleted, demoted, locked or stripped of a project. Every other rule is a guard rail around that sentence. |
| **admin** | Everything the owner can do, *except* anything aimed at the owner: no deleting it, no demoting it, no changing its password. |
| **user** | Named projects, and the work inside them. Not where that work runs. |

A user, on a project they have: sessions, the terminal, the notebook,
artifacts, dev instances, builds and tests, and the project's own build and
test commands. Not: deleting, renaming or trashing it, and nothing outside the
projects they were given.

**Which node a project builds on, and that node's configuration, are an
admin's.** There was briefly a fourth role that could do those two things; it
went, and the reason is the thing worth keeping: *a node is shared*. Changing
the stores or the network of the node project A builds on changes it for every
other project on that node, including ones the person doing it cannot see.
That is not a project-scoped act however it is reached, so it does not belong
to a project-scoped role. Enrollment, revocation, retiring, runner installs
and agent updates were never in question and stay with an admin too.

In the project's settings dialog this is a field, not a page: a user opens the
dialog and edits the build command, and the node select is not theirs to
change.

The deny list is short and stated as a deny list on purpose. An allow list
grows a hole every time a feature lands and nobody remembers to add it; a deny
list fails closed the other way: a new surface is unavailable to users until
somebody decides it should not be.

## Storage

`/config/users.json`, with the load/save/lock the notebook files already use.
Never committed, never in the image, `0600`.

Passwords are `pbkdf2_hmac('sha256', …)` from the standard library: the
dashboard has no dependencies and is not acquiring one for this. Per-user
salt, and the iteration count stored *in the record* so it can be raised later
without invalidating everybody.

## No env var

The first page a container with no accounts serves is the **first-run
screen**, and it asks for the owner's name and password; until that is done
nothing else is reachable, and after it the store is the truth. Nothing at
boot reads a credential from the environment: one there stays readable
forever. The one place `DASHBOARD_AUTH=name:password` is honoured is `bb`,
for a single command from a plain `docker exec` shell that has no session
token.

Which leaves the obvious question: what happens when the owner forgets the
password. The answer is the one every system gives; you need the machine.
`bb users passwd <name>`, in the container, resets it. Whoever can `docker
exec` into this container can already read everything in it.

## Sessions

The `bb_session` cookie already exists; it grows a user id, and tokens are kept
server-side with an expiry. Basic auth stays exactly as it is, checked against
the user store instead of one string, because `bb` and the test suite use it
and should keep working unchanged.

## What a Claude session gets, and bug #16

Today a session inherits the operator's credential, which is why "only the
operator can install a package" is a rule the code asks nicely about.

Under this model a session is given **a scoped token**: one project, `user`
rights, revocable, and never a person's password. That is the actual fix for
bug #16, and it belongs here rather than in a separate effort: the token has
nowhere to come from until users exist.

## Enforcement, and why it is mostly one function

A project you cannot see does not appear, not greyed out, not present and
refused. Absent.

That is cheaper than it sounds, because there is already one chokepoint.
`server.project_list()` is what enumerates the projects share, and all
seventeen of its callers go through it: the sidebar, the state payload, and
every `if name not in {p["name"] for p in project_list()}` guard. Filter it by
the requesting principal and three things happen at once.

- The GUI stops listing what the person cannot see, everywhere, because
  everywhere reads the same list.
- **The existence check becomes the permission check.** Somebody asking
  `/api/roadmap?project=payroll` gets *not a project*: the same answer a typo
  gets. No separate `may()` call at those seventeen sites, and no way to probe
  which projects exist by comparing error messages.
- Anything added later that lists projects is covered on the day it is
  written, because it will call the same function.

What is left for `may()` is the short deny list on projects a user *does*
have: delete, rename, trash, and changing the node it builds on. A handful of
endpoints, named explicitly.

The rule to hold to: filtering happens **on the server**. Hiding a row in the
page is a courtesy to the person, not a control.

## What this is, and what it is not

Worth stating plainly, because the gap between these two is where security
theatre grows.

**Any account with a Claude session is a powerful thing.** Code
generation plus a shell is most of a computer. The session's own boundary is
the sibling-project deny list, and that is a guardrail rather than a sandbox:
the file tools refuse the other projects, `Bash` is not covered, and
CLAUDE.md says so out loud. So somebody who wants to read a project they were
not given can, with effort, from a session they were given.

These roles are therefore for **scoping, not containment**: deciding who works
on what, keeping the dashboard honest about it, and making the audit trail
name a person. It is meant for people you would already trust with a shell on
this box. It is not a defence against one of them deciding to go looking.

Building it as though it were would mean sandboxing every session, and that is
a different and much larger project, and one the node work has quietly made
tractable: a person who needs a hard boundary gets their own node, where the
boundary is a machine rather than a rule. Until somebody needs that, this is
the honest amount of mechanism.

## The surface

Tools → **Users**, opening a document tab like Nodes and Jobs. Rows of name,
role, projects and last seen; add, edit, remove. The owner's row carries no
delete control and says why, rather than offering one that fails.
