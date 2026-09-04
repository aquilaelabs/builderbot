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

Three roles and one special account. Not a permission matrix — a matrix is a
thing nobody maintains, and it answers questions nobody asked.

| Role | What it is |
|---|---|
| **owner** | The master admin. Exactly one, always. Its username can be changed; it cannot be deleted, demoted, locked or stripped of a project. Every other rule is a guard rail around that sentence. |
| **admin** | Everything the owner can do, *except* anything aimed at the owner — no deleting it, no demoting it, no changing its password. |
| **member** | Named projects only, and cannot destroy one. |

A member, on a project they have: sessions, the terminal, the notebook,
artifacts, dev instances, builds and tests — the work. Not: deleting, renaming,
trashing or re-noding the project, and nothing outside projects at all (Nodes,
Tools installs, Settings, Users, the phone).

The deny list is short and stated as a deny list on purpose. An allow list
grows a hole every time a feature lands and nobody remembers to add it; a deny
list fails closed the other way — a new surface is unavailable to members until
somebody decides it should not be.

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

Under this model a session is given **a scoped token**: one project, member
rights, revocable, and never a person's password. That is the actual fix for
bug #16, and it belongs here rather than in a separate effort — the token has
nowhere to come from until users exist.

## Enforcement

One helper resolving the request to a principal, one `may(principal, action,
project)`, and every endpoint that names a project asking it. The audit rows
already exist and already take a principal; they stop saying `operator` and
start saying who it was.

The rule to hold to: authorization is checked **on the server, per request**.
Hiding a button is a courtesy to the person, not a control.

## The surface

Tools → **Users**, opening a document tab like Nodes and Jobs. Rows of name,
role, projects and last seen; add, edit, remove. The owner's row carries no
delete control and says why, rather than offering one that fails.
