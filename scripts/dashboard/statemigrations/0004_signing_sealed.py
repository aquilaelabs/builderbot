"""State 3 to 4: the projects' signing keys sealed at rest (R111 step 2).

  * nothing is rewritten here: the keys are sealed by the dashboard at its
    start (signing.seal_all), under the install's signing secret, which is
    never in /config and so is not this migration's to read. A start with
    no secret keeps them as they were.
  * the number is what moves: a sealed key is a file an older build cannot
    open, so an older build refuses to start on this /config rather than
    failing at the first signing.

Never edited once shipped (stateversion.py).
"""


def run(ctx):
    return
