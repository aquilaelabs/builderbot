# Changelog

## Unreleased

- The Artifacts tab now shows each product's version, who may move it, and this changelog (5a7b49c)
- A repo that ships two products can version each one on its own — an extension beside an app no longer share one number (d9ae96d)
- A project with no version yet can be given one from the Artifacts tab, or ask the project's Claude session to propose one (5a7b49c)
- Every version gets a changelog beside it: sessions log what changed for you, and a bump dates the accumulated entries (a2e21cc)
- An unreleased bump can be taken back — the number returns, its changelog entries rejoin the queue, the code stays (cb5cbad)
- Model and effort for everything sent to Claude are set once on a sidebar card instead of being asked at every send (9b8c1b2)
- The version stamp in the header became an About popup — no more truncated string on a phone (3accee0)
- Sessions no longer open on a wall of yellow permission warnings (d9508b0)
- Long lists in the notebook show a page at a time, with a Show more control (7a6cf2d)
- A version bump now stages until you press Save — Revert or leaving the page discards it (7a6cf2d)
- The Claude card now says which model Claude is actually on, not just what it would switch to (b38d4db)
- Asking Claude about a version now lands in the session instead of sitting unsent in the prompt (b38d4db)
