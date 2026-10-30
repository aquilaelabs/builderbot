# Versions and release lines

A project's version is its `VERSION` file, moved by `bb version bump` and
`bb version set` where the project's policy lets a session move it, and
released with `bb version release`. Between releases a build is
`X.Y.Z-dev.N`, where X.Y.Z is the release the work is heading for.

## Two releases at once

A branch has a *line*: the release it works toward. A branch named for a
release (`claude/0.7.0`) has that line by its name; any other takes one
with `bb version line X.Y.Z` on it (kept in git's own config for the
branch, so it never travels in a commit), and `bb version line none` goes
back to the name's. A build on a branch heads for its line, so work toward
0.7.0 builds as `0.7.0-dev.N` while a fix on `claude/0.6.2` builds as
`0.6.2-dev.N`, and the Artifacts view and the dashboard's version say which.

A roadmap item or one of its steps is meant for a release with `bb roadmap
target N X.Y.Z` (or `N.M` for a step); `bb roadmap --target X.Y.Z` lists
what is meant for one.

A *patch line* is one whose last number is above 0 (0.6.2). There a bump or
a release is refused for anything but the patch, and the gate holds the
project's own rules for what a patch may not change: a house rule named
`patch`, or `patch-` and a word, says in its files what that is (`bb rules
add patch "A patch adds no migration and keeps the API." --files
"scripts/dashboard/statemigrations, docs/api.md"`), and `bb tests
preflight` on a patch line fails on a changed file under one. BuilderBot's
own lint refuses a new state migration on a patch line.

## Two channels

A controller installed bare metal (or the OS) updates from GitHub's
releases: the *normal* channel, which is every published release (`vX.Y.Z`)
and never a pre-release. A *dev* channel takes the pre-releases CI
publishes from a dev build: a tag `vX.Y.Z-dev.N` built by the same workflow
as a release, marked a pre-release and never the latest, with the same
files (the controller bundle, the OS image, the stick disk, the APK). The
channel is picked under Controller settings, Updates, and the dev channel
is offered only on a controller started for development with its dev
switch on; every other install sees the normal channel alone and the
pre-releases never, and an ordinary start puts the channel back to normal. On
the dev channel Check now, Update and the update window take the newest
of the releases and the dev builds by rank (a release stands above every
dev build heading for it, a dev build by its ordinal), so a dev build
moves to a later dev build or to the release it was heading for. A dev
build is not a release: it may not come up, and the OS image's slot
fallback is what brings the machine back. `bb version release --dev` cuts
such a tag on this commit (no bump, no changelog section) and pushes it;
the stick maker's `--latest` and `--release` take only the normal channel.

## What a release upgrades from

Each release says how far back it reaches, in two numbers.

- **The state floor** is the oldest `/config` it moves forward
  (`SUPPORTED_FROM` in `scripts/dashboard/stateversion.py`). 0.9 reads state 2,
  what 0.6.0 shipped, so any 0.6.x, 0.7.x or 0.8.x install upgrades in one
  step. An older `/config` is refused at start with the release to go through
  first (`THROUGH`), and the migrations under the floor are gone from the tree.
- **The agent's window** is the minor of `AGENT_VERSION`. A node whose agent is
  from another window takes nothing but its own update, and its projects'
  sessions wait until it has it. The controller keeps what the previous
  window's agents need to be updated and to hand over what they left on the
  node, and nothing older.

There is no downgrade. A container goes back by restoring the copy the
upgrade took (`backups/before-VERSION`) under the older image. A bare-metal
install goes back by itself only when a new release does not answer after an
update.

## Moving work between the lines

- **Forward.** Once a patch line is released, `bb version forward
  claude/0.6.2` on the later line's branch merges it in: its fixes carried,
  the later line's `VERSION` kept, and the changelog stitched, the patch's
  dated section placed among the others by version and any entry it
  already released taken out of the later line's Unreleased, so a fix made
  on both lines is said once, under the release that shipped it. A patch
  line with changelog entries not yet released is refused until it is
  released. A conflict elsewhere is left in the tree, named, for a person.
- **Back.** A fix made on the later line first is carried back with `bb
  version backport COMMIT` on the patch line's branch: cherry-picked with
  its origin named in the message, the patch line's `VERSION` kept, and the
  changelog entries the commit added put under the patch line's Unreleased
  in their own categories.
