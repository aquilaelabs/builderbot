"""State 10 to 11: a project's git token is the key store's of the person who
gave it (R154; the operator, 27 Oct).

  * nothing is rewritten here: each token kept as a project's own, from
    before, goes into the key store of the project's owner (BuilderBot's
    owner where a project has none) and the project is linked to it, by the
    dashboard at its start (gitcreds.adopt), since that store is sealed
    under the owner's own key, which opens only under the install key, and
    neither is this migration's to read. A start with no install key keeps
    the tokens as they are until one is made.
  * the number is what moves: a project's file that names an account's
    entry is one an older build reads as a token that does not work, so an
    older build refuses to start on this /config rather than pushing with
    nothing.

Never edited once shipped (stateversion.py).
"""


def run(ctx):
    return
