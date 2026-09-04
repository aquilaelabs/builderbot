# Users, roles and project access

*Design, 4 September 2026. Nothing here is built yet — roadmap #22 carries the
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

Four roles and one special account. Not a permission matrix — a matrix is a
thing nobody maintains, and it answers questions nobody asked.

| Role | What it is |
|---|---|
| **owner** | The master admin. Exactly one, always. Its username can be changed; it cannot be deleted, demoted, locked or stripped of a project. Every other rule is a guard rail around that sentence. |
| **admin** | Everything the owner can do, *except* anything aimed at the owner — no deleting it, no demoting it, no changing its password. |
| **superuser** | Named projects, and the machinery behind them: which node a project builds on, and that node's own configuration. |
| **user** | Named projects, and the work inside them. Not where that work runs. |

Both project roles get, on a project they have: sessions, the terminal, the
notebook, artifacts, dev instances, builds and tests, the project's own build
and test commands. Neither can delete, rename or trash a project, and neither
sees anything outside the projects they were given.

The line between them is **reach**. Everything a user does stops at the
project; the two things a superuser adds do not.

| | user | superuser |
|---|---|---|
| Change which node the project builds on | no | yes |
| Edit that node's stores, mounts, network | no | yes |
| Enroll, revoke, retire a node; install a runner; update an agent | no | no — admin |
| Delete, rename or trash a project | no | no |
| Tools installs, Settings, Users, the phone | no | no |

**Say this out loud when handing somebody superuser: a node is shared.**
Changing the stores or the network of the node project A builds on changes it
for every other project on that node, including ones this person cannot see.
It is the one place a project role reaches past its own projects, and it is
why it is a role of its own rather than something a user simply gets. The
Nodes tab for a superuser shows the nodes their projects use and lets them
configure those; enrollment and revocation stay with an admin.

In the project's settings dialog this is a field, not a page: a user sees the
dialog and edits the build command, and the node select is not theirs to
change.

The deny lists are short and stated as deny lists on purpose. An allow list
grows a hole every time a feature lands and nobody remembers to add it; a deny
list fails closed the other way — a new surface is unavailable until somebody
decides it should not be.

## Storage

`/config/users.json`, with the load/save/lock the notebook files already use.
Never committed, never in the image, `0600`.

Passwords are `pbkdf2_hmac('sha256', …)` from the standard library — the
dashboard has no dependencies and is not acquiring one for this. Per-user
salt, and the iteration count stored *in the record* so it can be raised later
without invalidating everybody.

## Getting there from one env var

`DASHBOARD_AUTH` **seeds the owner once**, on the first boot that finds no
users file, and is ignored ever after. That is the unhardwiring pattern the
node path mapping already used: the env seeds, the store owns. It matters that
it stops being honoured — a credential that keeps working forever is a back
door, not a migration.

Which leaves the obvious question: what happens when the owner forgets the
password. The answer is the one every system gives — you need the machine.
`bb users passwd <name>`, in the container, resets it. Whoever can `docker
exec` into this container can already read everything in it.

## Sessions

The `bb_session` cookie already exists; it grows a user id, and tokens are kept
server-side with an expiry. Basic auth stays exactly as it is, checked against
the user store instead of one string, because `bb` and the test suite use it
and should keep working unchanged.

## What a Claude session gets — and bug #16

Today a session inherits the operator's credential, which is why "only the
operator can install a package" is a rule the code asks nicely about.

Under this model a session is given **a scoped token**: one project, `user`
rights, revocable, and never a person's password. That is the actual fix for
bug #16, and it belongs here rather than in a separate effort — the token has
nowhere to come from until users exist.

## Enforcement, and why it is mostly one function

A project you cannot see does not appear — not greyed out, not present and
refused. Absent.

That is cheaper than it sounds, because there is already one chokepoint.
`server.project_list()` is what enumerates the projects share, and all
seventeen of its callers go through it: the sidebar, the state payload, and
every `if name not in {p["name"] for p in project_list()}` guard. Filter it by
the requesting principal and three things happen at once.

- The GUI stops listing what the person cannot see, everywhere, because
  everywhere reads the same list.
- **The existence check becomes the permission check.** Somebody asking
  `/api/todo?project=payroll` gets *not a project* — the same answer a typo
  gets. No separate `may()` call at those seventeen sites, and no way to probe
  which projects exist by comparing error messages.
- Anything added later that lists projects is covered on the day it is
  written, because it will call the same function.

What is left for `may()` is the short deny list on projects somebody *does*
have: delete, rename and trash for both project roles, and re-noding plus node
configuration for a user but not a superuser. A handful of endpoints, named
explicitly.

The rule to hold to: filtering happens **on the server**. Hiding a row in the
page is a courtesy to the person, not a control.

## What this is, and what it is not

Worth stating plainly, because the gap between these two is where security
theatre grows.

**Any account with a Claude session is a powerful thing.** Code
generation plus a shell is most of a computer. The session's own boundary is
the sibling-project deny list, and that is a guardrail rather than a sandbox —
the file tools refuse the other projects, `Bash` is not covered, and
CLAUDE.md says so out loud. So somebody who wants to read a project they were
not given can, with effort, from a session they were given.

These roles are therefore for **scoping, not containment**: deciding who works
on what, keeping the dashboard honest about it, and making the audit trail
name a person. It is meant for people you would already trust with a shell on
this box. It is not a defence against one of them deciding to go looking.

Building it as though it were would mean sandboxing every session, and that is
a different and much larger project — and one the node work has quietly made
tractable: a person who needs a hard boundary gets their own node, where the
boundary is a machine rather than a rule. Until somebody needs that, this is
the honest amount of mechanism.

## The surface

Tools → **Users**, opening a document tab like Nodes and Jobs. Rows of name,
role, projects and last seen; add, edit, remove. The owner's row carries no
delete control and says why, rather than offering one that fails.
